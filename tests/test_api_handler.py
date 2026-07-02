"""The serverless request/response logic (HTTP layer kept thin and testable).

We load api/puzzle.py by path — it isn't an importable package — and exercise
its pure ``_build_response`` helper directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent / "api"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"api_{name}", API_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def api():
    return _load("puzzle")


@pytest.fixture(scope="module")
def hint_api():
    return _load("hint")


def test_default_route(api):
    status, payload = api._build_response({})
    assert status == 200
    assert payload["requested"] == "normal"          # default tier
    assert payload["difficulty"] == "normal"          # a normal puzzle measures normal
    assert payload["items"] == 4
    assert payload["clues"]


def test_explicit_params(api):
    status, payload = api._build_response(
        {"difficulty": ["hard"], "items": ["5"], "seed": ["12"]}
    )
    assert status == 200
    assert payload["requested"] == "hard"             # honoured the request
    assert payload["difficulty"] in ("normal", "hard", "mega", "giga", "tera")
    assert payload["items"] == 5
    assert payload["seed"] == 12


def test_unknown_difficulty_is_400(api):
    status, payload = api._build_response({"difficulty": ["wizard"]})
    assert status == 400
    assert "difficulty" in payload["error"]


def test_bad_items_is_400(api):
    status, payload = api._build_response({"items": ["lots"]})
    assert status == 400
    assert "items must be an integer" in payload["error"]


def test_bad_seed_is_400(api):
    status, payload = api._build_response({"seed": ["not-a-number"]})
    assert status == 400
    assert "seed must be an integer" in payload["error"]


def test_hint_empty_board_is_a_given(hint_api):
    status, payload = hint_api._build_response(
        {"seed": 5, "difficulty": "hard", "items": 4, "categories": 3, "known": {}}
    )
    assert status == 200
    assert payload["tier"] == 0
    assert payload["text"]


def test_hint_requires_integer_seed(hint_api):
    status, payload = hint_api._build_response({"known": {}})
    assert status == 400
    assert "seed must be an integer" in payload["error"]


def test_hint_rejects_non_dict_known(hint_api):
    status, payload = hint_api._build_response({"seed": 3, "known": [1, 2, 3]})
    assert status == 400
    assert "known" in payload["error"]


def test_hint_unknown_difficulty_is_400(hint_api):
    status, payload = hint_api._build_response({"seed": 3, "difficulty": "wizard"})
    assert status == 400
    assert "difficulty" in payload["error"]


def test_themes_listing(api):
    status, payload = api._build_response({"themes": ["1"]})
    assert status == 200
    keys = [t["key"] for t in payload["themes"]]
    assert "cafe" in keys and "dnd" in keys
    assert all(t["name"] and t["description"] for t in payload["themes"])


def test_puzzle_theme_param(api):
    status, payload = api._build_response({"theme": ["dnd"], "seed": ["3"]})
    assert status == 200
    assert payload["theme"] == "dnd"
    assert payload["name"] == "The Adventuring Party"


def test_unknown_theme_is_400(api):
    status, payload = api._build_response({"theme": ["atlantis"]})
    assert status == 400
    assert "unknown theme" in payload["error"]


def test_hint_theme(hint_api):
    status, payload = hint_api._build_response(
        {"seed": 5, "difficulty": "hard", "items": 4, "categories": 3,
         "theme": "dnd", "known": {}}
    )
    assert status == 200
    assert payload["tier"] == 0
    assert payload["text"]


def test_hint_unknown_theme_is_400(hint_api):
    status, payload = hint_api._build_response(
        {"seed": 3, "theme": "atlantis", "known": {}}
    )
    assert status == 400
    assert "unknown theme" in payload["error"]
