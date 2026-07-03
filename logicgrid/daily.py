"""The daily challenge: one shared puzzle per UTC day, plus everything the
leaderboard API needs that doesn't touch the network (storage lives in
``logicgrid.dailystore``, HTTP in ``api/daily.py``).

Design notes, because several choices here are security decisions:

- The day's seed is derived with an HMAC over a server secret, NOT a public
  hash of the date. If the mapping were public, anyone could regenerate the
  daily through ``/api/puzzle?seed=…`` — which ships the answer key — and
  read off the solution. With a secret derivation the daily payload (which
  omits ``solution`` and ``seed``) is the only source of the puzzle.
- Timing is server-authoritative: a signed session token is issued when the
  puzzle is fetched, and the elapsed time is measured server-side at
  submission. The client's clock is display-only.
- A solve is claimed in two phases: ``finish`` (verify the solution, freeze
  the time, hand back a signed result token) then ``claim`` (attach a name).
  Typing a name doesn't cost leaderboard time, and the single-use session id
  in the token is what the unique DB constraint hangs off.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets as _secrets
import time
from datetime import date, timedelta, timezone
from datetime import datetime as _dt

from .webapi import _MAX_SEED, build_payload, list_themes

# The daily follows a weekday schedule so times are comparable within a
# weekday while the week as a whole has real variety: two beginner days, a
# mid-week mega ramp, and a heavy weekend. Shapes are (band, categories,
# items-per-category). Friday is the "second wind": the first giga of the
# week on the smallest grid — full contradiction logic without the slog.
# Monday's beginner grid goes the other way, wide and shallow (3 categories,
# 5 entities), so even the easy days don't feel same-y. The theme rotates
# through the registry so consecutive days feel different.
WEEKDAY_SCHEDULE = {
    0: ("normal", 3, 5),  # Mon — speed race on a wide, shallow grid
    1: ("hard", 4, 4),    # Tue — the classic daily shape
    2: ("mega", 4, 4),    # Wed — first contradictions
    3: ("mega", 5, 4),    # Thu — same logic, bigger board
    4: ("giga", 5, 3),    # Fri — second wind: deep logic, tiny grid
    5: ("giga", 5, 4),    # Sat — the weekend main event
    6: ("tera", 4, 4),    # Sun — nested what-ifs
}


def daily_config(day: date) -> tuple[str, int, int]:
    """(difficulty, categories, items) for a calendar day."""
    return WEEKDAY_SCHEDULE[day.weekday()]


# Generation is generate-and-grade, so a given seed may measure off-band. We
# walk a deterministic chain of candidate seeds and take the first that
# grades exactly on-band, falling back to the closest band if the chain is
# exhausted (mirrors the web app's own re-roll behavior).
SEED_TRIES = 8
# Heavy shapes take seconds-to-minutes per build, and the first uncached
# request of a day pays for the whole walk — cap it so a serverless
# invocation can't time out. In production the walk almost never runs in a
# request at all: the warm-daily workflow (scripts/warm_daily.py, cron just
# after UTC midnight) does the full unbudgeted walk and caches the result,
# so this budget is the degraded path when the warmer hasn't run. When the
# walk is cut short the best candidate so far is used; the winner's seed is
# cached on first build, so every later request converges regardless.
WALK_BUDGET_S = 20.0
_BANDS = ["normal", "hard", "mega", "giga", "tera"]

# --- Anti-cheat floors (deliberately simple; see docs in the PR) -----------
# Nobody legitimately solves a grid faster than its clues can be read.
# Catches answer paste-ins posting absurd times. Scaled by band (harder
# logic = more reading and testing) and by table size relative to the
# classic 4x4's 12 solution cells. Every scheduled shape stays well under
# two minutes so honest speedruns are never at risk.
_BAND_FLOOR_MS = {
    "normal": 30_000,
    "hard": 45_000,
    "mega": 60_000,
    "giga": 75_000,
    "tera": 90_000,
}


def min_solve_ms(band: str, items: int, categories: int) -> int:
    cells = items * (categories - 1)
    return int(_BAND_FLOOR_MS.get(band, 45_000) * cells / 12)


# A session older than this can't submit (also bounds token replay windows).
MAX_SOLVE_MS = 12 * 60 * 60 * 1000
# Fewer board interactions than the solution table has cells means the grid
# was never actually worked: every entity needs (k-1) placed links.
def min_steps(items: int, categories: int) -> int:
    return items * (categories - 1)

# A result token must be claimed reasonably promptly after the solve.
CLAIM_WINDOW_MS = 60 * 60 * 1000
# Small allowance for clock skew between serverless invocations.
CLOCK_SKEW_S = 120


def today_utc() -> date:
    return _dt.now(timezone.utc).date()


def daily_theme(day: date) -> str:
    """Rotate through the registry themes, one per day, deterministically."""
    keys = [t["key"] for t in list_themes()]
    return keys[day.toordinal() % len(keys)]


def candidate_seed(day: date, secret: str, k: int) -> int:
    """The k-th candidate seed for a day. HMAC keeps the date->seed mapping
    private so the daily can't be replayed through the open /api/puzzle."""
    msg = f"daily:{day.isoformat()}:{k}".encode()
    digest = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") % _MAX_SEED


