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
DAY = date(2026, 7, 2)


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


def test_unknown_action_is_400(api, monkeypatch):
    monkeypatch.setenv("DAILY_SECRET", SECRET)
    status, payload = api._build_post_response({"action": "cheat"})
    assert status == 400
