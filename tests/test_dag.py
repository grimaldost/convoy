"""Tests for DAG ordering: edge-respecting, stable, and rejecting invalid graphs."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from convoy.core.dag import DagError, order
from convoy.core.spec import PR


def _pr(pr_id: str, *depends_on: str) -> PR:
    """A PR with only the fields ``order`` looks at; the rest are filler."""
    return PR(id=pr_id, branch='b', prompt='p', phase='x', depends_on=tuple(depends_on))


def _positions(result: tuple[PR, ...]) -> dict[str, int]:
    return {pr.id: index for index, pr in enumerate(result)}


def test_empty_returns_empty() -> None:
    assert order(()) == ()


def test_single_pr_returns_itself() -> None:
    single = _pr('a')
    assert order((single,)) == (single,)


def test_chain_orders_dependency_first_regardless_of_input_order() -> None:
    a = _pr('a')
    b = _pr('b', 'a')
    assert order((a, b)) == (a, b)
    # b listed before its dependency a: the result must still put a first.
    assert order((b, a)) == (a, b)


def test_result_respects_every_depends_on_edge() -> None:
    # d depends on b and c; b and c each depend on a. Every dependency must
    # precede its dependent in the result.
    a = _pr('a')
    b = _pr('b', 'a')
    c = _pr('c', 'a')
    d = _pr('d', 'b', 'c')
    result = order((d, c, b, a))
    at = _positions(result)
    assert set(at) == {'a', 'b', 'c', 'd'}
    assert at['a'] < at['b']
    assert at['a'] < at['c']
    assert at['b'] < at['d']
    assert at['c'] < at['d']


def test_independent_prs_keep_input_order() -> None:
    # No edge between the three, so the sort must not reorder them.
    a = _pr('a')
    b = _pr('b')
    c = _pr('c')
    assert order((c, a, b)) == (c, a, b)
    assert order((a, b, c)) == (a, b, c)


def test_stability_with_a_late_dependency() -> None:
    # c depends on a; b is independent. a and b are both ready initially and must
    # keep input order (a before b); c follows once a is placed.
    a = _pr('a')
    b = _pr('b')
    c = _pr('c', 'a')
    assert order((a, b, c)) == (a, b, c)


def test_cycle_raises() -> None:
    a = _pr('a', 'b')
    b = _pr('b', 'a')
    with pytest.raises(DagError):
        order((a, b))


def test_self_cycle_raises() -> None:
    with pytest.raises(DagError):
        order((_pr('a', 'a'),))


def test_unknown_dependency_raises() -> None:
    with pytest.raises(DagError):
        order((_pr('a', 'ghost'),))


# --- property: on a valid DAG, every PR precedes all of its dependents --------
#
# Generate unique ids, give each an acyclic dependency set (only earlier ids can
# be depended on), then present the PRs in a SHUFFLED input order so the sort has
# real reordering to do rather than receiving an already-topological sequence.

_IDS = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E, blacklist_characters='"\\'),
    min_size=1,
    max_size=8,
)


@st.composite
def _valid_dag(draw: st.DrawFn) -> tuple[PR, ...]:
    ids = draw(st.lists(_IDS, min_size=0, max_size=6, unique=True))
    prs: list[PR] = []
    for index, pr_id in enumerate(ids):
        earlier = ids[:index]
        depends_on = (
            draw(st.lists(st.sampled_from(earlier), max_size=len(earlier), unique=True))
            if earlier
            else []
        )
        prs.append(_pr(pr_id, *depends_on))
    return tuple(draw(st.permutations(prs)))


@given(_valid_dag())
def test_valid_dag_every_pr_precedes_its_dependents(prs: tuple[PR, ...]) -> None:
    result = order(prs)
    # Same multiset of PRs, no drops or dupes.
    assert sorted(pr.id for pr in result) == sorted(pr.id for pr in prs)
    at = _positions(result)
    # For each edge (dependency -> pr), the dependency comes first.
    for pr in prs:
        for dependency in pr.depends_on:
            assert at[dependency] < at[pr.id]
