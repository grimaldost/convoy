"""Tests for the pure gate verdict.

These pin the two properties the run branches on. ``blocking_red`` is the safety
contract — any blocking check that failed makes it true, full stop.
``independent_red`` is the narrower, trustworthy signal — a blocking *and*
independent check that failed. The invariant that carries the safety claim,
checked with hypothesis, is that independence never *suppresses* ``blocking_red``:
marking a failing blocking check independent can only ever add ``independent_red``
on top, never take a red away.

``Check`` values are built directly here (independent+blocking included), which is
fine — the parse-time guard against that combination lives in ``load_series``, not
on the dataclass.
"""

from hypothesis import given
from hypothesis import strategies as st

from convoy.core.gate import (
    CheckResult,
    GateVerdict,
    checks_for,
    checks_for_phases,
    decide,
)
from convoy.core.spec import PR, Check


def _check(name: str, *, blocking: bool, independent: bool = False) -> Check:
    """A ``Check`` with a placeholder ``run``; the verdict never looks at it."""
    return Check(name=name, run='true', blocking=blocking, independent=independent)


def _result(check: Check, *, passed: bool) -> CheckResult:
    return CheckResult(check=check, passed=passed, detail='' if passed else 'red')


def test_decide_wraps_results_in_order() -> None:
    a = _result(_check('a', blocking=True), passed=True)
    b = _result(_check('b', blocking=False), passed=False)
    verdict = decide([a, b])
    assert isinstance(verdict, GateVerdict)
    assert verdict.results == (a, b)


def test_all_pass_is_neither_red() -> None:
    verdict = decide(
        [
            _result(_check('a', blocking=True), passed=True),
            _result(_check('b', blocking=True, independent=True), passed=True),
            _result(_check('c', blocking=False), passed=True),
        ]
    )
    assert verdict.blocking_red is False
    assert verdict.independent_red is False


def test_empty_is_neither_red() -> None:
    verdict = decide([])
    assert verdict.blocking_red is False
    assert verdict.independent_red is False


def test_blocking_failure_is_blocking_red() -> None:
    verdict = decide([_result(_check('a', blocking=True), passed=False)])
    assert verdict.blocking_red is True
    # Not marked independent, so not an independent red.
    assert verdict.independent_red is False


def test_blocking_independent_failure_is_both_reds() -> None:
    verdict = decide([_result(_check('a', blocking=True, independent=True), passed=False)])
    assert verdict.blocking_red is True
    assert verdict.independent_red is True


def test_non_blocking_failure_is_not_blocking_red() -> None:
    # A red on a non-blocking check must never block, independent or not.
    verdict = decide(
        [
            _result(_check('a', blocking=False), passed=False),
            _result(_check('b', blocking=False, independent=True), passed=False),
        ]
    )
    assert verdict.blocking_red is False
    assert verdict.independent_red is False


def test_independent_blocking_red_still_blocks_alongside_a_plain_red() -> None:
    # A blocking independent red and a blocking implementer red together: both
    # properties hold, and the independent one has not softened the block.
    verdict = decide(
        [
            _result(_check('impl', blocking=True), passed=False),
            _result(_check('oracle', blocking=True, independent=True), passed=False),
        ]
    )
    assert verdict.blocking_red is True
    assert verdict.independent_red is True


# --- property: independence never suppresses blocking_red --------------------
#
# A blocking check that failed makes the gate blocking_red no matter what its
# independence flag is. So for any set of results, flipping every failing
# blocking check's ``independent`` flag to True leaves blocking_red unchanged:
# independence can only add independent_red on top, never remove the block.

_BOOL = st.booleans()


@st.composite
def _results(draw: st.DrawFn) -> tuple[CheckResult, ...]:
    count = draw(st.integers(min_value=0, max_value=6))
    out: list[CheckResult] = []
    for i in range(count):
        blocking = draw(_BOOL)
        independent = draw(_BOOL)
        passed = draw(_BOOL)
        check = _check(f'c{i}', blocking=blocking, independent=independent)
        out.append(_result(check, passed=passed))
    return tuple(out)


def _mark_all_independent(results: tuple[CheckResult, ...]) -> tuple[CheckResult, ...]:
    return tuple(
        CheckResult(
            check=Check(
                name=r.check.name,
                run=r.check.run,
                blocking=r.check.blocking,
                independent=True,
            ),
            passed=r.passed,
            detail=r.detail,
        )
        for r in results
    )


