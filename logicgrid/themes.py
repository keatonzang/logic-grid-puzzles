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
                unit=c.get("unit", ""),
                unit_suffix=c.get("unit_suffix", ""),
                referent=c.get("referent", ""),
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


def theme_to_dict(theme: Theme) -> dict:
    """Serialise a Theme to a plain dict — the inverse of ``theme_from_dict`` and
    the canonical *single-file* representation (round-trips through JSON, ready for
    a future user-authored-theme import/export). Optional category fields are
    omitted when at their default, so exported files stay minimal."""
    cats = []
    for c in theme.categories:
        cd: dict = {"name": c.name, "items": list(c.items)}
        if c.ordered:
            cd["ordered"] = True
        if c.values is not None:
            cd["values"] = list(c.values)
        if c.unit:
            cd["unit"] = c.unit
        if c.unit_suffix:
            cd["unit_suffix"] = c.unit_suffix
        if c.referent:
            cd["referent"] = c.referent
        cats.append(cd)
    return {
        "name": theme.name,
        "description": theme.description,
        "entity_noun": theme.entity_noun,
        "categories": cats,
    }


def theme_to_json(theme: Theme, *, indent: int = 2) -> str:
    """The whole theme as one JSON string — what import/export round-trips."""
    return json.dumps(theme_to_dict(theme), indent=indent, ensure_ascii=False)


def theme_from_json(text: str) -> Theme:
    """Parse (and validate) a theme from a JSON string — the import counterpart.

    Raises ``ValueError`` (with a human-readable message from ``Theme.validate``)
    on a malformed or inconsistent theme, so an importer can surface it directly.
    """
    return theme_from_dict(json.loads(text))
