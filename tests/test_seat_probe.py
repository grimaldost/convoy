"""Tests for the pre-run seat viability probe (interface/seat_probe.py)."""

from pathlib import Path

from convoy.core.spec import (
    PR,
    Branches,
    Budgets,
    Governance,
    Paths,
    Review,
    Series,
    Tools,
)
from convoy.interface.seat_probe import seat_problem
from convoy.interface.spawn import (
    FakeSpawn,
    SpawnEconomy,
    SpawnRequest,
    SpawnResult,
    budget_result,
    ok_result,
)


def _governance(model: str = 'claude-sonnet-5') -> Governance:
    return Governance(
        effort='high',
        permission_mode='acceptEdits',
        timeout_seconds=1800,
        budgets=Budgets(implementation=5.0, review=1.0, fix=2.0),
        tools=Tools(implementation=('Read', 'Edit'), review=(), fix=()),
        model=model,
    )


def _series(model: str = 'claude-sonnet-5', *, prs: tuple[PR, ...] | None = None) -> Series:
    """A one-model, one-PR series by default; ``prs`` overrides the PR list.

    The default PR inherits ``[governance]``, so a plain ``_series()`` probes exactly the
    series model — the pre-per-PR behaviour the five original probe tests pin.
    """
    if prs is None:
        prs = (PR(id='pr-1', branch='pr-1', prompt='pr-1.md', phase='p'),)
    return Series(
        id='s',
        version='1',
        branches=Branches(base='base', integration='integration'),
        paths=Paths(prompts='/tmp/p', outputs='/tmp/o'),
        governance=_governance(model),
        review=Review(blocking=False, max_fix_attempts=0),
        checks=(),
        prs=prs,
    )


def _infra_result(output: str) -> SpawnResult:
    return SpawnResult(
        exit_code=1,
        output=output,
        economy=SpawnEconomy(
            input_tokens=0,
            output_tokens=0,
            num_turns=0,
            duration_s=0.1,
            cost_usd=0.0,
            effective_model='claude-sonnet-5',
        ),
        classification='infrastructure',
    )


def test_healthy_seat_returns_no_problem(tmp_path: Path) -> None:
    assert seat_problem(FakeSpawn([ok_result()]), _series(), tmp_path) is None


def test_dead_seat_returns_a_located_problem_carrying_the_output(tmp_path: Path) -> None:
    spawn = FakeSpawn([_infra_result('claude: Not logged in - please run /login')])
    problem = seat_problem(spawn, _series(), tmp_path)
    assert problem is not None
    assert problem.kind == 'seat'
    assert 'Not logged in' in problem.message
    assert 'claude-sonnet-5' in problem.message  # names the model that was probed


def test_probe_request_is_minimal_but_uses_the_run_model(tmp_path: Path) -> None:
    """The probe validates the seat AND the run's resolved model, spending near-zero."""
    spawn = FakeSpawn([ok_result()])
    seat_problem(spawn, _series(), tmp_path)

    assert len(spawn.calls) == 1
    request, cwd = spawn.calls[0]
    assert isinstance(request, SpawnRequest)
    assert request.model == 'claude-sonnet-5'  # the governed model — probes real access
    assert request.tools == ()  # tool-less: nothing can touch the workspace
    assert 0 < request.budget_usd <= 0.05  # near-zero spend cap
    assert cwd == tmp_path


def test_budget_probe_result_is_not_a_seat_problem(tmp_path: Path) -> None:
    # A budget-classified probe still proves the seat answered; only infrastructure blocks.
    assert seat_problem(FakeSpawn([budget_result()]), _series(), tmp_path) is None


def test_missing_agent_cli_is_a_seat_problem(tmp_path: Path) -> None:
    class _MissingBinarySpawn:
        def spawn(self, request: SpawnRequest, cwd: Path) -> SpawnResult:
            raise FileNotFoundError('claude executable not found')

    problem = seat_problem(_MissingBinarySpawn(), _series(), tmp_path)
    assert problem is not None
    assert problem.kind == 'seat'
    assert 'not found' in problem.message


# --- coverage of the full model set a mixed-tier run can spawn on -------------


def test_probe_covers_every_distinct_per_pr_model(tmp_path: Path) -> None:
    """One probe per DISTINCT model, in first-PR-seen order — pins coverage and dedupe."""
    prs = (
        PR(id='a', branch='a', prompt='a.md', phase='p'),  # inherits the series model
        PR(id='b', branch='b', prompt='b.md', phase='p', model='claude-opus-4-8'),
        PR(id='c', branch='c', prompt='c.md', phase='p', model='claude-opus-4-8'),  # dupe
    )
    spawn = FakeSpawn([ok_result(), ok_result()])  # exactly two healthy probes

    assert seat_problem(spawn, _series('claude-haiku-4-5', prs=prs), tmp_path) is None
    # Two distinct models: the series model (pr-a) then opus (pr-b); pr-c's dupe adds nothing.
    assert [request.model for request, _cwd in spawn.calls] == [
        'claude-haiku-4-5',
        'claude-opus-4-8',
    ]


def test_probe_stops_at_the_first_dead_model(tmp_path: Path) -> None:
    """The first dead model returns a Problem; the rest are never probed (do not pay twice)."""
    prs = (
        PR(id='a', branch='a', prompt='a.md', phase='p'),  # series model — dies
        PR(id='b', branch='b', prompt='b.md', phase='p', model='claude-opus-4-8'),
    )
    # Only ONE result scripted: a second spawn would trip FakeSpawn's over-call assert.
    spawn = FakeSpawn([_infra_result('claude: Not logged in - please run /login')])

    problem = seat_problem(spawn, _series('claude-haiku-4-5', prs=prs), tmp_path)
    assert problem is not None
    assert 'claude-haiku-4-5' in problem.message
    assert len(spawn.calls) == 1  # the opus model was never reached


def test_series_with_no_prs_probes_the_series_model(tmp_path: Path) -> None:
    """A series naming no PRs still probes the [governance] model — no silent zero-probe hole."""
    spawn = FakeSpawn([ok_result()])
    assert seat_problem(spawn, _series('claude-sonnet-5', prs=()), tmp_path) is None
    assert [request.model for request, _cwd in spawn.calls] == ['claude-sonnet-5']


# --- the failing model is located at the section that declares it -------------


def test_dead_series_model_locates_the_problem_at_governance(tmp_path: Path) -> None:
    """A failing inherited/series model points the user at [governance], the section it lives in."""
    spawn = FakeSpawn([_infra_result('claude: Not logged in - please run /login')])
    problem = seat_problem(spawn, _series('claude-sonnet-5'), tmp_path)
    assert problem is not None
    assert problem.where == '[governance]'


def test_dead_per_pr_override_model_locates_the_problem_at_its_pr(tmp_path: Path) -> None:
    """A failing PER-PR override model points at that PR's [[prs]] table — not [governance].

    The old probe hard-coded ``where='[governance]'`` for every seat failure, so a
    per-PR override model that the seat could not serve sent the user to the wrong TOML
    section. The location now follows the model to the table that declares it.
    """
    prs = (
        PR(id='a', branch='a', prompt='a.md', phase='p'),  # series model — healthy
        PR(id='b', branch='b', prompt='b.md', phase='p', model='claude-opus-4-8'),  # dies
    )
    spawn = FakeSpawn([ok_result(), _infra_result('claude: Not logged in')])
    problem = seat_problem(spawn, _series('claude-haiku-4-5', prs=prs), tmp_path)
    assert problem is not None
    assert 'claude-opus-4-8' in problem.message  # still names the failing model
    assert problem.where == "[[prs]] 'b'"
