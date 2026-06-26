"""Clue semantics: holds() truth and text() phrasing for each clue type."""

from __future__ import annotations

import pytest

from logicgrid.clues import (
    AllDifferent,
    Among,
    Diff,
    EitherOr,
    ExactlyKLinks,
    GroupMatch,
    Greater,
    Negative,
    Neither,
    Positive,
    entity_of,
)


def test_entity_of_resolves_column(identity_solution):
    # X[i][c] == i, so item j in any category is carried by entity j
    assert entity_of(identity_solution, (1, 2)) == 2
    assert entity_of(identity_solution, (0, 0)) == 0


def test_entity_of_raises_when_item_absent(identity_solution):
    with pytest.raises(ValueError):
        entity_of(identity_solution, (1, 99))


def test_positive_holds(plain_theme, identity_solution):
    # entity 0 carries item 0 in every category -> these share an entity
    assert Positive((0, 0), (1, 0)).holds(identity_solution)
    # item 0 of cat0 and item 1 of cat1 belong to different entities
    assert not Positive((0, 0), (1, 1)).holds(identity_solution)


def test_positive_text(plain_theme, identity_solution):
    assert Positive((0, 0), (1, 0)).text(plain_theme) == "Ann goes with Dog."


def test_negative_is_complement_of_positive(identity_solution):
    same = (0, 0), (1, 0)
    diff = (0, 0), (1, 1)
    assert Negative(*same).holds(identity_solution) is False
    assert Negative(*diff).holds(identity_solution) is True


def test_negative_text(plain_theme, identity_solution):
    assert Negative((0, 0), (1, 1)).text(plain_theme) == "Ann does not go with Eel."


def test_involved_columns():
    assert Positive((0, 1), (2, 0)).involved == frozenset({0, 2})
    assert Greater(2, (0, 1), (0, 0)).involved == frozenset({0, 2})


def test_removal_classes():
    assert Positive((0, 0), (1, 0)).removal_class == 0
    assert Negative((0, 0), (1, 1)).removal_class == 2
    assert Greater(2, (0, 1), (0, 0)).removal_class == 1


def test_greater_holds(ordered_theme, identity_solution):
    # category 2 is ordered (item index == rank); entity 2 outranks entity 0
    higher = Greater(2, (0, 2), (0, 0))  # ref cat 0: item 2 (entity2) vs item 0 (entity0)
    assert higher.holds(identity_solution)
    lower = Greater(2, (0, 0), (0, 2))
    assert not lower.holds(identity_solution)


def test_greater_text(ordered_theme, identity_solution):
    text = Greater(2, (0, 2), (0, 0)).text(ordered_theme)
    assert "higher Year" in text
    assert "Zu" in text and "Xi" in text


def test_diff_holds(ordered_theme, identity_solution):
    values = [2001, 2002, 2003]
    # entity2's year (2003) minus entity0's (2001) == 2
    assert Diff(2, (0, 2), (0, 0), 2, values).holds(identity_solution)
    assert not Diff(2, (0, 2), (0, 0), 1, values).holds(identity_solution)


def test_diff_text(ordered_theme):
    values = [2001, 2002, 2003]
    text = Diff(2, (0, 2), (0, 0), 2, values).text(ordered_theme)
    assert "exactly 2 more" in text
    assert "Year" in text


# --- "one of N" disjunctions over option *terms* (may span categories) -------
# plain_theme: cat0 Person[Ann,Bo,Cy], cat1 Pet[Dog,Eel,Fox], cat2 Drink[Gin,Hop,Ice]
# identity_solution: X[i][c] == i, so entity 0 = Ann/Dog/Gin.
# Anchor (0, 0) = Ann. True option terms for Ann: (1,0)=Dog, (2,0)=Gin.

def test_options_can_span_categories():
    # one Pet term, one Drink term -> involved spans all three categories
    clue = Among((0, 0), [(1, 0), (2, 1)])
    assert clue.involved == frozenset({0, 1, 2})


def test_among_is_inclusive(identity_solution):
    # >= 1 true. Dog (true) + Hop (false) -> holds.
    assert Among((0, 0), [(1, 0), (2, 1)]).holds(identity_solution)
    # both false -> fails
    assert not Among((0, 0), [(1, 1), (2, 1)]).holds(identity_solution)
    # both true (Dog AND Gin both Ann's) -> still holds, and does NOT imply
    # the two belong to different entities (the key inclusive property)
    assert Among((0, 0), [(1, 0), (2, 0)]).holds(identity_solution)


