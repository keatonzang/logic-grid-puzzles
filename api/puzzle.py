"""Vercel Python serverless function: generate a logic-grid puzzle as JSON.

Routes (both served at /api/puzzle):
    GET /api/puzzle?list=1                       -> {"themes": [...]}
    GET /api/puzzle?theme=detectives&seed=3       -> puzzle payload

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

from logicgrid.webapi import DEFAULT_THEME, build_payload, list_themes  # noqa: E402


def _build_response(query: dict) -> tuple[int, dict]:
    if query.get("list"):
        return 200, {"themes": list_themes()}

    theme = query.get("theme", [DEFAULT_THEME])[0]
    seed_raw = query.get("seed", [None])[0]
    seed = None
    if seed_raw not in (None, ""):
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            return 400, {"error": f"seed must be an integer, got {seed_raw!r}"}

    try:
        return 200, build_payload(theme, seed=seed)
    except KeyError:
        return 400, {"error": f"unknown theme: {theme!r}"}


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
