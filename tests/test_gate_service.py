"""Tests for the gate-only service: selection, execution, envelope, and refusals.

The service is the single fold both surfaces (CLI ``convoy gate`` and the MCP
``convoy_gate`` tool) consume, so what is pinned here is pinned for both: the
exit-code mapping, the envelope shape, and the fail-closed refusal of a vacuous
selection. Commands run for real against ``tmp_path`` under ``sys.executable``,
the same way the gate runner's own tests do.
"""

import sys
from pathlib import Path

import pytest

from convoy.core.spec import Check, GateSpec
from convoy.interface.drivers.headless import EXIT_BLOCKED, EXIT_OK
from convoy.interface.gate_runner import SubprocessGateRunner
from convoy.interface.gate_service import EmptySelectionError, gate_envelope, run_gate

_PY = sys.executable

_OK = f'"{_PY}" -c "exit(0)"'
_RED = f'"{_PY}" -c "import sys; sys.stderr.write(\'boom-marker\'); sys.exit(1)"'


def _spec(*checks: Check, timeout: int = 60) -> GateSpec:
    return GateSpec(id='svc-test', checks=checks, timeout_seconds=timeout)


def _check(
    name: str,
    run: str,
    *,
    blocking: bool = True,
    independent: bool = False,
    phases: tuple[str, ...] = (),
) -> Check:
    return Check(name=name, run=run, blocking=blocking, independent=independent, phases=phases)


# --- run_gate -----------------------------------------------------------------------------


def test_all_green_is_exit_ok(tmp_path: Path) -> None:
    outcome = run_gate(_spec(_check('a', _OK), _check('b', _OK)), tmp_path)
    assert outcome.exit_code == EXIT_OK
    assert outcome.verdict.blocking_red is False
    assert [r.check.name for r in outcome.verdict.results] == ['a', 'b']


def test_a_blocking_red_is_exit_blocked(tmp_path: Path) -> None:
    outcome = run_gate(_spec(_check('a', _OK), _check('bad', _RED)), tmp_path)
    assert outcome.exit_code == EXIT_BLOCKED
    assert outcome.verdict.blocking_red is True


def test_a_non_blocking_red_is_exit_ok(tmp_path: Path) -> None:
    """Advisory checks advise; only a blocking red blocks — same rule as the run."""
    outcome = run_gate(_spec(_check('advice', _RED, blocking=False)), tmp_path)
    assert outcome.exit_code == EXIT_OK
    assert outcome.verdict.blocking_red is False
    assert outcome.verdict.results[0].passed is False


def test_a_red_detail_carries_the_check_output(tmp_path: Path) -> None:
    outcome = run_gate(_spec(_check('bad', _RED)), tmp_path)
    assert 'boom-marker' in outcome.verdict.results[0].detail


def test_phase_selection_narrows_what_runs(tmp_path: Path) -> None:
    spec = _spec(
        _check('always', _OK),
        _check('core-only', _RED, phases=('core',)),
        _check('later-only', _RED, phases=('later',)),
    )
    outcome = run_gate(spec, tmp_path, phases=('later',))
    assert [r.check.name for r in outcome.verdict.results] == ['always', 'later-only']
    assert outcome.exit_code == EXIT_BLOCKED


def test_no_phases_runs_the_whole_gate(tmp_path: Path) -> None:
    spec = _spec(_check('a', _OK), _check('scoped', _OK, phases=('core',)))
    outcome = run_gate(spec, tmp_path)
    assert [r.check.name for r in outcome.verdict.results] == ['a', 'scoped']


def test_an_empty_selection_is_refused(tmp_path: Path) -> None:
    """Fail-closed: a green from zero checks is a vacuous assurance, not a verdict."""
    spec = _spec(_check('core-only', _OK, phases=('core',)))
    with pytest.raises(EmptySelectionError, match='selects no checks'):
        run_gate(spec, tmp_path, phases=('nope',))


def test_a_blocking_independent_check_without_isolation_fails_closed(tmp_path: Path) -> None:
    """The same isolation guard the run applies: an in-tree (or missing) asset never runs."""
    spec = _spec(
        _check('indep', _OK, independent=True),
    )
    outcome = run_gate(spec, tmp_path)
    assert outcome.exit_code == EXIT_BLOCKED
    assert outcome.verdict.results[0].passed is False


def test_the_spec_timeout_governs_the_run(tmp_path: Path) -> None:
    hang = f'"{_PY}" -c "import time; time.sleep(30)"'
    outcome = run_gate(_spec(_check('hang', hang, phases=()), timeout=1), tmp_path)
    assert outcome.exit_code == EXIT_BLOCKED
    assert 'timed out' in outcome.verdict.results[0].detail.lower()


# --- gate_envelope ------------------------------------------------------------------------


def test_envelope_shape_is_stable(tmp_path: Path) -> None:
    spec = _spec(_check('a', _OK), _check('bad', _RED, phases=('core',)))
    outcome = run_gate(spec, tmp_path, phases=('core',))
    envelope = gate_envelope(spec, tmp_path, ('core',), outcome)
    assert envelope == {
        'ok': False,
        'outcome': 'blocked',
        'series_id': 'svc-test',
        'workspace': str(tmp_path),
        'phases': ['core'],
        'checks': [
            {
                'name': 'a',
                'passed': True,
                'blocking': True,
                'independent': False,
                'phases': [],
                'detail': '',
            },
            {
                'name': 'bad',
                'passed': False,
                'blocking': True,
                'independent': False,
                'phases': ['core'],
                'detail': envelope['checks'][1]['detail'],
            },
        ],
        'blocking_red': True,
        'independent_red': False,
        'counts': {'selected': 2, 'passed': 1, 'failed': 1},
        'exit_code': EXIT_BLOCKED,
    }
    assert 'boom-marker' in envelope['checks'][1]['detail']


def test_envelope_green_outcome_word(tmp_path: Path) -> None:
    spec = _spec(_check('a', _OK))
    outcome = run_gate(spec, tmp_path)
    envelope = gate_envelope(spec, tmp_path, (), outcome)
    assert envelope['ok'] is True
    assert envelope['outcome'] == 'completed'
    assert envelope['exit_code'] == EXIT_OK


def test_the_default_timeout_matches_the_runner_signature() -> None:
    """The comment in spec.py claims the two cannot drift; this is the pin behind it."""
    import inspect

    from convoy.core.spec import DEFAULT_GATE_TIMEOUT_SECONDS

    default = inspect.signature(SubprocessGateRunner.__init__).parameters['timeout_seconds']
    assert default.default == float(DEFAULT_GATE_TIMEOUT_SECONDS)