def build_daily(day: date, secret: str, seed: int | None = None,
                budget_s: float | None = WALK_BUDGET_S) -> tuple[dict, int]:
    """Build the day's full payload (solution included — callers strip it).

    With ``seed`` (the cached choice from the store) the puzzle is rebuilt
    directly. Without it, walk the candidate chain for a band match; the walk
    is deterministic in (day, secret), so even with no store every request
    converges on the same puzzle. (The only exception: if WALK_BUDGET_S cuts
    a walk short, machines of different speeds could pick different
    fallbacks — in production the store caches the first winner's seed, so
    this never surfaces to players.)
    """
    difficulty, categories, items = daily_config(day)
    theme = daily_theme(day)
    kwargs = dict(
        difficulty=difficulty,
        items=items,
        categories=categories,
        theme=theme,
    )
    if seed is not None:
        return build_payload(seed=seed, **kwargs), seed

    want = _BANDS.index(difficulty)
    best: tuple[dict, int] | None = None
    t0 = time.monotonic()
    for k in range(SEED_TRIES):
        if best is not None and budget_s is not None and time.monotonic() - t0 > budget_s:
            break
        cand_seed = candidate_seed(day, secret, k)
        payload = build_payload(seed=cand_seed, **kwargs)
        if payload["difficulty"] == difficulty:
            return payload, cand_seed
        if best is None or (
            abs(_BANDS.index(payload["difficulty"]) - want)
            < abs(_BANDS.index(best[0]["difficulty"]) - want)
        ):
            best = (payload, cand_seed)
    return best  # type: ignore[return-value]  # SEED_TRIES >= 1 guarantees a value


def public_daily(payload: dict) -> dict:
    """The client-safe view: no answer key, and no seed (a seed would let the
    open /api/puzzle endpoint reproduce the puzzle WITH its answer key)."""
    return {k: v for k, v in payload.items() if k not in ("solution", "seed")}


def check_rows(payload: dict, rows) -> bool:
    """Does the submitted solution table match the puzzle's? Rows arrive as
    lists of item labels, one row per entity; order-insensitive."""
    if not isinstance(rows, list):
        return False
    try:
        got = sorted(tuple(str(x) for x in row) for row in rows)
    except TypeError:
        return False
    want = sorted(tuple(row) for row in payload["solution"])
    return got == want


# --- Signed tokens ----------------------------------------------------------
# Compact HMAC-signed JSON (b64url(body).b64url(sig)). Session tokens carry
# the issue time (t0 of the official clock); result tokens carry the verified
# elapsed time so "claim" can't re-litigate it.

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_token(data: dict, secret: str) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    return f"{_b64e(raw)}.{_b64e(sig)}"


def verify_token(token: str, secret: str) -> dict | None:
    """The token's payload if the signature checks out, else None."""
    if not isinstance(token, str) or token.count(".") != 1:
        return None
    body_b64, sig_b64 = token.split(".")
    try:
        raw, sig = _b64d(body_b64), _b64d(sig_b64)
    except (ValueError, TypeError):
        return None
    want = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, want):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def issue_session(day: date, secret: str, now: float | None = None) -> str:
    return sign_token(
        {
            "v": 1,
            "t": "session",
            "d": day.isoformat(),
            "sid": _secrets.token_hex(8),
            "iat": int(now if now is not None else time.time()),
        },
        secret,
    )


def issue_result(session: dict, elapsed_ms: int, steps: int, secret: str,
                 now: float | None = None) -> str:
    return sign_token(
        {
            "v": 1,
            "t": "result",
            "d": session["d"],
            "sid": session["sid"],
            "ms": elapsed_ms,
            "steps": steps,
            "iat": int(now if now is not None else time.time()),
        },
        secret,
    )


