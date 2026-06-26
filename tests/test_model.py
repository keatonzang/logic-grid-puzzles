"""Theme/Category data model and validation."""

from __future__ import annotations

import pytest

from logicgrid.model import Category, Theme


def test_n_and_k(plain_theme):
    assert plain_theme.n == 3
    assert plain_theme.k == 3


def test_category_value_defaults_to_index():
    cat = Category("C", ["a", "b", "c"])
    assert [cat.value(i) for i in range(3)] == [0, 1, 2]


def test_category_value_uses_values_when_present():
    cat = Category("Year", ["x", "y", "z"], ordered=True, values=[2001, 2005, 2009])
    assert [cat.value(i) for i in range(3)] == [2001, 2005, 2009]


def test_valid_theme_passes(plain_theme, ordered_theme):
    plain_theme.validate()
    ordered_theme.validate()


def test_too_few_categories():
    theme = Theme("t", "", [Category("Only", ["a", "b"])])
    with pytest.raises(ValueError, match="at least 2 categories"):
        theme.validate()


def test_too_few_items():
    theme = Theme("t", "", [Category("A", ["a"]), Category("B", ["b"])])
    with pytest.raises(ValueError, match="at least 2 items"):
        theme.validate()


def test_mismatched_item_counts():
    theme = Theme("t", "", [Category("A", ["a", "b"]), Category("B", ["c", "d", "e"])])
    with pytest.raises(ValueError, match="same number of items"):
        theme.validate()


def test_duplicate_items_within_category():
    theme = Theme("t", "", [Category("A", ["a", "a"]), Category("B", ["c", "d"])])
    with pytest.raises(ValueError, match="duplicate items"):
        theme.validate()


def test_values_length_mismatch():
    theme = Theme(
        "t",
        "",
        [
            Category("A", ["a", "b"], ordered=True, values=[1]),
            Category("B", ["c", "d"]),
        ],
    )
    with pytest.raises(ValueError, match="`values` length"):
        theme.validate()


def test_labels_must_be_globally_unique():
    # "x" appears in both categories
    theme = Theme("t", "", [Category("A", ["x", "b"]), Category("B", ["x", "d"])])
    with pytest.raises(ValueError, match="unique across ALL"):
        theme.validate()
