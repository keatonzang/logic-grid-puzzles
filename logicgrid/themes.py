"""Load themes from YAML or JSON data files."""

from __future__ import annotations

import json
from pathlib import Path

from .model import Category, Theme


def load_theme(path: str | Path) -> Theme:
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "PyYAML is required for .yaml themes (pip install pyyaml), "
                "or use a .json theme instead."
            ) from exc
        data = yaml.safe_load(raw)
    elif path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        raise ValueError(f"unsupported theme extension: {path.suffix} (use .yaml or .json)")

    return theme_from_dict(data)


def theme_from_dict(data: dict) -> Theme:
    cats = []
    for c in data["categories"]:
        cats.append(
            Category(
                name=c["name"],
                items=list(c["items"]),
                ordered=bool(c.get("ordered", False)),
                values=list(c["values"]) if c.get("values") is not None else None,
            )
        )
    theme = Theme(
        name=data.get("name", "Untitled puzzle"),
        description=data.get("description", ""),
        categories=cats,
        entity_noun=data.get("entity_noun", "entry"),
    )
    theme.validate()
    return theme