def _parse_day(text) -> date | None:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def validate_session(data: dict | None, now: float) -> tuple[dict | None, str | None]:
    """Shared shape/freshness checks for a verified session token.
    Returns (session, error). A session is valid for today's board or —
    for solvers who started just before midnight UTC — yesterday's."""
    if not data or data.get("t") != "session" or not isinstance(data.get("sid"), str):
        return None, "invalid session token"
    day = _parse_day(data.get("d"))
    iat = data.get("iat")
    if day is None or not isinstance(iat, int):
        return None, "invalid session token"
    if iat > now + CLOCK_SKEW_S:
        return None, "invalid session token"
    if (now - iat) * 1000 > MAX_SOLVE_MS:
        return None, "this session has expired — reload for a fresh start"
    if day not in (today_utc(), today_utc() - timedelta(days=1)):
        return None, "this session is for a previous day's puzzle — reload"
    return data, None


def validate_result(data: dict | None, now: float) -> tuple[dict | None, str | None]:
    if (
        not data
        or data.get("t") != "result"
        or not isinstance(data.get("sid"), str)
        or not isinstance(data.get("ms"), int)
        or not isinstance(data.get("iat"), int)
        or _parse_day(data.get("d")) is None
    ):
        return None, "invalid result token"
    if data["iat"] > now + CLOCK_SKEW_S or (now - data["iat"]) * 1000 > CLAIM_WINDOW_MS:
        return None, "that solve has expired — play again tomorrow"
    return data, None


# --- Display names -----------------------------------------------------------
# No accounts, so the name is free text — filtered server-side. Two lists:
# fragments that are objectionable wherever they appear (leet-normalized,
# spacing/punctuation stripped, repeats collapsed), and words only blocked as
# a whole token (so e.g. "Dickens" or "Cassie" stay fine).

NAME_MIN, NAME_MAX = 2, 20
_NAME_ALLOWED = re.compile(r"^[A-Za-z0-9 ._'\-]+$")

_LEET = str.maketrans({
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a", "5": "s",
    "6": "g", "7": "t", "8": "b", "9": "g", "@": "a", "$": "s",
    "!": "i", "+": "t", "|": "i",
})

_BLOCKED_FRAGMENTS = (
    "fuck", "shit", "cunt", "nigg", "fagg", "bitch", "whore", "slut",
    "penis", "vagin", "hitler", "nazi", "retard", "kike", "chink",
    "wank", "jizz", "dyke", "pedo", "raping", "rapist", "molest",
)
_BLOCKED_WORDS = frozenset({
    "ass", "arse", "anal", "anus", "cum", "sex", "tit", "tits", "fag",
    "hoe", "dick", "cock", "porn", "rape", "nsfw", "kys", "twat",
    "puss", "pussy", "boob", "boobs", "semen", "smegma",
})


def _normalized(text: str) -> str:
    """Lowercase, undo leet substitutions, drop everything but letters."""
    lowered = text.lower().translate(_LEET)
    return re.sub(r"[^a-z]", "", lowered)


def _collapse(text: str) -> str:
    return re.sub(r"(.)\1+", r"\1", text)


def name_allowed(name: str) -> bool:
    squeezed = _normalized(name)
    for candidate in (squeezed, _collapse(squeezed)):
        if any(frag in candidate for frag in _BLOCKED_FRAGMENTS):
            return False
    tokens = {
        _collapse(_normalized(tok))
        for tok in re.split(r"[\s._'\-]+", name.lower())
    } | {_normalized(tok) for tok in re.split(r"[\s._'\-]+", name.lower())}
    return not (tokens & _BLOCKED_WORDS)


def clean_name(raw) -> tuple[str | None, str | None]:
    """Validate and canonicalize a display name. Returns (name, error)."""
    if not isinstance(raw, str):
        return None, "name must be text"
    name = re.sub(r"\s+", " ", raw).strip()
    if len(name) < NAME_MIN:
        return None, f"name needs at least {NAME_MIN} characters"
    if len(name) > NAME_MAX:
        return None, f"name can't be longer than {NAME_MAX} characters"
    if not _NAME_ALLOWED.match(name):
        return None, "name can only use letters, numbers, spaces, and . _ ' -"
    if not name_allowed(name):
        return None, "that name isn't allowed on the board — try another"
    return name, None
