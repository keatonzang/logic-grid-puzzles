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


def test_plural_ordered_category_name_warns():
    # comparison clues assume a singular name; "Earnings" reads with disagreement
    theme = Theme("t", "", [
        Category("A", ["p", "q"]),
        Category("Earnings", ["lo", "hi"], ordered=True, values=[10, 20]),
    ])
    with pytest.warns(UserWarning, match="looks like a plural"):
        theme.validate()


def test_singular_s_name_does_not_warn(recwarn):
    # '-s' singulars (Status/Bonus/Class/Axis) must NOT trip the heuristic
    for name in ("Status", "Bonus", "Class", "Axis"):
        Theme("t", "", [
            Category("A", ["p", "q"]),
            Category(name, ["lo", "hi"], ordered=True, values=[10, 20]),
        ]).validate()
    assert len(recwarn) == 0


def test_plural_flag_suppresses_warning(recwarn):
    # setting plural=True opts into plural agreement, so no warning is emitted
    Theme("t", "", [
        Category("A", ["p", "q"]),
        Category("Earnings", ["lo", "hi"], ordered=True, values=[10, 20], plural=True),
    ]).validate()
    assert len(recwarn) == 0


def test_category_verb_and_article_agree_with_plural():
    sing = Category("Price", ["a", "b"], ordered=True)
    plur = Category("Dues", ["a", "b"], ordered=True, plural=True)
    assert (sing.verb, sing.article) == ("is", "a ")
    assert (plur.verb, plur.article) == ("are", "")
