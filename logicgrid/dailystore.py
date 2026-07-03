"""Supabase persistence for the daily leaderboard, via PostgREST over
urllib — no client library, matching the repo's dependency-free functions.

All access goes through the service-role key (env), and both tables have RLS
enabled with **no policies**: the browser can never talk to the database
directly, so every write funnels through our API where names are filtered
and times are validated. The anon key is never shipped.

Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BOARD_LIMIT = 100  # entries shown per day
MAX_PER_IP = 5     # soft cap: blocks one machine spamming entries, tolerates shared networks


class StoreError(Exception):
    """The store is unreachable or returned an unexpected error."""


class DuplicateScore(StoreError):
    """A unique constraint fired: this solve (session id) was already posted.
    ``str(exc)`` holds the PostgREST detail."""


def configured() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))


def _request(method: str, table: str, *, params: dict | None = None,
             body=None, prefer: str | None = None):
    base = os.environ["SUPABASE_URL"].rstrip("/")
    url = f"{base}/rest/v1/{table}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 409:
            raise DuplicateScore(detail) from exc
        raise StoreError(f"store error {exc.code}: {detail[:200]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StoreError(f"store unreachable: {exc}") from exc
    return json.loads(raw) if raw else None


def get_daily_row(day: date) -> dict | None:
    """The day's canonical row: {"seed": int, "payload": dict | None}.
    ``payload`` is the full generated puzzle (solution included), cached so
    requests can serve and verify without a multi-second regeneration."""
    rows = _request("GET", "daily_puzzles",
                    params={"day": f"eq.{day.isoformat()}", "select": "seed,payload"})
    return rows[0] if rows else None


def save_daily_row(day: date, seed: int, theme: str, difficulty: str,
                   payload: dict) -> None:
    """First writer wins; concurrent cold starts converge on one canonical row
    (generation is deterministic, so the losers' payloads were identical)."""
    _request(
        "POST", "daily_puzzles",
        params={"on_conflict": "day"},
        body={
            "day": day.isoformat(), "seed": seed, "theme": theme,
            "difficulty": difficulty, "payload": payload,
        },
        prefer="resolution=ignore-duplicates",
    )


def update_daily_payload(day: date, payload: dict) -> None:
    """Backfill the cached payload on a row that predates the cache column."""
    _request(
        "PATCH", "daily_puzzles",
        params={"day": f"eq.{day.isoformat()}"},
        body={"payload": payload},
    )


def top_scores(day: date, limit: int = BOARD_LIMIT) -> list[dict]:
    """The day's board, best time first (ties: earlier submission wins).
    Includes ``sid`` so the API can locate a fresh entry's rank; the API
    strips it before responding."""
    return _request(
        "GET", "daily_scores",
        params={
            "day": f"eq.{day.isoformat()}",
            "select": "name,time_ms,steps,sid",
            "order": "time_ms.asc,created_at.asc",
            "limit": str(limit),
        },
    ) or []


def insert_score(day: date, name: str, time_ms: int, steps: int | None,
                 sid: str, ip_hash: str | None) -> None:
    """One row per solve. The unique ``sid`` makes a result token single-use:
    replaying one is a 409, surfaced as DuplicateScore."""
    _request(
        "POST", "daily_scores",
        body={
            "day": day.isoformat(),
            "name": name,
            "time_ms": time_ms,
            "steps": steps,
            "sid": sid,
            "ip_hash": ip_hash,
        },
    )


def count_for_ip(day: date, ip_hash: str) -> int:
    rows = _request(
        "GET", "daily_scores",
        params={
            "day": f"eq.{day.isoformat()}",
            "ip_hash": f"eq.{ip_hash}",
            "select": "id",
            "limit": str(MAX_PER_IP + 1),
        },
    )
    return len(rows or [])
