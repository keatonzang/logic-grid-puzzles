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
    """A unique constraint fired: this solve (session id) was already posted,
    or this account already has a score today. ``str(exc)`` holds the
    PostgREST detail so callers can tell which."""


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


def get_daily_seed(day: date) -> int | None:
    rows = _request("GET", "daily_puzzles",
                    params={"day": f"eq.{day.isoformat()}", "select": "seed"})
    return rows[0]["seed"] if rows else None


def save_daily_seed(day: date, seed: int, theme: str, difficulty: str) -> None:
    """First writer wins; concurrent cold starts converge on one canonical row."""
    _request(
        "POST", "daily_puzzles",
        params={"on_conflict": "day"},
        body={"day": day.isoformat(), "seed": seed, "theme": theme, "difficulty": difficulty},
        prefer="resolution=ignore-duplicates",
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
                 sid: str, user_id: str, ip_hash: str | None) -> None:
    """One row per solve. Two unique constraints guard it: ``sid`` makes a
    result token single-use, and (day, user_id) allows one score per account
    per day. Either violation is a 409, surfaced as DuplicateScore."""
    _request(
        "POST", "daily_scores",
        body={
            "day": day.isoformat(),
            "name": name,
            "time_ms": time_ms,
            "steps": steps,
            "sid": sid,
            "user_id": user_id,
            "ip_hash": ip_hash,
        },
    )


def auth_user(access_token: str) -> dict | None:
    """Resolve a client-supplied Supabase Auth access token to its user via
    GoTrue, or None if the token is missing/invalid/expired. Server-side
    verification: the client's word about who it is never reaches the DB."""
    if not access_token or not configured():
        return None
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    req = urllib.request.Request(
        f"{base}/auth/v1/user",
        headers={"apikey": key, "Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            user = json.loads(res.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return None
        raise StoreError(f"auth error {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StoreError(f"auth unreachable: {exc}") from exc
    return user if isinstance(user, dict) and user.get("id") else None


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
