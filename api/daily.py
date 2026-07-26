"""Vercel Python serverless function: the daily challenge + leaderboard.

    GET  /api/daily            -> today's puzzle (no answer key), a signed
                                  session token, and the current leaderboard
    GET  /api/daily?board=1    -> leaderboard only (cheap refresh)
    GET  /api/daily?calendar=YYYY-MM
                               -> that month's played days, each with its
                                  shape, theme and top of the board
    GET  /api/daily?play=YYYY-MM-DD
                               -> a past daily to replay for fun: the full
                                  payload (solution included), no session
                                  token, no route to the leaderboard
    POST /api/daily {"action": "finish", "token": ..., "rows": [[label,..],..],
                     "steps": N}
        -> verifies the solution server-side against the regenerated puzzle;
           on success returns the official (server-measured) time and a
           signed single-use result token
    POST /api/daily {"action": "claim", "result_token": ..., "name": "..."}
        -> filters the name, inserts the score (result tokens are single-use,
           entries per network per day are capped), returns rank + fresh board

The pure logic lives in ``logicgrid.daily`` (deterministic generation,
tokens, name filter) and ``logicgrid.dailystore`` (Supabase REST), so this
layer stays thin and unit-testable like api/puzzle.py.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the repo root importable so ``logicgrid`` resolves in the function bundle.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logicgrid import daily, dailystore  # noqa: E402

_MAX_BODY = 64 * 1024


def _secret() -> str | None:
    return os.environ.get("DAILY_SECRET") or None


def _ip_hash(ip: str | None, secret: str) -> str | None:
    """A keyed, truncated hash — enough to spot one machine flooding the
    board, without storing raw addresses."""
    if not ip:
        return None
    return hashlib.sha256(f"{secret}:{ip}".encode()).hexdigest()[:16]


def _board_rows(day) -> list[dict]:
    """Leaderboard entries in client shape (no sid)."""
    return [
        {"name": r["name"], "time_ms": r["time_ms"], "steps": r.get("steps")}
        for r in dailystore.top_scores(day)
    ]


def _daily_payload(day, secret: str) -> tuple[dict, int]:
    """The day's full payload. The store caches the whole generated payload
    (not just the seed): generation is a multi-second generate-and-grade run,
    and with the cache a request — crucially a solve submission awaiting its
    verdict — costs one row read. Falls back to the deterministic candidate
    walk if the store is unavailable, so the daily never goes down with it."""
    row = None
    if dailystore.configured():
        try:
            row = dailystore.get_daily_row(day)
        except dailystore.StoreError:
            row = None  # degrade: deterministic walk still converges
    if row and row.get("payload"):
        return row["payload"], row["seed"]

    seed = row["seed"] if row else None
    payload, chosen = daily.build_daily(day, secret, seed=seed)
    if dailystore.configured():
        try:
            if row is None:
                dailystore.save_daily_row(
                    day, chosen, payload["theme"], payload["difficulty"], payload
                )
            else:  # row from before the payload cache existed — backfill it
                dailystore.update_daily_payload(day, payload)
        except dailystore.StoreError:
            pass  # cache miss only costs the next request a regeneration
    return payload, chosen


def _month_bounds(text: str):
    """(first, last) dates of a "YYYY-MM", or None if it isn't one."""
    try:
        year, month = (int(part) for part in text.split("-", 1))
        first = daily.date(year, month, 1)
    except (ValueError, TypeError):
        return None
    last_day = calendar.monthrange(first.year, first.month)[1]
    return first, first.replace(day=last_day)