def test_among_defaults_to_at_least_one(plain_theme):
    clue = Among((0, 0), [(1, 0), (2, 1)])
    assert clue.at_least == 1
    assert clue.text(plain_theme) == "Ann goes with at least one of Dog or Hop."


def test_among_at_least_k_threshold(identity_solution):
    # anchor Ann; Dog (1,0) and Gin (2,0) are both Ann's -> 2 matches.
    both_true = Among((0, 0), [(1, 0), (2, 0)], at_least=2)
    assert both_true.holds(identity_solution)          # 2 >= 2
    # only one of the two is Ann's -> 1 match, fails the >= 2 threshold
    one_true = Among((0, 0), [(1, 0), (2, 1)], at_least=2)
    assert not one_true.holds(identity_solution)


def test_among_at_least_k_text(plain_theme):
    clue = Among((0, 0), [(1, 0), (2, 0)], at_least=2)  # Dog, Gin
    assert clue.text(plain_theme) == "Ann goes with at least two of Dog and Gin."


def test_either_or_is_exclusive(identity_solution):
    # exactly one true. Dog (true) + Hop (false) -> holds.
    assert EitherOr((0, 0), [(1, 0), (2, 1)]).holds(identity_solution)
    # both true -> exclusivity rejects it (the difference from Among)
    assert not EitherOr((0, 0), [(1, 0), (2, 0)]).holds(identity_solution)
    # zero true -> also fails
    assert not EitherOr((0, 0), [(1, 1), (2, 1)]).holds(identity_solution)


def test_either_or_implies_distinct_entities(identity_solution):
    # If two options sit on the SAME entity, EitherOr can never hold...
    same_entity = EitherOr((0, 1), [(1, 1), (2, 1)])  # Bo's pet Eel & drink Hop both Bo's
    assert not same_entity.holds(identity_solution)
    # ...whereas an inclusive Among on those same options does hold.
    assert Among((0, 1), [(1, 1), (2, 1)]).holds(identity_solution)


def test_neither_holds_when_no_option_matches(identity_solution):
    assert Neither((0, 0), [(1, 1), (2, 1)]).holds(identity_solution)      # none Ann's
    assert not Neither((0, 0), [(1, 0), (2, 1)]).holds(identity_solution)  # Dog is Ann's


def test_disjunction_text_phrasing(plain_theme):
    anchor = (0, 0)  # Ann
    assert Among(anchor, [(1, 0), (2, 1)]).text(plain_theme) == \
        "Ann goes with at least one of Dog or Hop."
    assert EitherOr(anchor, [(1, 0), (2, 1)]).text(plain_theme) == \
        "Ann goes with either Dog or Hop."
    assert EitherOr(anchor, [(1, 0), (2, 1), (1, 2)]).text(plain_theme) == \
        "Ann goes with exactly one of Dog, Fox, or Hop."
    assert Neither(anchor, [(1, 1), (2, 1)]).text(plain_theme) == \
        "Ann goes with neither Eel nor Hop."
    assert Neither(anchor, [(1, 0), (1, 1), (2, 1)]).text(plain_theme) == \
        "Ann goes with none of Dog, Eel, or Hop."


def test_options_sorted_so_text_does_not_leak_the_true_one():
    # stored sorted regardless of input order (true option not placed first)
    assert Among((0, 0), [(2, 1), (1, 0)]).options == ((1, 0), (2, 1))


def test_removal_classes_for_disjunctions():
    assert Among((0, 0), [(1, 0), (2, 1)]).removal_class == 1
    assert EitherOr((0, 0), [(1, 0), (2, 1)]).removal_class == 1
    assert Neither((0, 0), [(1, 0), (2, 1)]).removal_class == 2


# --- AllDifferent ("A, B, and C are all different") --------------------------

def test_all_different_holds_when_entities_distinct(identity_solution):
    # entity_of((c, i)) == i under the identity solution.
    assert AllDifferent([(0, 0), (1, 1), (2, 2)]).holds(identity_solution)  # 0,1,2
    # (0,0) and (1,0) both resolve to entity 0 -> a clash
    assert not AllDifferent([(0, 0), (1, 0), (2, 1)]).holds(identity_solution)


