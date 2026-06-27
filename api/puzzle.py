"""Vercel Python serverless function: generate a logic-grid puzzle as JSON.

    GET /api/puzzle?difficulty=medium&items=4&categories=4&seed=3   -> puzzle payload

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
    build_payload,
)


def _build_response(query: dict) -> tuple[int, dict]:
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
            seed=seed, difficulty=difficulty, items=items, categories=categories
        )
    except ValueError as exc:
        return 400, {"error": str(exc)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - Vercel/BaseHTTPRequestHandler contract
        query = parse_qs(urlparse(self.path).query)
        status, payload = _build_response(query)
        body = json.dumps(payload).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence default stderr logging
        pass
