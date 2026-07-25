"""Tests for the pure structural pre-flight (core/preflight.py)."""

import pytest

from convoy.core.preflight import (
    check_dag,
    check_governance,
    check_phases,
    inert_assets,
    structural_problems,
    ungated_prs,
)
from convoy.core.spec import (
    PR,
    Branches,
    Budgets,
    Check,
    Governance,
    Paths,
    Review,
    Series,
    Tools,
)


def _gov(*, model: str | None = None, tier: str | None = None) -> Governance:
    return Governance(
        effort='low',
        permission_mode='default',
        timeout_seconds=60,
        budgets=Budgets(implementation=1.0, review=1.0, fix=1.0),
        tools=Tools(implementation=('Read',), review=(), fix=()),
        model=model,
        tier=tier,
    )


def _series(
    *,
    governance: Governance | None = None,
    prs: tuple[PR, ...] = (),
    checks: tuple[Check, ...] = (),
) -> Series:
    return Series(
        id='s',
        version='1',
        branches=Branches(base='base', integration='integration'),
        paths=Paths(prompts='/tmp/p', outputs='/tmp/o'),
        governance=governance or _gov(model='claude-haiku-4-5'),
        review=Review(blocking=False, max_fix_attempts=0),
        checks=checks,
        prs=prs,
    )


_CYCLE = (
    PR(id='a', branch='a', prompt='a.md', phase='p', depends_on=('b',)),
    PR(id='b', branch='b', prompt='b.md', phase='p', depends_on=('a',)),
)
_ACYCLIC = (
    PR(id='a', branch='a', prompt='a.md', phase='p'),
    PR(id='b', branch='b', prompt='b.md', phase='p', depends_on=('a',)),
)


def test_clean_series_has_no_problems() -> None:
    assert structural_problems(_series(prs=_ACYCLIC)) == []


def test_unknown_tier_is_a_governance_problem() -> None:
    problems = check_governance(_series(governance=_gov(tier='banana')))
    assert len(problems) == 1
    assert problems[0].kind == 'governance'
    assert 'banana' in problems[0].message


def test_neither_model_nor_tier_is_a_governance_problem() -> None:
    problems = check_governance(_series(governance=_gov()))
    assert len(problems) == 1
    assert problems[0].kind == 'governance'


def test_explicit_model_has_no_governance_problem() -> None:
    assert check_governance(_series(governance=_gov(model='claude-opus-4-8'))) == []


def test_unknown_per_pr_tier_is_a_governance_problem() -> None:
    # Without this the typo survives `convoy validate` AND the run pre-flight, then raises
    # mid-run — after earlier PRs already spent real money.
    prs = (PR(id='a', branch='a', prompt='a.md', phase='p', tier='banana'),)
    problems = check_governance(_series(prs=prs))
    assert len(problems) == 1
    assert problems[0].kind == 'governance'
    assert "'a'" in problems[0].where
    assert 'banana' in problems[0].message


def test_valid_per_pr_override_has_no_governance_problem() -> None:
    prs = (
        PR(id='a', branch='a', prompt='a.md', phase='p', tier='weak'),
        PR(id='b', branch='b', prompt='b.md', phase='p', model='claude-opus-4-8'),
        PR(id='c', branch='c', prompt='c.md', phase='p'),
    )
    assert check_governance(_series(prs=prs)) == []


def test_series_governance_must_resolve_even_when_every_pr_overrides() -> None:
    # [governance] stays the required fallback and the audit baseline. A broken series
    # value yields ONE problem, not 1+N: only PRs that actually override are checked.
    prs = (
        PR(id='a', branch='a', prompt='a.md', phase='p', tier='weak'),
        PR(id='b', branch='b', prompt='b.md', phase='p', tier='strong'),
    )
    problems = check_governance(_series(governance=_gov(), prs=prs))
    assert len(problems) == 1
    assert problems[0].where == '[governance]'


def test_cycle_is_a_dag_problem() -> None:
    problems = check_dag(_series(prs=_CYCLE))
    assert len(problems) == 1
    assert problems[0].kind == 'dag'


def test_acyclic_graph_has_no_dag_problem() -> None:
    assert check_dag(_series(prs=_ACYCLIC)) == []


def test_structural_collects_both_categories() -> None:
    problems = structural_problems(_series(governance=_gov(tier='banana'), prs=_CYCLE))
    kinds = sorted(problem.kind for problem in problems)
    assert kinds == ['dag', 'governance']


# --- phase resolution and gate coverage --------------------------------------


def _phased(pr_id: str, phase: str) -> PR:
    return PR(id=pr_id, branch=pr_id, prompt=f'{pr_id}.md', phase=phase)


