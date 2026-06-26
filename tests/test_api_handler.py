"""The serverless request/response logic (HTTP layer kept thin and testable).

We load api/puzzle.py by path — it isn't an importable package — and exercise
its pure ``_build_response`` helper directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

API_FILE = Path(__file__).resolve().parent.parent / "api" / "puzzle.py"


@pytest.fixture(scope="module")
def api():
    spec = importlib.util.spec_from_file_location("api_puzzle", API_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_route(api):
    status, payload = api._build_response({})
    assert status == 200
    assert payload["difficulty"] == "medium"
    assert payload["items"] == 4
    assert payload["clues"]


def test_explicit_params(api):
    status, payload = api._build_response(
        {"difficulty": ["hard"], "items": ["5"], "seed": ["12"]}
    )
    assert status == 200
    assert payload["difficulty"] == "hard"
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
