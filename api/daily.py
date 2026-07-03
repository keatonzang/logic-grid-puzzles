"""Vercel Python serverless function: the daily challenge + leaderboard.

    GET  /api/daily            -> today's puzzle (no answer key), a signed
                                  session token, and the current leaderboard
    GET  /api/daily?board=1    -> leaderboard only (cheap refresh)
    POST /api/daily {"action": "finish", "token": ..., "rows": [[label,..],..],
                     "steps": N}
        -> verifies the solution server-side against the regenerated puzzle;
           on success returns the official (server-measured) time and a
           signed single-use result token
    POST /api/daily {"action": "claim", "result_token": ..., "name": "..."}
        (Authorization: Bearer <supabase auth access token>)
        -> requires a signed-in account; filters the name, inserts the score
           (one per account per day), returns rank + fresh board

The pure logic lives in ``logicgrid.daily`` (deterministic generation,
tokens, name filter) and ``logicgrid.dailystore`` (Supabase REST), so this
layer stays thin and unit-testable like api/puzzle.py.
"""

from __future__ import annotations

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


def _build_get_response(query: dict, now: float | None = None) -> tuple[int, dict]:
    secret = _secret()
    if secret is None:
        return 503, {"error": "the daily challenge isn't configured yet (DAILY_SECRET)"}
    day = daily.today_utc()

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
    # The anon key is public by design (RLS blocks it from every table); the
    # client only needs it to talk to Supabase Auth for sign-in/sign-up.
    auth_cfg = None
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_ANON_KEY"):
        auth_cfg = {
            "url": os.environ["SUPABASE_URL"].rstrip("/"),
            "anon_key": os.environ["SUPABASE_ANON_KEY"],
        }
    return 200, {
        "date": day.isoformat(),
        "token": daily.issue_session(day, secret, now),
        "puzzle": daily.public_daily(payload),
        "leaderboard": board,
        "auth": auth_cfg,
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
    if elapsed_ms < daily.MIN_SOLVE_MS or steps < daily.min_steps():
        return 422, {
            "error": "that solve looks implausible, so it can't be posted to the board"
        }

    return 200, {
        "correct": True,
        "time_ms": elapsed_ms,
        "result_token": daily.issue_result(session, elapsed_ms, steps, secret, now),
    }


def _claim(body: dict, secret: str, now: float, ip: str | None,
           user_token: str | None) -> tuple[int, dict]:
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
    try:
        user = dailystore.auth_user(user_token or "")
    except dailystore.StoreError:
        return 503, {"error": "leaderboard is unavailable right now"}
    if user is None:
        return 401, {"error": "sign in to post your time to the board"}

    day = daily.date.fromisoformat(result["d"])
    ip_hash = _ip_hash(ip, secret)
    try:
        if ip_hash and dailystore.count_for_ip(day, ip_hash) >= dailystore.MAX_PER_IP:
            return 429, {"error": "this network has posted enough scores for one day"}
        dailystore.insert_score(
            day, name, result["ms"], result.get("steps") or None, result["sid"],
            user["id"], ip_hash
        )
        rows = dailystore.top_scores(day)
    except dailystore.DuplicateScore as dup:
        if "daily_scores_day_user" in str(dup):
            return 409, {"error": "this account already posted a time today"}
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
                         now: float | None = None,
                         user_token: str | None = None) -> tuple[int, dict]:
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
        return _claim(body, secret, now, ip, user_token)
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
        auth_header = self.headers.get("Authorization") or ""
        user_token = auth_header[7:] if auth_header.startswith("Bearer ") else None
        status, payload = _build_post_response(body, ip=self._client_ip(), user_token=user_token)
        self._send(status, payload)

    def do_OPTIONS(self):  # noqa: N802 - CORS preflight for the POST
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, *args):  # silence default stderr logging
        pass
