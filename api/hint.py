"""Vercel Python serverless function: the next explained deduction for a puzzle.

    POST /api/hint
    { "seed": 3, "difficulty": "medium", "items": 4, "categories": 3,
      "known": { "0-1": [[0,1,2,0], ...], ... } }

``seed`` + ``difficulty`` + ``items`` + ``categories`` regenerate the *exact*
puzzle the player is looking at (generation is deterministic in the seed) — or,
for a custom theme, the same ``theme_doc`` the puzzle was generated with — and
``known`` is their current board (0 blank / 1 link / 2 no-link). The response is a
single hint step (cell, value, technique, plain-English reason), or
``{"done": true}`` once nothing new can be deduced.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Make the repo root importable so ``logicgrid`` resolves in the function bundle.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logicgrid.webapi import (  # noqa: E402
    DEFAULT_CATEGORIES,
    DEFAULT_DIFFICULTY,
    DEFAULT_ITEMS,
    DEFAULT_THEME,
    build_hint,
)

_MAX_BODY = 256 * 1024  # generous cap; a board is tiny


def _build_response(body: dict) -> tuple[int, dict]:
    if not isinstance(body, dict):
        return 400, {"error": "request body must be a JSON object"}

    seed_raw = body.get("seed")
    try:
        seed = int(seed_raw)
    except (TypeError, ValueError):
        return 400, {"error": f"seed must be an integer, got {seed_raw!r}"}

    difficulty = body.get("difficulty", DEFAULT_DIFFICULTY)
    try:
        items = int(body.get("items", DEFAULT_ITEMS))
        categories = int(body.get("categories", DEFAULT_CATEGORIES))
    except (TypeError, ValueError):
        return 400, {"error": "items and categories must be integers"}

    known = body.get("known") or {}
    if not isinstance(known, dict):
        return 400, {"error": "known must be an object of i-j -> matrix"}

    theme = body.get("theme", DEFAULT_THEME)
    theme_doc = body.get("theme_doc")
    if theme_doc is not None and not isinstance(theme_doc, dict):
        return 400, {"error": "theme_doc must be an object (the exported theme file)"}

    try:
        return 200, build_hint(seed, difficulty, items, categories, known, theme, theme_doc)
    except ValueError as exc:
        return 400, {"error": str(exc)}


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

    def do_POST(self):  # noqa: N802 - Vercel/BaseHTTPRequestHandler contract
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
        status, payload = _build_response(body)
        self._send(status, payload)

    def do_OPTIONS(self):  # noqa: N802 - CORS preflight for the POST
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, *args):  # silence default stderr logging
        pass