def test_unknown_phase_tag_is_a_problem() -> None:
    """A typo would silently reduce the check to gating nothing, so it must fail loud."""
    series = _series(
        prs=(_phased('pr-1', 'core'),),
        checks=(Check(name='suite', run='true', blocking=True, phases=('cores',)),),
    )
    problems = check_phases(series)
    assert len(problems) == 1
    assert problems[0].kind == 'phases'
    assert problems[0].where == "[[checks]] 'suite'"
    assert 'cores' in problems[0].message
    # The message names what IS declared, so the fix is obvious without opening the spec.
    assert 'core' in problems[0].message


def test_known_phase_tags_are_clean() -> None:
    series = _series(
        prs=(_phased('pr-1', 'core'), _phased('pr-2', 'extras')),
        checks=(Check(name='suite', run='true', blocking=True, phases=('core', 'extras')),),
    )
    assert check_phases(series) == []


def test_unscoped_check_needs_no_declared_phase() -> None:
    series = _series(
        prs=(_phased('pr-1', 'core'),),
        checks=(Check(name='suite', run='true', blocking=True),),
    )
    assert check_phases(series) == []


def test_phase_problems_are_part_of_the_structural_pass() -> None:
    series = _series(
        prs=(_phased('pr-1', 'core'),),
        checks=(Check(name='suite', run='true', blocking=True, phases=('nope',)),),
    )
    assert any(problem.kind == 'phases' for problem in structural_problems(series))


def test_pr_left_ungated_by_scoping_is_an_advisory() -> None:
    series = _series(
        prs=(_phased('pr-1', 'core'), _phased('pr-9', 'docs')),
        checks=(Check(name='suite', run='true', blocking=True, phases=('core',)),),
    )
    advisories = ungated_prs(series)
    assert len(advisories) == 1
    assert advisories[0].kind == 'gate'
    assert advisories[0].where == "[[prs]] 'pr-9'"
    assert 'docs' in advisories[0].message
    # Advice, never a problem: the series stays runnable.
    assert check_phases(series) == []


def test_a_covered_pr_raises_no_advisory() -> None:
    series = _series(
        prs=(_phased('pr-1', 'core'),),
        checks=(Check(name='suite', run='true', blocking=True, phases=('core',)),),
    )
    assert ungated_prs(series) == []


def test_a_non_blocking_check_does_not_count_as_a_gate() -> None:
    """A check that cannot stop a merge does not make a PR gated."""
    series = _series(
        prs=(_phased('pr-1', 'core'),),
        checks=(Check(name='lint', run='true', blocking=False),),
    )
    assert len(ungated_prs(series)) == 1


def test_a_series_with_no_checks_advises_every_pr() -> None:
    series = _series(prs=(_phased('pr-1', 'core'), _phased('pr-2', 'core')))
    assert len(ungated_prs(series)) == 2


# --- inert assets --------------------------------------------------------------------------
#
# `asset` is read in exactly one place: the fail-closed isolation guard, which runs only for
# a check that is BOTH blocking and independent. Anywhere else the parser accepts it,
# `dump_series` writes it back, and nothing reads it -- so the isolation the author thinks
# they bought is not being verified.


def _asset_check(
    name: str, *, blocking: bool, independent: bool, asset: str = '/tmp/o.py'
) -> Check:
    return Check(name=name, run='true', blocking=blocking, independent=independent, asset=asset)


def test_a_blocking_independent_asset_is_not_flagged() -> None:
    """The one shape that IS read. Flagging it would make the advisory noise."""
    series = _series(checks=(_asset_check('oracle', blocking=True, independent=True),))

    assert inert_assets(series) == []


def test_no_asset_is_not_flagged() -> None:
    series = _series(checks=(_asset_check('plain', blocking=False, independent=False, asset=''),))

    assert inert_assets(series) == []


@pytest.mark.parametrize(
    ('blocking', 'independent', 'expected'),
    [
        (True, False, 'not independent'),
        (False, True, 'not blocking'),
        (False, False, 'neither blocking nor independent'),
    ],
)
def test_an_inert_asset_names_which_flag_is_missing(
    blocking: bool, independent: bool, expected: str
) -> None:
    """Which flag to set is the whole actionable content; 'not independent' when it is
    also not blocking would send the author to fix half of it."""
    series = _series(checks=(_asset_check('oracle', blocking=blocking, independent=independent),))

    advisories = inert_assets(series)

    assert len(advisories) == 1
    assert advisories[0].kind == 'gate'
    assert advisories[0].where == "[[checks]] 'oracle'"
    assert expected in advisories[0].message


def test_an_inert_asset_never_becomes_a_problem() -> None:
    """The series is unusual, not invalid: the check still runs and still reports."""
    series = _series(checks=(_asset_check('oracle', blocking=False, independent=False),))

    assert structural_problems(series) == []
