"""Shared fixtures: small hand-built themes and a known solution to assert against."""

from __future__ import annotations

import pytest

from logicgrid.model import Category, Theme

THEMES_DIR = "themes"


@pytest.fixture
def plain_theme() -> Theme:
    """A minimal 3x3 theme with no ordered category."""
    return Theme(
        name="Tiny",
        description="three by three",
        entity_noun="row",
        categories=[
            Category("Person", ["Ann", "Bo", "Cy"]),
            Category("Pet", ["Dog", "Eel", "Fox"]),
            Category("Drink", ["Gin", "Hop", "Ice"]),
        ],
    )


@pytest.fixture
def ordered_theme() -> Theme:
    """A 3x3 theme with one ordered, numeric-valued category."""
    return Theme(
        name="Ordered",
        description="with a ranked column",
        entity_noun="entry",
        categories=[
            Category("Name", ["Xi", "Yo", "Zu"]),
            Category("Color", ["Red", "Green", "Blue"]),
            Category(
                "Year",
                ["2001", "2002", "2003"],
                ordered=True,
                values=[2001, 2002, 2003],
            ),
        ],
    )


@pytest.fixture
def wide_theme() -> Theme:
    """A 4-category x 3-item theme — wide enough for 'at least K of N' (K>=2)
    clues, which need at least 3 categories besides the anchor's."""
    return Theme(
        name="Wide",
        description="four categories",
        entity_noun="row",
        categories=[
            Category("Name", ["Al", "Bea", "Coe"]),
            Category("Pet", ["Dog", "Eel", "Fox"]),
            Category("Toy", ["Gem", "Hat", "Ink"]),
            Category("City", ["Juno", "Kiev", "Lima"]),
        ],
    )


@pytest.fixture
def identity_solution() -> list[list[int]]:
    """Solution where entity i carries item i in every category (X[i][c] == i)."""
    return [[i, i, i] for i in range(3)]