def test_all_different_involves_each_category():
    assert AllDifferent([(0, 0), (1, 1), (2, 2)]).involved == frozenset({0, 1, 2})


def test_all_different_text(plain_theme):
    # plain_theme.entity_noun == "row" -> pluralised to "rows"
    clue = AllDifferent([(0, 0), (1, 1), (2, 2)])  # Ann, Eel, Ice
    assert clue.text(plain_theme) == "Ann, Eel, and Ice are all different rows."


def test_all_different_allows_repeated_categories(identity_solution):
    # two terms from category 0 (Ann, Bo) + one from category 1 (Fox=entity2)
    clue = AllDifferent([(0, 0), (0, 1), (1, 2)])
    assert clue.involved == frozenset({0, 1})  # spans two categories
    assert clue.holds(identity_solution)       # entities 0, 1, 2 all distinct


def test_all_different_removal_class():
    assert AllDifferent([(0, 0), (1, 1), (2, 2)]).removal_class == 2


# --- ExactlyKLinks (exclusive pairing, generalised to "exactly K of N") ------
# identity_solution: entity_of((c, i)) == i.

def test_exactly_k_links_xor(identity_solution):
    # one true link (Ann–Dog, both entity 0) + one false (Bo–Dog: entities 1,0)
    true_link = ((0, 0), (1, 0))
    false_link = ((0, 1), (1, 0))
    assert ExactlyKLinks([true_link, false_link], k=1).holds(identity_solution)
    # both true -> count 2, fails "exactly one"
    assert not ExactlyKLinks([((0, 0), (1, 0)), ((0, 1), (1, 1))], k=1).holds(identity_solution)
    # both false -> count 0, fails
    assert not ExactlyKLinks([((0, 0), (1, 1)), ((0, 1), (1, 0))], k=1).holds(identity_solution)


def test_exactly_k_links_higher_k(identity_solution):
    links = [((0, 0), (1, 0)), ((0, 1), (1, 1)), ((0, 2), (1, 0))]  # 2 true, 1 false
    assert ExactlyKLinks(links, k=2).holds(identity_solution)
    assert not ExactlyKLinks(links, k=1).holds(identity_solution)


def test_exactly_k_links_text_xor(plain_theme):
    clue = ExactlyKLinks([((0, 0), (1, 1)), ((0, 1), (1, 0))], k=1)
    assert clue.text(plain_theme) == "Either Ann goes with Eel, or Bo goes with Dog — but not both."


def test_exactly_k_links_text_general(plain_theme):
    clue = ExactlyKLinks([((0, 0), (1, 0)), ((0, 1), (1, 1)), ((0, 2), (2, 0))], k=1)
    txt = clue.text(plain_theme)
    assert txt.startswith("Exactly one of these is true:")
    assert txt.count(";") == 2  # three statements joined by semicolons


def test_exactly_k_links_involved():
    assert ExactlyKLinks([((0, 0), (1, 0)), ((2, 1), (1, 2))], k=1).involved == frozenset({0, 1, 2})


# --- GroupMatch ("between A and B, one is C and the other is D") --------------

def test_group_match_holds(identity_solution):
    # left {Ann, Bo} = entities {0,1}; right {Dog(e0), Hop(e1)} = {0,1} -> holds
    assert GroupMatch([(0, 0), (0, 1)], [(1, 0), (2, 1)]).holds(identity_solution)
    # right {Dog(e0), Ice(e2)} = {0,2} != {0,1} -> fails
    assert not GroupMatch([(0, 0), (0, 1)], [(1, 0), (2, 2)]).holds(identity_solution)


def test_group_match_text_two(plain_theme):
    clue = GroupMatch([(0, 0), (0, 1)], [(1, 0), (2, 1)])  # Ann,Bo / Dog,Hop
    assert clue.text(plain_theme) == "Between Ann and Bo, one goes with Dog and the other with Hop."


def test_group_match_text_three(plain_theme):
    clue = GroupMatch([(0, 0), (0, 1), (0, 2)], [(1, 0), (1, 1), (1, 2)])
    assert clue.text(plain_theme) == "Ann, Bo, and Cy go with Dog, Eel, and Fox, in some order."


def test_group_match_involves_both_sides():
    assert GroupMatch([(0, 0), (0, 1)], [(1, 0), (2, 1)]).involved == frozenset({0, 1, 2})
