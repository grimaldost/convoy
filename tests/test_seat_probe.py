"""Tests for the pre-run seat viability probe (interface/seat_probe.py)."""

from pathlib import Path

from convoy.core.spec import Budgets, Governance, Tools
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
    assert seat_problem(FakeSpawn([ok_result()]), _governance(), tmp_path) is None


def test_dead_seat_returns_a_located_problem_carrying_the_output(tmp_path: Path) -> None:
    spawn = FakeSpawn([_infra_result('claude: Not logged in - please run /login')])
    problem = seat_problem(spawn, _governance(), tmp_path)
    assert problem is not None
    assert problem.kind == 'seat'
    assert 'Not logged in' in problem.message
    assert 'claude-sonnet-5' in problem.message  # names the model that was probed


def test_probe_request_is_minimal_but_uses_the_run_model(tmp_path: Path) -> None:
    """The probe validates the seat AND the run's resolved model, spending near-zero."""
    spawn = FakeSpawn([ok_result()])
    seat_problem(spawn, _governance(), tmp_path)

    assert len(spawn.calls) == 1
    request, cwd = spawn.calls[0]
    assert isinstance(request, SpawnRequest)
    assert request.model == 'claude-sonnet-5'  # the governed model — probes real access
    assert request.tools == ()  # tool-less: nothing can touch the workspace
    assert 0 < request.budget_usd <= 0.05  # near-zero spend cap
    assert cwd == tmp_path


def test_budget_probe_result_is_not_a_seat_problem(tmp_path: Path) -> None:
    # A budget-classified probe still proves the seat answered; only infrastructure blocks.
    assert seat_problem(FakeSpawn([budget_result()]), _governance(), tmp_path) is None


def test_missing_agent_cli_is_a_seat_problem(tmp_path: Path) -> None:
    class _MissingBinarySpawn:
        def spawn(self, request: SpawnRequest, cwd: Path) -> SpawnResult:
            raise FileNotFoundError('claude executable not found')

    problem = seat_problem(_MissingBinarySpawn(), _governance(), tmp_path)
    assert problem is not None
    assert problem.kind == 'seat'
    assert 'not found' in problem.message