def _calendar(month: str) -> tuple[int, dict]:
    """A month of past dailies with each day's board.

    Days come from the store, because a day only exists once it was actually
    played — the schedule alone would invent dailies for dates the site wasn't
    live. Shape falls back to the weekday schedule, which is deterministic, for
    rows written before it was recorded.
    """
    bounds = _month_bounds(month)
    if bounds is None:
        return 400, {"error": "month must look like YYYY-MM"}
    first, last = bounds
    today = daily.today_utc()
    if first > today:
        return 200, {"month": month, "today": today.isoformat(), "days": []}
    last = min(last, today)  # never advertise a day that hasn't been played yet
    if not dailystore.configured():
        return 503, {"error": "the archive is unavailable right now"}

    try:
        rows = dailystore.puzzles_in_range(first, last)
        scores = dailystore.scores_in_range(first, last)
    except dailystore.StoreError:
        return 503, {"error": "the archive is unavailable right now"}

    by_day: dict[str, list[dict]] = {}
    for row in scores:
        by_day.setdefault(row["day"], []).append(row)

    names = {t["key"]: t["name"] for t in daily.list_themes()}
    days = []
    for row in rows:
        iso = row["day"]
        entries = by_day.get(iso, [])
        _band, categories, items = daily.daily_config(daily.date.fromisoformat(iso))
        days.append({
            "date": iso,
            "theme": row["theme"],
            "theme_name": names.get(row["theme"], row["theme"]),
            "difficulty": row["difficulty"],
            "categories": categories,
            "items": items,
            "entries": len(entries),
            "top": [
                {"name": e["name"], "time_ms": e["time_ms"], "steps": e.get("steps")}
                for e in entries[:dailystore.ARCHIVE_TOP]
            ],
        })
    return 200, {"month": month, "today": today.isoformat(), "days": days}


def _replay(day_text: str, secret: str) -> tuple[int, dict]:
    """A past daily, served to be replayed for fun.

    Everything today's payload withholds — the solution, the seed — comes back
    here, because the reason for withholding it is gone: a closed day's board
    can't be posted to, so there is no position to protect and the puzzle can
    behave like free play (Check, Hint, Reveal all work client-side).

    The window that makes that safe is narrow, so the guard is strict. Today is
    obviously off limits. So is YESTERDAY: ``validate_session`` accepts a
    session token for either day, so someone who opened yesterday's puzzle
    before midnight UTC can still be holding a live session against a board
    that is still accepting entries. Only days beyond that window are replays.

    A day with no stored row is a day that never ran, and generating one here
    would invent a daily retroactively — so that's a 404, not a fresh puzzle.
    """
    try:
        day = daily.date.fromisoformat(day_text)
    except (ValueError, TypeError):
        return 400, {"error": "day must look like YYYY-MM-DD"}

    newest_replayable = daily.today_utc() - daily.timedelta(days=2)
    if day > newest_replayable:
        return 403, {
            "error": "that daily is still live — it can be replayed once its board closes"
        }
    if not dailystore.configured():
        return 503, {"error": "past dailies are unavailable right now"}

    try:
        row = dailystore.get_daily_row(day)
    except dailystore.StoreError:
        return 503, {"error": "past dailies are unavailable right now"}
    if not row:
        return 404, {"error": "no daily was played on that day"}

    payload = row.get("payload")
    if not payload:  # a row from before the payload cache — rebuild from its seed
        payload, _seed = daily.build_daily(day, secret, seed=row["seed"])
    # No session token is issued, and none would validate for a day this old:
    # a replay has no route to the leaderboard at all.
    return 200, {"date": day.isoformat(), "puzzle": payload, "replay": True}


def _build_get_response(query: dict, now: float | None = None) -> tuple[int, dict]:
    secret = _secret()
    if secret is None:
        return 503, {"error": "the daily challenge isn't configured yet (DAILY_SECRET)"}
    day = daily.today_utc()

    if "calendar" in query:
        return _calendar(query["calendar"][0] or day.strftime("%Y-%m"))

    if "play" in query:
        return _replay(query["play"][0], secret)

    if "board" in query:
        try:
            return 200, {"date": day.isoformat(), "leaderboard": _board_rows(day)}
        except dailystore.StoreError:
            return 503, {"error": "leaderboard is unavailable right now"}

    payload, _seed = _daily_payload(day, secret)
    board: list[dict] | None
    try:
        board = _board_rows(day) if dailystore.configured() else None
    except dailystore.StoreError:
        board = None
    return 200, {
        "date": day.isoformat(),
        "token": daily.issue_session(day, secret, now),
        "puzzle": daily.public_daily(payload),
        "leaderboard": board,
    }