@given(_results())
def test_independence_never_suppresses_blocking_red(results: tuple[CheckResult, ...]) -> None:
    baseline = decide(results).blocking_red
    # Marking every check independent cannot change whether a red blocks.
    all_independent = decide(_mark_all_independent(results)).blocking_red
    assert all_independent == baseline
    # And a blocking failure anywhere always means blocking_red, directly.
    expected = any(not r.passed and r.check.blocking for r in results)
    assert baseline == expected


# --- phase scoping (checks_for) ----------------------------------------------
#
# Scoping decides WHICH checks run for a PR; it never touches what a red means.
# The default — a check with no ``phases`` — must select every PR, so a series that
# scopes nothing behaves exactly as it did before the field existed.


def _pr(pr_id: str, phase: str) -> PR:
    return PR(id=pr_id, branch=pr_id, prompt=f'{pr_id}.md', phase=phase)


def test_unscoped_check_gates_every_pr() -> None:
    check = _check('suite', blocking=True)
    assert checks_for([check], _pr('pr-1', 'core')) == (check,)
    assert checks_for([check], _pr('pr-2', 'extras')) == (check,)


def test_scoped_check_gates_only_its_phases() -> None:
    core = Check(name='core-suite', run='true', blocking=True, phases=('core',))
    late = Check(name='late-suite', run='true', blocking=True, phases=('extras',))
    assert checks_for([core, late], _pr('pr-1', 'core')) == (core,)
    assert checks_for([core, late], _pr('pr-4', 'extras')) == (late,)


def test_check_may_name_several_phases() -> None:
    both = Check(name='shared', run='true', blocking=True, phases=('core', 'extras'))
    assert checks_for([both], _pr('pr-1', 'core')) == (both,)
    assert checks_for([both], _pr('pr-4', 'extras')) == (both,)
    assert checks_for([both], _pr('pr-9', 'docs')) == ()


def test_selection_preserves_declaration_order() -> None:
    a = Check(name='a', run='true', blocking=True, phases=('core',))
    b = _check('b', blocking=True)
    c = Check(name='c', run='true', blocking=True, phases=('core',))
    assert checks_for([a, b, c], _pr('pr-1', 'core')) == (a, b, c)


def test_a_pr_may_select_no_checks() -> None:
    # Deliberately not an error: pre-flight reports it as a non-blocking advisory.
    scoped = Check(name='core-suite', run='true', blocking=True, phases=('core',))
    assert checks_for([scoped], _pr('pr-9', 'docs')) == ()


@given(
    st.lists(st.sampled_from(['core', 'extras', 'docs']), max_size=4),
    st.sampled_from(['core', 'extras', 'docs']),
)
def test_scoping_never_changes_what_a_red_means(phases: list[str], pr_phase: str) -> None:
    """Whatever survives selection is judged by the same rules — a blocking red still blocks."""
    check = Check(name='c', run='true', blocking=True, phases=tuple(phases))
    selected = checks_for([check], _pr('pr-1', pr_phase))
    verdict = decide([_result(c, passed=False) for c in selected])
    assert verdict.blocking_red is bool(selected)


# --- checks_for_phases: the gate-only selection ------------------------------------------


def _scoped(name: str, *phases: str) -> Check:
    return Check(name=name, run='true', blocking=True, phases=phases)


def test_no_phases_selects_the_whole_tuple() -> None:
    checks = (_scoped('a'), _scoped('b', 'core'), _scoped('c', 'later'))
    assert checks_for_phases(checks, ()) == checks


def test_a_phase_selects_unscoped_plus_matching_in_declaration_order() -> None:
    unscoped = _scoped('a')
    core = _scoped('b', 'core')
    later = _scoped('c', 'later')
    assert checks_for_phases((later, unscoped, core), ('core',)) == (unscoped, core)


def test_multiple_phases_union_without_duplicates() -> None:
    both = _scoped('b', 'core', 'later')
    assert checks_for_phases((both, _scoped('c', 'later')), ('core', 'later')) == (
        both,
        _scoped('c', 'later'),
    )


def test_an_unknown_phase_still_selects_the_unscoped_checks() -> None:
    unscoped = _scoped('a')
    assert checks_for_phases((unscoped, _scoped('b', 'core')), ('nope',)) == (unscoped,)


def test_phase_selection_agrees_with_the_per_pr_fold() -> None:
    """One phase tag must select exactly what a PR carrying that tag is gated on."""
    checks = (_scoped('a'), _scoped('b', 'core'), _scoped('c', 'later'))
    pr = PR(id='p', branch='p', prompt='p.md', phase='core', depends_on=())
    assert checks_for_phases(checks, ('core',)) == checks_for(checks, pr)
