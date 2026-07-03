"""The daily challenge: deterministic generation, signed tokens, the name
filter, and the api/daily.py request logic (store-less paths; Supabase is
exercised against the real project, not from unit tests)."""

from __future__ import annotations

import importlib.util
import time
from datetime import date
from pathlib import Path

import pytest

from logicgrid import daily

API_DIR = Path(__file__).resolve().parent.parent / "api"
SECRET = "test-secret"
# A Monday: the schedule's cheapest shape (normal 3x5 builds in ~0.05s), so
# the payload-building fixtures stay fast.
DAY = date(2026, 7, 6)


@pytest.fixture(scope="module", autouse=True)
def _pin_today():
    """Pin 'today' to DAY so the suite behaves identically every weekday
    (the schedule varies shape by weekday) and never builds a heavy grid."""
    real = daily.today_utc
    daily.today_utc = lambda: DAY
    yield
    daily.today_utc = real


def _load_daily_api():
    spec = importlib.util.spec_from_file_location("api_daily", API_DIR / "daily.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def api():
    return _load_daily_api()


@pytest.fixture(scope="module")
def day_payload():
    payload, seed = daily.build_daily(DAY, SECRET)
    return payload, seed


# --- The weekday schedule -------------------------------------------------------

def test_schedule_covers_the_week_with_the_agreed_band_mix():
    bands = [daily.WEEKDAY_SCHEDULE[d][0] for d in range(7)]
    assert sorted(bands) == sorted(
        ["normal", "hard", "mega", "mega", "giga", "giga", "tera"]
    )


def test_monday_beginner_grid_is_wide_and_shallow():
    assert daily.WEEKDAY_SCHEDULE[0] == ("normal", 3, 5)


def test_friday_second_wind_is_the_smallest_giga():
    band, categories, items = daily.WEEKDAY_SCHEDULE[4]
    assert (band, categories, items) == ("giga", 5, 3)
    # smallest table of any giga (or harder) day in the week
    heavy = [
        items * (categories - 1)
        for band, categories, items in daily.WEEKDAY_SCHEDULE.values()
        if band in ("giga", "tera")
    ]
    friday_cells = items * (categories - 1)
    assert friday_cells == min(heavy)


def test_schedule_shapes_are_buildable():
    from logicgrid.webapi import (
        MAX_CATEGORIES, MIN_CATEGORIES, MIN_ITEMS, max_items_for,
    )
    for band, categories, items in daily.WEEKDAY_SCHEDULE.values():
        assert MIN_CATEGORIES <= categories <= MAX_CATEGORIES
        assert MIN_ITEMS <= items <= max_items_for(categories)


def test_solve_floors_scale_but_stay_under_two_minutes():
    # the classic shape keeps its original floor (today's cached rows stay valid)
    assert daily.min_solve_ms("hard", 4, 4) == 45_000
    for band, categories, items in daily.WEEKDAY_SCHEDULE.values():
        floor = daily.min_solve_ms(band, items, categories)
        assert 0 < floor < 120_000
    # a harder band on the same grid never has a lower floor
    assert (
        daily.min_solve_ms("normal", 4, 4)
        < daily.min_solve_ms("mega", 4, 4)
        < daily.min_solve_ms("tera", 4, 4)
    )


def test_daily_config_follows_the_weekday():
    assert daily.daily_config(date(2026, 7, 6)) == daily.WEEKDAY_SCHEDULE[0]  # Mon
    assert daily.daily_config(date(2026, 7, 10)) == daily.WEEKDAY_SCHEDULE[4]  # Fri


def test_build_daily_uses_the_scheduled_shape(day_payload):
    payload, _seed = day_payload  # DAY is a Monday: normal, 3 categories x 5 items
    assert payload["requested"] == "normal"
    assert payload["n_categories"] == 3
    assert payload["items"] == 5


# --- Deterministic generation -------------------------------------------------

def test_candidate_seeds_deterministic_and_secret_bound():
    assert daily.candidate_seed(DAY, SECRET, 0) == daily.candidate_seed(DAY, SECRET, 0)
    assert daily.candidate_seed(DAY, SECRET, 0) != daily.candidate_seed(DAY, SECRET, 1)
    # a different secret yields a different chain: the date->seed mapping is private
    assert daily.candidate_seed(DAY, SECRET, 0) != daily.candidate_seed(DAY, "other", 0)


def test_build_daily_converges_and_rebuilds_from_seed(day_payload):
    payload, seed = day_payload
    assert payload["difficulty"] in ("normal", "hard", "mega", "giga", "tera")
    assert payload["theme"] == daily.daily_theme(DAY)
    # the cached-seed path rebuilds the identical puzzle
    again, _ = daily.build_daily(DAY, SECRET, seed=seed)
    assert again["clues"] == payload["clues"]
    assert again["solution"] == payload["solution"]


def test_public_daily_withholds_solution_and_seed(day_payload):
    payload, _seed = day_payload
    public = daily.public_daily(payload)
    assert "solution" not in public
    assert "seed" not in public
    assert public["clues"] == payload["clues"]


def test_check_rows(day_payload):
    payload, _seed = day_payload
    truth = payload["solution"]
    assert daily.check_rows(payload, [list(r) for r in truth])
    assert daily.check_rows(payload, list(reversed(truth)))  # row order is free
    wrong = [list(r) for r in truth]
    wrong[0], wrong[1] = wrong[0][:1] + wrong[1][1:], wrong[1][:1] + wrong[0][1:]
    assert not daily.check_rows(payload, wrong)
    assert not daily.check_rows(payload, "nonsense")
    assert not daily.check_rows(payload, [])


# --- Tokens -------------------------------------------------------------------

def test_token_roundtrip_and_tamper():
    token = daily.issue_session(DAY, SECRET, now=1000)
    data = daily.verify_token(token, SECRET)
    assert data and data["t"] == "session" and data["iat"] == 1000
    assert daily.verify_token(token, "other-secret") is None
    body, sig = token.split(".")
    assert daily.verify_token(f"{body}x.{sig}", SECRET) is None
    assert daily.verify_token("garbage", SECRET) is None


def test_session_validation_windows():
    now = time.time()
    fresh = daily.verify_token(daily.issue_session(daily.today_utc(), SECRET, now - 60), SECRET)
    session, err = daily.validate_session(fresh, now)
    assert err is None and session["sid"]

    stale_iat = now - (daily.MAX_SOLVE_MS / 1000 + 10)
    stale = daily.verify_token(daily.issue_session(daily.today_utc(), SECRET, stale_iat), SECRET)
    _, err = daily.validate_session(stale, now)
    assert err and "expired" in err

    old_day = daily.verify_token(daily.issue_session(date(2020, 1, 1), SECRET, now - 60), SECRET)
    _, err = daily.validate_session(old_day, now)
    assert err

    result = daily.verify_token(
        daily.issue_result({"d": "2026-07-02", "sid": "ab"}, 60000, 20, SECRET, now), SECRET
    )
    _, err = daily.validate_session(result, now)  # a result token is not a session
    assert err


# --- Display names -------------------------------------------------------------

@pytest.mark.parametrize("name", ["Keaton", "puzzle fan 42", "Ana-Maria", "J.R.", "O'Brien"])
def test_names_accepted(name):
    cleaned, err = daily.clean_name(name)
    assert err is None and cleaned == name


def test_name_canonicalizes_whitespace():
    cleaned, err = daily.clean_name("  puzzle   fan ")
    assert err is None and cleaned == "puzzle fan"


@pytest.mark.parametrize(
    "name",
    [
        "x",                # too short
        "a" * 21,           # too long
        "so<script>",       # disallowed characters
        "fuck",             # plain profanity
        "FuCkEr",           # case
        "f u c k",          # spacing
        "sh1thead",         # leet
        "fuuuuck",          # repeats
        "ass",              # whole-token block
        "a$$hat",           # leet whole-token
    ],
)
def test_names_rejected(name):
    cleaned, err = daily.clean_name(name)
    assert cleaned is None and err


def test_name_substrings_of_blocked_tokens_are_fine():
    for name in ("Cassie", "Dickens", "Sextant" [:6], "cocoa"):
        cleaned, err = daily.clean_name(name)
        assert err is None, f"{name!r} wrongly rejected: {err}"


# --- api/daily request logic (no store configured) ------------------------------

def test_get_requires_secret(api, monkeypatch):
    monkeypatch.delenv("DAILY_SECRET", raising=False)
    status, payload = api._build_get_response({})
    assert status == 503 and "DAILY_SECRET" in payload["error"]


def test_get_serves_puzzle_without_solution(api, monkeypatch):
    monkeypatch.setenv("DAILY_SECRET", SECRET)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    status, payload = api._build_get_response({})
    assert status == 200
    assert "solution" not in payload["puzzle"] and "seed" not in payload["puzzle"]
    assert payload["puzzle"]["clues"]
    session = daily.verify_token(payload["token"], SECRET)
    assert session and session["d"] == payload["date"]
    assert payload["leaderboard"] is None  # store not configured -> board unavailable


def _finish_body(api, monkeypatch, *, rows, iat_ago, steps):
    monkeypatch.setenv("DAILY_SECRET", SECRET)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    now = time.time()
    token = daily.issue_session(daily.today_utc(), SECRET, now - iat_ago)
    return api._build_post_response(
        {"action": "finish", "token": token, "rows": rows, "steps": steps}, now=now
    )


@pytest.fixture(scope="module")
def today_truth(api):
    payload, _ = daily.build_daily(daily.today_utc(), SECRET)
    return [list(r) for r in payload["solution"]]


def test_finish_correct_solve_issues_result(api, monkeypatch, today_truth):
    status, payload = _finish_body(api, monkeypatch, rows=today_truth, iat_ago=120, steps=40)
    assert status == 200 and payload["correct"] is True
    assert payload["time_ms"] >= 120_000 - 1000
    result = daily.verify_token(payload["result_token"], SECRET)
    assert result["t"] == "result" and result["ms"] == payload["time_ms"]


def test_finish_wrong_rows_say_incorrect(api, monkeypatch, today_truth):
    wrong = [list(r) for r in today_truth]
    wrong[0][1], wrong[1][1] = wrong[1][1], wrong[0][1]
    status, payload = _finish_body(api, monkeypatch, rows=wrong, iat_ago=120, steps=40)
    assert status == 200 and payload["correct"] is False
    assert "result_token" not in payload


def test_finish_too_fast_is_rejected(api, monkeypatch, today_truth):
    status, payload = _finish_body(api, monkeypatch, rows=today_truth, iat_ago=5, steps=40)
    assert status == 422 and "implausible" in payload["error"]


def test_finish_too_few_steps_is_rejected(api, monkeypatch, today_truth):
    status, payload = _finish_body(api, monkeypatch, rows=today_truth, iat_ago=120, steps=3)
    assert status == 422
    # and omitting the count entirely doesn't dodge the floor
    status, _ = _finish_body(api, monkeypatch, rows=today_truth, iat_ago=120, steps=None)
    assert status == 422


def test_finish_floors_follow_the_payload_shape(api, monkeypatch, today_truth):
    # DAY is a Monday: a normal 3x5, so the floors are 25s and 10 steps.
    # Under the old fixed 4x4 floors (45s, 12 steps) both submissions below
    # would have been wrongly rejected.
    status, payload = _finish_body(api, monkeypatch, rows=today_truth, iat_ago=30, steps=10)
    assert status == 200 and payload["correct"] is True
    # and the scaled-down floors still bite just underneath
    status, _ = _finish_body(api, monkeypatch, rows=today_truth, iat_ago=20, steps=10)
    assert status == 422
    status, _ = _finish_body(api, monkeypatch, rows=today_truth, iat_ago=30, steps=9)
    assert status == 422


def test_claim_rejects_bad_names_before_touching_the_store(api, monkeypatch):
    monkeypatch.setenv("DAILY_SECRET", SECRET)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    now = time.time()
    result_token = daily.issue_result(
        {"d": daily.today_utc().isoformat(), "sid": "abc123"}, 90_000, 40, SECRET, now
    )
    status, payload = api._build_post_response(
        {"action": "claim", "result_token": result_token, "name": "sh1thead"}, now=now
    )
    assert status == 400 and "allowed" in payload["error"]

    status, payload = api._build_post_response(
        {"action": "claim", "result_token": result_token, "name": "Keaton"}, now=now
    )
    assert status == 503  # good name, but no store configured


def _claim_env(api, monkeypatch):
    """A configured store whose network calls are stubbed at the module level."""
    monkeypatch.setenv("DAILY_SECRET", SECRET)
    monkeypatch.setenv("SUPABASE_URL", "https://stub.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "stub-key")
    now = time.time()
    result_token = daily.issue_result(
        {"d": daily.today_utc().isoformat(), "sid": "abc123"}, 90_000, 40, SECRET, now
    )
    return now, {"action": "claim", "result_token": result_token, "name": "Keaton"}


def test_claim_replayed_result_token_is_a_conflict(api, monkeypatch):
    now, body = _claim_env(api, monkeypatch)
    monkeypatch.setattr(api.dailystore, "count_for_ip", lambda day, ip: 0)

    def dup(*args, **kwargs):
        raise api.dailystore.DuplicateScore(
            'duplicate key value violates unique constraint "daily_scores_sid_key"'
        )

    monkeypatch.setattr(api.dailystore, "insert_score", dup)
    status, payload = api._build_post_response(body, now=now)
    assert status == 409 and "already on the board" in payload["error"]


def test_claim_inserts_as_guest_no_account_needed(api, monkeypatch):
    now, body = _claim_env(api, monkeypatch)
    monkeypatch.setattr(api.dailystore, "count_for_ip", lambda day, ip: 0)
    seen = {}

    def record(day, name, time_ms, steps, sid, ip_hash):
        seen.update(name=name, time_ms=time_ms, sid=sid)

    monkeypatch.setattr(api.dailystore, "insert_score", record)
    monkeypatch.setattr(
        api.dailystore, "top_scores",
        lambda day: [{"name": "Keaton", "time_ms": 90_000, "steps": 40, "sid": "abc123"}],
    )
    status, payload = api._build_post_response(body, now=now, ip="203.0.113.9")
    assert status == 200 and payload["rank"] == 1
    assert seen == {"name": "Keaton", "time_ms": 90_000, "sid": "abc123"}


def test_claim_respects_the_per_network_cap(api, monkeypatch):
    now, body = _claim_env(api, monkeypatch)
    monkeypatch.setattr(
        api.dailystore, "count_for_ip", lambda day, ip: api.dailystore.MAX_PER_IP
    )
    status, payload = api._build_post_response(body, now=now, ip="203.0.113.9")
    assert status == 429


def test_unknown_action_is_400(api, monkeypatch):
    monkeypatch.setenv("DAILY_SECRET", SECRET)
    status, payload = api._build_post_response({"action": "cheat"})
    assert status == 400


# --- Payload cache: submissions must verify without regenerating ---------------

def _stub_store(monkeypatch):
    monkeypatch.setenv("DAILY_SECRET", SECRET)
    monkeypatch.setenv("SUPABASE_URL", "https://stub.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "stub-key")


def test_cached_payload_is_served_without_regenerating(api, monkeypatch, day_payload):
    payload, seed = day_payload
    _stub_store(monkeypatch)
    monkeypatch.setattr(api.dailystore, "get_daily_row",
                        lambda day: {"seed": seed, "payload": payload})
    monkeypatch.setattr(api.dailystore, "top_scores", lambda day: [])

    def boom(*args, **kwargs):
        raise AssertionError("regenerated the puzzle despite a cached payload")

    monkeypatch.setattr(api.daily, "build_daily", boom)
    status, got = api._build_get_response({})
    assert status == 200
    assert got["puzzle"]["clues"] == payload["clues"]
    assert "solution" not in got["puzzle"] and "seed" not in got["puzzle"]

    # a finish verdict also comes straight from the cache
    now = time.time()
    token = daily.issue_session(daily.today_utc(), SECRET, now - 120)
    status, fin = api._build_post_response(
        {"action": "finish", "token": token,
         "rows": [list(r) for r in payload["solution"]], "steps": 40},
        now=now,
    )
    assert status == 200 and fin["correct"] is True


def test_pre_cache_row_gets_its_payload_backfilled(api, monkeypatch, day_payload):
    payload, seed = day_payload
    _stub_store(monkeypatch)
    monkeypatch.setattr(api.dailystore, "get_daily_row",
                        lambda day: {"seed": seed, "payload": None})
    monkeypatch.setattr(api.daily, "build_daily",
                        lambda day, secret, seed=None: (payload, seed))
    filled = {}
    monkeypatch.setattr(api.dailystore, "update_daily_payload",
                        lambda day, p: filled.update(payload=p))
    monkeypatch.setattr(api.dailystore, "top_scores", lambda day: [])
    status, got = api._build_get_response({})
    assert status == 200
    assert filled["payload"] is payload