def _finish(body: dict, secret: str, now: float) -> tuple[int, dict]:
    session, err = daily.validate_session(daily.verify_token(body.get("token", ""), secret), now)
    if err:
        return 400, {"error": err}

    day = daily.date.fromisoformat(session["d"])
    payload, _seed = _daily_payload(day, secret)
    if not daily.check_rows(payload, body.get("rows")):
        return 200, {"correct": False}

    elapsed_ms = int((now - session["iat"]) * 1000)
    steps = body.get("steps")
    if not isinstance(steps, int) or not 0 < steps < 100_000:
        steps = 0  # missing/absurd step counts fail the floor below
    # Anti-cheat floors: a submission faster than the puzzle can be read, or
    # with fewer board interactions than the table has cells, isn't a solve.
    # Sized from the payload itself — the schedule varies shape by weekday,
    # and the payload's measured band is what the player actually solved.
    items = payload.get("items", 4)
    categories = payload.get("n_categories", 4)
    band = payload.get("difficulty", "hard")
    if (
        elapsed_ms < daily.min_solve_ms(band, items, categories)
        or steps < daily.min_steps(items, categories)
    ):
        return 422, {
            "error": "that solve looks implausible, so it can't be posted to the board"
        }

    return 200, {
        "correct": True,
        "time_ms": elapsed_ms,
        "result_token": daily.issue_result(session, elapsed_ms, steps, secret, now),
    }


def _claim(body: dict, secret: str, now: float, ip: str | None) -> tuple[int, dict]:
    result, err = daily.validate_result(
        daily.verify_token(body.get("result_token", ""), secret), now
    )
    if err:
        return 400, {"error": err}
    name, err = daily.clean_name(body.get("name"))
    if err:
        return 400, {"error": err}
    if not dailystore.configured():
        return 503, {"error": "leaderboard is unavailable right now"}

    day = daily.date.fromisoformat(result["d"])
    ip_hash = _ip_hash(ip, secret)
    try:
        if ip_hash and dailystore.count_for_ip(day, ip_hash) >= dailystore.MAX_PER_IP:
            return 429, {"error": "this network has posted enough scores for one day"}
        dailystore.insert_score(
            day, name, result["ms"], result.get("steps") or None, result["sid"], ip_hash
        )
        rows = dailystore.top_scores(day)
    except dailystore.DuplicateScore:
        return 409, {"error": "this solve is already on the board"}
    except dailystore.StoreError:
        return 503, {"error": "leaderboard is unavailable right now"}

    rank = next((i + 1 for i, r in enumerate(rows) if r.get("sid") == result["sid"]), None)
    return 200, {
        "rank": rank,  # null if outside the stored top-N
        "name": name,
        "time_ms": result["ms"],
        "date": day.isoformat(),
        "leaderboard": [
            {"name": r["name"], "time_ms": r["time_ms"], "steps": r.get("steps")} for r in rows
        ],
    }


def _build_post_response(body: dict, ip: str | None = None,
                         now: float | None = None) -> tuple[int, dict]:
    if not isinstance(body, dict):
        return 400, {"error": "request body must be a JSON object"}
    secret = _secret()
    if secret is None:
        return 503, {"error": "the daily challenge isn't configured yet (DAILY_SECRET)"}
    now = now if now is not None else time.time()

    action = body.get("action")
    if action == "finish":
        return _finish(body, secret, now)
    if action == "claim":
        return _claim(body, secret, now, ip)
    return 400, {"error": "action must be 'finish' or 'claim'"}


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _client_ip(self) -> str | None:
        forwarded = self.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0] if self.client_address else None

    def do_GET(self):  # noqa: N802 - Vercel/BaseHTTPRequestHandler contract
        query = parse_qs(urlparse(self.path).query)
        status, payload = _build_get_response(query)
        self._send(status, payload)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length > _MAX_BODY:
            self._send(413, {"error": "request body too large"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON body"})
            return
        status, payload = _build_post_response(body, ip=self._client_ip())
        self._send(status, payload)

    def do_OPTIONS(self):  # noqa: N802 - CORS preflight for the POST
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, *args):  # silence default stderr logging
        pass
