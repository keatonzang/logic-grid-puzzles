"""Vercel Python serverless function: generate a logic-grid puzzle as JSON.

    GET /api/puzzle?difficulty=medium&items=4&categories=4&seed=3   -> puzzle payload
    POST /api/puzzle {"theme_doc": {...}, "difficulty": "...", "seed": 3}
        -> puzzle payload from a user-supplied theme document (the single-file
           JSON the theme builder exports). Deterministic in (doc, settings,
           seed), so /api/hint regenerates the same puzzle from the same doc.

The actual generation lives in ``logicgrid.webapi`` so it stays unit-testable
without spinning up HTTP.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Make the repo root importable so ``logicgrid`` resolves in the function bundle.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logicgrid.webapi import (  # noqa: E402
    DEFAULT_CATEGORIES,
    DEFAULT_DIFFICULTY,
    DEFAULT_ITEMS,
    DEFAULT_THEME,
    build_payload,
    list_themes,
)

_MAX_BODY = 256 * 1024  # a theme document is a few KB; this is generous


def _build_response(query: dict) -> tuple[int, dict]:
    if "themes" in query:  # catalogue for the theme picker
        return 200, {"themes": list_themes()}

    theme = query.get("theme", [DEFAULT_THEME])[0]
    difficulty = query.get("difficulty", [DEFAULT_DIFFICULTY])[0]

    items_raw = query.get("items", [DEFAULT_ITEMS])[0]
    try:
        items = int(items_raw)
    except (TypeError, ValueError):
        return 400, {"error": f"items must be an integer, got {items_raw!r}"}

    cats_raw = query.get("categories", [DEFAULT_CATEGORIES])[0]
    try:
        categories = int(cats_raw)
    except (TypeError, ValueError):
        return 400, {"error": f"categories must be an integer, got {cats_raw!r}"}

    seed_raw = query.get("seed", [None])[0]
    seed = None
    if seed_raw not in (None, ""):
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            return 400, {"error": f"seed must be an integer, got {seed_raw!r}"}

    try:
        return 200, build_payload(
            seed=seed, difficulty=difficulty, items=items, categories=categories, theme=theme
        )
    except ValueError as exc:
        return 400, {"error": str(exc)}


def _build_custom_response(body: dict) -> tuple[int, dict]:
    """POST form: generate from a user-supplied theme document."""
    if not isinstance(body, dict):
        return 400, {"error": "request body must be a JSON object"}
    theme_doc = body.get("theme_doc")
    if not isinstance(theme_doc, dict):
        return 400, {"error": "theme_doc must be an object (the exported theme file)"}

    difficulty = body.get("difficulty", DEFAULT_DIFFICULTY)
    seed_raw = body.get("seed")
    seed = None
    if seed_raw not in (None, ""):
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            return 400, {"error": f"seed must be an integer, got {seed_raw!r}"}

    try:
        return 200, build_payload(seed=seed, difficulty=difficulty, theme_doc=theme_doc)
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

    def do_GET(self):  # noqa: N802 - Vercel/BaseHTTPRequestHandler contract
        query = parse_qs(urlparse(self.path).query)
        status, payload = _build_response(query)
        self._send(status, payload)

    def do_POST(self):  # noqa: N802 - custom theme documents come in a body
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
        status, payload = _build_custom_response(body)
        self._send(status, payload)

    def do_OPTIONS(self):  # noqa: N802 - CORS preflight for the POST
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, *args):  # silence default stderr logging
        pass
