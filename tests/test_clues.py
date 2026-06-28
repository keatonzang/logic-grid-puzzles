"""Clue semantics: holds() truth and text() phrasing for each clue type."""

from __future__ import annotations

import pytest

from logicgrid.clues import (
    AbsApart,
    Adjacent,
    AllDifferent,
    Among,
    AtLeastApart,
    AtMost,
    Between,
    Diff,
    DiffGroup,
    EitherOr,
    Exactly,
    ExactlyKLinks,
    GroupCount,
    GroupGroupCompare,
    GroupGroupCount,
    GroupOrder,
    Iff,
    Implies,
    InGroup,
    NotInGroup,
    SameGroup,
    GroupMatch,
    Greater,
    MultiCompare,
    Negative,
    Neither,
    NextTo,
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
    assert "higher year" in text
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
    assert "year" in text  # category name reads lower-case mid-sentence


def test_between_holds(ordered_theme, identity_solution):
    # ranks under identity: entity i has rank i in ordered cat 2
    assert Between(2, (0, 0), (0, 2), (0, 1)).holds(identity_solution)      # 0 < 1 < 2
    assert Between(2, (0, 2), (0, 0), (0, 1)).holds(identity_solution)      # endpoints swapped
    assert not Between(2, (0, 0), (0, 1), (0, 2)).holds(identity_solution)  # 2 not between 0,1


def test_between_text(ordered_theme, identity_solution):
    text = Between(2, (0, 0), (0, 2), (0, 1)).text(ordered_theme)  # Xi, Zu, Yo
    assert text == "Yo's year is between Xi and Zu."


def test_between_involves_all_three(ordered_theme):
    assert Between(2, (0, 0), (1, 1), (0, 2)).involved == frozenset({0, 1, 2})


def test_adjacent_holds(ordered_theme, identity_solution):
    assert Adjacent(2, (0, 0), (0, 1)).holds(identity_solution)      # rank 1 == 0 + 1
    assert not Adjacent(2, (0, 0), (0, 2)).holds(identity_solution)  # 2 != 0 + 1
    assert not Adjacent(2, (0, 1), (0, 0)).holds(identity_solution)  # wrong direction


def test_adjacent_text(ordered_theme, identity_solution):
    text = Adjacent(2, (0, 0), (0, 1)).text(ordered_theme)  # Xi, Yo
    assert text == "Xi's year is immediately below Yo."


def test_next_to_is_undirected(ordered_theme, identity_solution):
    # consecutive ranks hold in EITHER direction (unlike Adjacent)
    assert NextTo(2, (0, 0), (0, 1)).holds(identity_solution)   # ranks 0,1
    assert NextTo(2, (0, 1), (0, 0)).holds(identity_solution)   # reversed -> still next to
    assert not NextTo(2, (0, 0), (0, 2)).holds(identity_solution)  # 2 apart
    assert NextTo(2, (0, 1), (0, 0)).removal_class == 1


def test_next_to_text(ordered_theme, identity_solution):
    assert NextTo(2, (0, 0), (0, 1)).text(ordered_theme) == \
        "Xi's year is immediately next to Yo."


def test_abs_apart_at_least(ordered_theme, identity_solution):
    v = [2001, 2002, 2003]
    # |2003 - 2001| = 2; direction-free
    assert AbsApart(2, (0, 2), (0, 0), 2, True, v).holds(identity_solution)
    assert AbsApart(2, (0, 0), (0, 2), 2, True, v).holds(identity_solution)  # reversed
    assert not AbsApart(2, (0, 2), (0, 0), 3, True, v).holds(identity_solution)


def test_abs_apart_at_most(ordered_theme, identity_solution):
    v = [2001, 2002, 2003]
    # at most 1 away: ranks 0 and 1 (gap 1) hold; ranks 0 and 2 (gap 2) don't
    assert AbsApart(2, (0, 0), (0, 1), 1, False, v).holds(identity_solution)
    assert AbsApart(2, (0, 1), (0, 0), 1, False, v).holds(identity_solution)  # reversed
    assert not AbsApart(2, (0, 0), (0, 2), 1, False, v).holds(identity_solution)


def test_abs_apart_text(ordered_theme):
    v = [2001, 2002, 2003]
    assert AbsApart(2, (0, 2), (0, 0), 2, True, v).text(ordered_theme) == \
        "Zu's year is at least 2 away from Xi."
    assert AbsApart(2, (0, 0), (0, 1), 1, False, v).text(ordered_theme) == \
        "Xi's year is at most 1 away from Yo."


def test_unit_prefixes_amounts_in_numeric_clues():
    # a category with a unit ("$") formats clue *amounts*, e.g. "exactly $3 more"
    from logicgrid.model import Category, Theme

    v = [5, 7, 9]
    theme = Theme("Café", "", [
        Category("Customer", ["Ava", "Ben", "Cara"]),
        Category("Drink", ["Chai", "Latte", "Mocha"]),
        Category("Price", ["$5", "$7", "$9"], ordered=True, values=v, unit="$"),
    ])
    assert Diff(2, (0, 2), (0, 0), 4, v).text(theme) == \
        "Cara's price is exactly $4 more than Ava."
    assert AtLeastApart(2, (0, 2), (0, 0), 4, v).text(theme) == \
        "Cara's price is at least $4 more than Ava."
    assert AbsApart(2, (0, 2), (0, 0), 4, True, v).text(theme) == \
        "Cara's price is at least $4 away from Ava."
    assert AbsApart(2, (0, 1), (0, 0), 2, False, v).text(theme) == \
        "Ben's price is at most $2 away from Ava."


# --- new value dials: AtLeastApart / MultiCompare / AtMost --------------------
# ordered_theme cat 2 = Year, values [2001, 2002, 2003]; identity ranks 0,1,2.

def test_at_least_apart_holds_and_text(ordered_theme, identity_solution):
    v = [2001, 2002, 2003]
    assert AtLeastApart(2, (0, 2), (0, 0), 2, v).holds(identity_solution)      # gap 2 >= 2
    assert AtLeastApart(2, (0, 2), (0, 0), 1, v).holds(identity_solution)      # 2 >= 1 (loose)
    assert not AtLeastApart(2, (0, 2), (0, 0), 3, v).holds(identity_solution)  # 2 >= 3 fails
    assert AtLeastApart(2, (0, 2), (0, 0), 2, v).text(ordered_theme) == \
        "Zu's year is at least 2 more than Xi."


def test_multi_compare_holds_and_text(ordered_theme, identity_solution):
    above = MultiCompare(2, (0, 2), [(0, 0), (0, 1)], greater=True)   # Zu > Xi and Yo
    below = MultiCompare(2, (0, 0), [(0, 1), (0, 2)], greater=False)  # Xi < Yo and Zu
    assert above.holds(identity_solution)
    assert below.holds(identity_solution)
    assert not MultiCompare(2, (0, 1), [(0, 0), (0, 2)], greater=True).holds(identity_solution)
    assert above.text(ordered_theme) == "Zu's year was more than both Xi and Yo."


def test_at_most_holds_and_text(plain_theme, identity_solution):
    assert AtMost((0, 0), [(1, 0), (2, 1)], 1).holds(identity_solution)      # 1 match <= 1
    assert not AtMost((0, 0), [(1, 0), (2, 0)], 1).holds(identity_solution)  # 2 matches > 1
    assert AtMost((0, 0), [(1, 0), (2, 1)], 1).removal_class == 2
    assert AtMost((0, 0), [(1, 0), (2, 1)], 1).text(plain_theme) == \
        "Ann goes with at most one of Dog and Hop."


def test_exactly_holds_and_text(plain_theme, identity_solution):
    # Ann's true options are Dog (1,0) and Gin (2,0); Hop (2,1) is wrong.
    assert Exactly((0, 0), [(1, 0), (2, 0)], 2).holds(identity_solution)      # 2 match == 2
    assert not Exactly((0, 0), [(1, 0), (2, 1)], 2).holds(identity_solution)  # 1 match != 2
    assert not Exactly((0, 0), [(1, 0), (2, 0)], 1).holds(identity_solution)  # 2 match != 1
    assert Exactly((0, 0), [(1, 0), (2, 1)], 2).removal_class == 2
    assert Exactly((0, 0), [(1, 0), (2, 1)], 2).text(plain_theme) == \
        "Ann goes with exactly two of Dog and Hop."


# --- Conditionals: links A–B and C–D (entity 0 = Ann/Dog/Gin) ----------------

def test_implies_holds_and_text(plain_theme, identity_solution):
    A_D = ((0, 0), (1, 0))    # Ann–Dog: true (both entity 0)
    A_G = ((0, 0), (2, 0))    # Ann–Gin: true (both entity 0)
    A_Hop = ((0, 0), (2, 1))  # Ann–Hop: false
    Eel_Ice = ((1, 1), (2, 2))  # false (different entities)
    assert Implies(A_D, A_G).holds(identity_solution)        # T -> T
    assert not Implies(A_D, A_Hop).holds(identity_solution)  # T -> F  (violated)
    assert Implies(Eel_Ice, A_Hop).holds(identity_solution)  # F -> _  (vacuous)
    assert Implies(A_D, A_G).removal_class == 2
    assert Implies(((0, 0), (1, 0)), ((1, 1), (2, 2))).text(plain_theme) == \
        "If Ann goes with Dog, then Eel goes with Ice."


def test_iff_holds_and_text(plain_theme, identity_solution):
    A_D = ((0, 0), (1, 0))    # true
    A_G = ((0, 0), (2, 0))    # true
    A_Hop = ((0, 0), (2, 1))  # false
    Eel_Ice = ((1, 1), (2, 2))  # false
    assert Iff(A_D, A_G).holds(identity_solution)        # T <-> T
    assert Iff(A_Hop, Eel_Ice).holds(identity_solution)  # F <-> F
    assert not Iff(A_D, A_Hop).holds(identity_solution)  # T <-> F
    assert Iff(A_D, A_G).removal_class == 2
    assert Iff(((0, 0), (1, 0)), ((1, 1), (2, 2))).text(plain_theme) == \
        "Ann goes with Dog if and only if Eel goes with Ice."


# --- Hierarchy / groups ------------------------------------------------------
# Pet category grouped into "kinds": Furred = {Dog, Fox}, Finned = {Eel}.

def _group_theme():
    from logicgrid.model import Category, Theme

    return Theme("G", "", [
        Category("Owner", ["Ann", "Bo", "Cy"]),
        Category("Pet", ["Dog", "Eel", "Fox"], group_noun="kind",
                 groups=(("Furred", ("Dog", "Fox")), ("Finned", ("Eel",)))),
    ], entity_noun="home")


_GROUP_X = [[0, 0], [1, 1], [2, 2]]  # Ann-Dog, Bo-Eel, Cy-Fox
_FURRED, _FINNED = (0, 2), (1,)
_PART = (_FURRED, _FINNED)


def test_in_group_holds_and_text():
    g = _group_theme()
    assert InGroup((0, 0), 1, "Furred", _FURRED).holds(_GROUP_X)       # Ann -> Dog in Furred
    assert not InGroup((0, 1), 1, "Furred", _FURRED).holds(_GROUP_X)   # Bo -> Eel not in Furred
    assert InGroup((0, 0), 1, "Furred", _FURRED).removal_class == 2
    assert InGroup((0, 0), 1, "Furred", _FURRED).text(g) == "Ann belongs to the Furred."


def test_same_group_holds_and_text():
    g = _group_theme()
    assert SameGroup((0, 0), (0, 2), 1, "kind", _PART).holds(_GROUP_X)      # Dog & Fox both Furred
    assert not SameGroup((0, 0), (0, 1), 1, "kind", _PART).holds(_GROUP_X)  # Dog vs Eel
    assert SameGroup((0, 0), (0, 2), 1, "kind", _PART).text(g) == \
        "Ann and Cy are in the same kind."


def test_diff_group_holds_and_text():
    g = _group_theme()
    assert DiffGroup((0, 0), (0, 1), 1, "kind", _PART).holds(_GROUP_X)      # Furred vs Finned
    assert not DiffGroup((0, 0), (0, 2), 1, "kind", _PART).holds(_GROUP_X)  # both Furred
    assert DiffGroup((0, 0), (0, 1), 1, "kind", _PART).text(g) == \
        "Ann and Bo are in different kinds."


def test_not_in_group_holds_and_text():
    g = _group_theme()
    # Bo -> Eel (Finned), so Bo is NOT in Furred -> holds; Ann -> Dog IS Furred -> fails
    assert NotInGroup((0, 1), 1, "Furred", _FURRED).holds(_GROUP_X)
    assert not NotInGroup((0, 0), 1, "Furred", _FURRED).holds(_GROUP_X)
    assert NotInGroup((0, 1), 1, "Furred", _FURRED).removal_class == 2
    assert NotInGroup((0, 1), 1, "Furred", _FURRED).text(g) == \
        "Bo does not belong to the Furred."


def test_group_count_holds_modes():
    # _GROUP_X: Ann->Dog(Furred), Bo->Eel(Finned), Cy->Fox(Furred). Furred has 2 of 3.
    anchors = [(0, 0), (0, 1), (0, 2)]
    assert GroupCount(anchors, 1, "Furred", _FURRED, 2, "exactly").holds(_GROUP_X)
    assert not GroupCount(anchors, 1, "Furred", _FURRED, 3, "exactly").holds(_GROUP_X)
    assert GroupCount(anchors, 1, "Furred", _FURRED, 2, "atleast").holds(_GROUP_X)
    assert GroupCount(anchors, 1, "Furred", _FURRED, 1, "atleast").holds(_GROUP_X)
    assert not GroupCount(anchors, 1, "Furred", _FURRED, 3, "atleast").holds(_GROUP_X)
    assert GroupCount(anchors, 1, "Furred", _FURRED, 2, "atmost").holds(_GROUP_X)
    assert not GroupCount(anchors, 1, "Furred", _FURRED, 1, "atmost").holds(_GROUP_X)
    assert GroupCount(anchors, 1, "Furred", _FURRED, 2, "exactly").removal_class == 2


def test_group_count_text():
    g = _group_theme()
    c = GroupCount([(0, 0), (0, 1), (0, 2)], 1, "Furred", _FURRED, 2, "exactly")
    assert c.text(g) == "Exactly two of Ann, Bo, and Cy belong to the Furred."
    al = GroupCount([(0, 0), (0, 1)], 1, "Furred", _FURRED, 1, "atleast")
    assert al.text(g) == "At least one of Ann and Bo belong to the Furred."
    am = GroupCount([(0, 0), (0, 1)], 1, "Furred", _FURRED, 1, "atmost")
    assert am.text(g) == "At most one of Ann and Bo belong to the Furred."
    # k == 0 reads as "None of ..." rather than "Exactly 0 of ..."
    z_ex = GroupCount([(0, 0), (0, 1)], 1, "Furred", _FURRED, 0, "exactly")
    z_am = GroupCount([(0, 0), (0, 1)], 1, "Furred", _FURRED, 0, "atmost")
    assert z_ex.text(g) == "None of Ann and Bo belong to the Furred."
    assert z_am.text(g) == "None of Ann and Bo belong to the Furred."


def _ordered_group_theme():
    # Pet grouped (Furred={Dog,Fox}, Finned={Eel}); Score ordered (ranks 0,1,2)
    from logicgrid.model import Category, Theme

    return Theme("G", "", [
        Category("Owner", ["Ann", "Bo", "Cy"]),
        Category("Pet", ["Dog", "Eel", "Fox"], group_noun="kind",
                 groups=(("Furred", ("Dog", "Fox")), ("Finned", ("Eel",)))),
        Category("Score", ["Lo", "Mid", "Hi"], ordered=True, values=[1, 2, 3]),
    ], entity_noun="home")


def test_group_order_holds_and_text():
    g = _ordered_group_theme()
    # X: entity0 Ann-Dog(Furred)-Mid, entity1 Bo-Eel(Finned)-Lo, entity2 Cy-Fox(Furred)-Hi
    # Furred ranks {1,2} (Mid,Hi); Finned rank {0} (Lo) -> Furred all above Finned.
    X = [[0, 0, 1], [1, 1, 0], [2, 2, 2]]
    assert GroupOrder(1, 2, (0, 2), (1,), "Furred", "Finned").holds(X)
    assert not GroupOrder(1, 2, (1,), (0, 2), "Finned", "Furred").holds(X)  # reverse false
    assert GroupOrder(1, 2, (0, 2), (1,), "Furred", "Finned").removal_class == 2
    assert GroupOrder(1, 2, (0, 2), (1,), "Furred", "Finned").text(g) == \
        "Everyone in the Furred ranks higher in score than everyone in the Finned."


def _two_partition_theme():
    # Trade grouped (Guild G={t0,t1}/H={t2,t3}); Quarter grouped (Ward W={q0,q1}/E={q2,q3})
    from logicgrid.model import Category, Theme

    return Theme("T", "", [
        Category("Owner", ["A", "B", "C", "D"]),
        Category("Trade", ["t0", "t1", "t2", "t3"], group_noun="guild",
                 groups=(("G", ("t0", "t1")), ("H", ("t2", "t3")))),
        Category("Quarter", ["q0", "q1", "q2", "q3"], group_noun="ward",
                 groups=(("W", ("q0", "q1")), ("E", ("q2", "q3")))),
    ], entity_noun="artisan")


# X: e0 t0/q0, e1 t1/q1, e2 t2/q2, e3 t3/q3  -> G={e0,e1} all in W; H={e2,e3} all in E
_TWO_X = [[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3]]


def test_group_group_count_holds_and_text():
    g = _two_partition_theme()
    G, H, W, E = (0, 1), (2, 3), (0, 1), (2, 3)
    # G∩W = {e0,e1} = 2 ; G∩E = 0
    assert GroupGroupCount(1, G, "G", 2, W, "W", 2, "exactly").holds(_TWO_X)
    assert GroupGroupCount(1, G, "G", 2, E, "E", 0, "exactly").holds(_TWO_X)
    assert GroupGroupCount(1, G, "G", 2, W, "W", 1, "atleast").holds(_TWO_X)
    assert not GroupGroupCount(1, G, "G", 2, W, "W", 1, "atmost").holds(_TWO_X)
    assert GroupGroupCount(1, G, "G", 2, W, "W", 2, "exactly").removal_class == 2
    assert GroupGroupCount(1, G, "Guild G", 2, W, "Ward W", 2, "exactly").text(g) == \
        "Exactly two members of the Guild G are in the Ward W."
    assert GroupGroupCount(1, G, "Guild G", 2, W, "Ward W", 1, "atleast").text(g) == \
        "At least one member of the Guild G is in the Ward W."
    assert GroupGroupCount(1, G, "Guild G", 2, E, "Ward E", 0, "exactly").text(g) == \
        "No members of the Guild G are in the Ward E."


def test_group_group_compare_holds_and_text():
    g = _two_partition_theme()
    G, H, W = (0, 1), (2, 3), (0, 1)
    # G∩W = 2, H∩W = 0  -> more G than H in W
    assert GroupGroupCompare(1, G, "G", H, "H", 2, W, "W").holds(_TWO_X)
    assert not GroupGroupCompare(1, H, "H", G, "G", 2, W, "W").holds(_TWO_X)  # reverse false
    assert GroupGroupCompare(1, G, "G", H, "H", 2, W, "W").removal_class == 2
    assert GroupGroupCompare(1, G, "Guild G", H, "Guild H", 2, W, "Ward W").text(g) == \
        "More members of the Guild G are in the Ward W than members of the Guild H."


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
    assert clue.text(plain_theme) == "Ann, Eel, and Ice belong to different rows."


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
