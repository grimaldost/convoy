"""Tests for the pure structural pre-flight (core/preflight.py)."""

from convoy.core.preflight import check_dag, check_governance, structural_problems
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
