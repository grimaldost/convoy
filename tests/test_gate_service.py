"""Tests for the gate-only service: selection, execution, envelope, and refusals.

The service is the single fold both surfaces (CLI ``convoy gate`` and the MCP
``convoy_gate`` tool) consume, so what is pinned here is pinned for both: the
exit-code mapping, the envelope shape, and the fail-closed refusal of a vacuous
selection. Commands run for real against ``tmp_path`` under ``sys.executable``,
the same way the gate runner's own tests do.
"""

import os
import sys
from pathlib import Path

import pytest

from convoy import __version__
from convoy.core.gate import (
    AdvisoryOnlySelectionError,
    EmptySelectionError,
    IsolationRefusedError,
    UnknownPhaseError,
    repair_brief,
)
from convoy.core.spec import Check, GateSpec, SpecError
from convoy.interface.drivers.headless import EXIT_BLOCKED, EXIT_OK
from convoy.interface.gate_runner import SubprocessGateRunner
from convoy.interface.gate_service import (
    GateSpecNotFoundError,
    convoy_home,
    find_gate_spec,
    gate_brief_envelope,
    gate_envelope,
    gate_root,
    gate_spec_env,
    gate_usage_envelope,
    is_trusted,
    resolve_gate_spec,
    run_gate,
    trust_project,
    trusted_projects,
)

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
    outcome = run_gate(_spec(_check('a', _OK), _check('advice', _RED, blocking=False)), tmp_path)
    assert outcome.exit_code == EXIT_OK
    assert outcome.verdict.blocking_red is False
    assert outcome.verdict.results[1].passed is False


def test_selected_carries_the_selection_in_order(tmp_path: Path) -> None:
    a, b = _check('a', _OK), _check('b', _OK, phases=('core',))
    outcome = run_gate(_spec(a, b), tmp_path)
    assert outcome.selected == (a, b)
    assert outcome.phases == ()


def test_an_advisory_only_selection_is_refused(tmp_path: Path) -> None:
    """Nothing selected can say no — `completed` would assure nothing, so it is refused."""
    spec = _spec(_check('advice', _OK, blocking=False))
    with pytest.raises(AdvisoryOnlySelectionError, match='no blocking check'):
        run_gate(spec, tmp_path)


def test_an_unknown_phase_tag_is_refused(tmp_path: Path) -> None:
    """A typo'd tag must not silently narrow the gate to the unscoped checks and go green."""
    spec = _spec(_check('always', _OK), _check('scoped', _RED, phases=('core',)))
    with pytest.raises(UnknownPhaseError, match="'cores'"):
        run_gate(spec, tmp_path, phases=('cores',))


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
    """The fail-closed backstop for a directly constructed spec the loader would refuse."""
    spec = GateSpec(id='empty', checks=(), timeout_seconds=60)
    with pytest.raises(EmptySelectionError, match='vacuous'):
        run_gate(spec, tmp_path)


def test_unbacked_isolation_is_a_usage_refusal_not_a_red(tmp_path: Path) -> None:
    """The run reports this identical spec defect at pre-flight as usage; so does gate-only.

    Classifying it as a red would set ``independent_red`` — the signal an auto-repair
    loop keys on — for a misconfiguration no repair can fix.
    """
    spec = _spec(_check('indep', _OK, independent=True))
    with pytest.raises(IsolationRefusedError, match="'indep'"):
        run_gate(spec, tmp_path)


def test_the_spec_timeout_governs_the_run(tmp_path: Path) -> None:
    hang = f'"{_PY}" -c "import time; time.sleep(30)"'
    outcome = run_gate(_spec(_check('hang', hang, phases=()), timeout=1), tmp_path)
    assert outcome.exit_code == EXIT_BLOCKED
    assert 'timed out' in outcome.verdict.results[0].detail.lower()


# --- gate_envelope ------------------------------------------------------------------------


def test_envelope_shape_is_stable(tmp_path: Path) -> None:
    """Every key and its value, except the two a machine's own output decides.

    ``repair_brief`` is popped rather than compared against itself: its value belongs to
    ``test_envelope_repair_brief_is_the_run_s_own_fix_section``, and an entry that reads
    the envelope back is true by construction, so it would pin the key's presence while
    letting any value regression through. The pop still fails loudly if the key is gone.
    """
    spec = _spec(
        _check('a', _OK),
        _check('bad', _RED, phases=('core',)),
        _check('later-only', _OK, phases=('later',)),
    )
    outcome = run_gate(spec, tmp_path, phases=('core',))
    envelope = gate_envelope(spec, tmp_path, outcome)
    brief = envelope.pop('repair_brief')
    assert envelope == {
        'ok': False,
        'outcome': 'blocked',
        'series_id': 'svc-test',
        'workspace': str(tmp_path.resolve()),
        'phases': ['core'],
        'checks': [
            {
                'name': 'a',
                'passed': True,
                'blocking': True,
                'independent': False,
                'phases': [],
                'exit_code': 0,
                'timed_out': False,
                'detail': '',
            },
            {
                'name': 'bad',
                'passed': False,
                'blocking': True,
                'independent': False,
                'phases': ['core'],
                'exit_code': 1,
                'timed_out': False,
                'detail': envelope['checks'][1]['detail'],
            },
        ],
        'blocking_red': True,
        'independent_red': False,
        'counts': {'total': 3, 'selected': 2, 'passed': 1, 'failed': 1},
        'advisories': [],
        'truncated': {'any': False, 'checks': 0},
        'exit_code': EXIT_BLOCKED,
        'convoy_version': __version__,
    }
    assert 'boom-marker' in envelope['checks'][1]['detail']
    assert brief.startswith('## Failing checks to repair')
    assert 'bad' in brief


def test_envelope_repair_brief_is_empty_on_a_green_gate(tmp_path: Path) -> None:
    """Nothing blocking failed, so there is nothing to brief a repair with."""
    spec = _spec(_check('a', _OK))
    envelope = gate_envelope(spec, tmp_path, run_gate(spec, tmp_path))
    assert envelope['repair_brief'] == ''


def test_envelope_repair_brief_is_the_run_s_own_fix_section(tmp_path: Path) -> None:
    """The envelope hands out exactly the section the run's fix loop briefs a repair with."""
    spec = _spec(_check('bad', _RED))
    outcome = run_gate(spec, tmp_path)
    envelope = gate_envelope(spec, tmp_path, outcome)
    assert envelope['repair_brief'] == repair_brief(outcome.verdict)


def test_envelope_green_outcome_word(tmp_path: Path) -> None:
    spec = _spec(_check('a', _OK))
    outcome = run_gate(spec, tmp_path)
    envelope = gate_envelope(spec, tmp_path, outcome)
    assert envelope['ok'] is True
    assert envelope['outcome'] == 'completed'
    assert envelope['exit_code'] == EXIT_OK


def test_envelope_workspace_is_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative workspace means nothing outside the invoking shell — resolve it."""
    monkeypatch.chdir(tmp_path)
    spec = _spec(_check('a', _OK))
    envelope = gate_envelope(spec, Path('.'), run_gate(spec, Path('.')))
    assert envelope['workspace'] == str(tmp_path.resolve())


def test_a_timed_out_check_reports_structured_fields(tmp_path: Path) -> None:
    hang = f'"{_PY}" -c "import time; time.sleep(30)"'
    outcome = run_gate(_spec(_check('hang', hang), timeout=1), tmp_path)
    envelope = gate_envelope(_spec(_check('hang', hang), timeout=1), tmp_path, outcome)
    entry = envelope['checks'][0]
    assert entry['timed_out'] is True
    assert entry['exit_code'] is None


def test_the_check_list_is_capped_with_a_truncation_report(tmp_path: Path) -> None:
    """No silent drop: past the cap the count of omitted checks is reported."""
    from convoy.interface import gate_service

    checks = tuple(_check(f'c{i}', _OK) for i in range(gate_service._CHECK_CAP + 3))
    spec = GateSpec(id='many', checks=checks, timeout_seconds=60)
    envelope = gate_envelope(spec, tmp_path, run_gate(spec, tmp_path))
    assert len(envelope['checks']) == gate_service._CHECK_CAP
    assert envelope['truncated'] == {'any': True, 'checks': 3}
    assert envelope['counts']['selected'] == gate_service._CHECK_CAP + 3


def test_the_usage_envelope_carries_the_documented_exit_code() -> None:
    envelope = gate_usage_envelope(ValueError('nope'), error_kind='spec', series_id='s')
    assert envelope == {
        'ok': False,
        'outcome': 'usage',
        'error_kind': 'spec',
        'error': 'nope',
        'exit_code': 3,
        'series_id': 's',
    }
    assert 'series_id' not in gate_usage_envelope(ValueError('x'), error_kind='spec')


def test_gate_usage_errors_classify_as_spec_not_filesystem() -> None:
    """`error_kind` once mislabeled these as 'filesystem' via its OSError catch-all."""
    from convoy.interface.run_summary import error_kind

    for exc in (
        EmptySelectionError('x'),
        UnknownPhaseError('x'),
        AdvisoryOnlySelectionError('x'),
        IsolationRefusedError('x'),
    ):
        assert error_kind(exc) == 'spec'


def test_the_default_timeout_matches_the_runner_signature() -> None:
    """The comment in spec.py claims the two cannot drift; this is the pin behind it."""
    import inspect

    from convoy.core.spec import DEFAULT_GATE_TIMEOUT_SECONDS

    default = inspect.signature(SubprocessGateRunner.__init__).parameters['timeout_seconds']
    assert default.default == float(DEFAULT_GATE_TIMEOUT_SECONDS)


# --- project spec discovery, the oracles default, and the brief envelope ---------------


def _project_with_spec(root: Path) -> Path:
    (root / '.convoy').mkdir(parents=True)
    spec = root / '.convoy' / 'gate.toml'
    spec.write_text('', encoding='utf-8')
    return spec


def test_find_gate_spec_prefers_the_project_dir_from_the_environment(tmp_path: Path) -> None:
    project_spec = _project_with_spec(tmp_path / 'project')
    _project_with_spec(tmp_path / 'elsewhere')
    env = {'CLAUDE_PROJECT_DIR': str(tmp_path / 'project')}
    assert find_gate_spec(tmp_path / 'elsewhere', env) == project_spec


def test_find_gate_spec_walks_up_from_the_start_directory(tmp_path: Path) -> None:
    spec = _project_with_spec(tmp_path / 'repo')
    nested = tmp_path / 'repo' / 'src' / 'pkg'
    nested.mkdir(parents=True)
    assert find_gate_spec(nested, {}) == spec


def test_find_gate_spec_falls_through_a_project_dir_without_a_spec(tmp_path: Path) -> None:
    spec = _project_with_spec(tmp_path / 'repo')
    (tmp_path / 'bare').mkdir()
    env = {'CLAUDE_PROJECT_DIR': str(tmp_path / 'bare')}
    assert find_gate_spec(tmp_path / 'repo', env) == spec


def test_find_gate_spec_returns_none_when_nothing_is_found(tmp_path: Path) -> None:
    (tmp_path / 'empty').mkdir()
    assert find_gate_spec(tmp_path / 'empty', {}) is None


def test_resolve_gate_spec_keeps_an_explicit_series_file(tmp_path: Path) -> None:
    _project_with_spec(tmp_path)
    explicit = tmp_path / 'series.toml'
    assert resolve_gate_spec(explicit, tmp_path, {}) == explicit


def test_resolve_gate_spec_refuses_when_nothing_is_found(tmp_path: Path) -> None:
    (tmp_path / 'empty').mkdir()
    with pytest.raises(GateSpecNotFoundError) as excinfo:
        resolve_gate_spec(None, tmp_path / 'empty', {})
    message = str(excinfo.value)
    assert 'gate.toml' in message
    assert 'CLAUDE_PROJECT_DIR' in message


def test_gate_spec_env_defaults_the_oracles_dir_for_a_project_spec(tmp_path: Path) -> None:
    spec = tmp_path / 'proj' / '.convoy' / 'gate.toml'
    env = gate_spec_env(spec, {'PATH': 'x', 'CONVOY_HOME': str(tmp_path / 'home')})
    assert env['CONVOY_ORACLES'] == str(tmp_path / 'home' / 'oracles' / 'proj')
    assert env['PATH'] == 'x'


def test_gate_spec_env_keeps_an_explicit_oracles_dir(tmp_path: Path) -> None:
    spec = tmp_path / 'proj' / '.convoy' / 'gate.toml'
    env = gate_spec_env(spec, {'CONVOY_ORACLES': '/mine', 'CONVOY_HOME': str(tmp_path)})
    assert env['CONVOY_ORACLES'] == '/mine'


def test_gate_spec_env_injects_no_default_for_an_explicit_series_file(tmp_path: Path) -> None:
    env = gate_spec_env(tmp_path / 'proj' / 'series.toml', {'CONVOY_HOME': str(tmp_path)})
    assert 'CONVOY_ORACLES' not in env


def test_gate_brief_envelope_carries_exactly_four_fields(tmp_path: Path) -> None:
    outcome = run_gate(_spec(_check('ok', _OK)), tmp_path)
    assert gate_brief_envelope(outcome) == {
        'ok': True,
        'outcome': 'completed',
        'repair_brief': '',
        'convoy_version': __version__,
    }


def test_gate_brief_envelope_agrees_with_the_full_envelope_on_red(tmp_path: Path) -> None:
    spec = _spec(_check('bad', _RED))
    outcome = run_gate(spec, tmp_path)
    full = gate_envelope(spec, tmp_path, outcome)
    brief = gate_brief_envelope(outcome)
    assert brief['ok'] is False
    assert brief['outcome'] == 'blocked'
    assert brief['repair_brief'] == full['repair_brief']
    assert 'bad' in brief['repair_brief']


# --- the hook trust list ---------------------------------------------------------------------


def test_convoy_home_defaults_to_the_dot_convoy_dir_under_home() -> None:
    assert convoy_home({}) == Path.home() / '.convoy'
    assert convoy_home({'CONVOY_HOME': '/elsewhere'}) == Path('/elsewhere')


def test_trust_list_is_empty_until_written(tmp_path: Path) -> None:
    env = {'CONVOY_HOME': str(tmp_path / 'home')}
    assert trusted_projects(env) == ()
    assert is_trusted(tmp_path / 'proj', env) is False


def test_trust_project_writes_resolves_and_is_idempotent(tmp_path: Path) -> None:
    env = {'CONVOY_HOME': str(tmp_path / 'home')}
    project = tmp_path / 'proj'
    project.mkdir()
    path = trust_project(project, env)
    assert path == tmp_path / 'home' / 'hook-trust.toml'
    trust_project(project / '..' / 'proj', env)
    assert len(trusted_projects(env)) == 1
    assert is_trusted(project, env) is True
    assert is_trusted(tmp_path / 'other', env) is False


def test_a_malformed_trust_list_is_a_spec_error(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    home.mkdir()
    env = {'CONVOY_HOME': str(home)}
    (home / 'hook-trust.toml').write_text('[trust]\nprojects = "not-a-list"\n', encoding='utf-8')
    with pytest.raises(SpecError, match='list of strings'):
        trusted_projects(env)
    with pytest.raises(SpecError):
        trust_project(tmp_path / 'proj', env)


def test_the_launching_process_can_vouch_for_roots(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    project = tmp_path / 'staged'
    project.mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    env = {
        'CONVOY_HOME': str(home),
        'CONVOY_TRUSTED_ROOTS': os.pathsep.join([str(other), str(project / '..' / 'staged')]),
    }
    assert is_trusted(project, env) is True
    assert is_trusted(other, env) is True
    assert is_trusted(tmp_path / 'else', env) is False
    assert trusted_projects(env) == ()


# --- $CONVOY_GATE_SPEC: an explicit spec, rooted at the workspace ---------------------------


def test_convoy_gate_spec_wins_over_discovery(tmp_path: Path) -> None:
    project_spec = _project_with_spec(tmp_path / 'repo')
    named = tmp_path / 'elsewhere' / 'gate.toml'
    named.parent.mkdir()
    named.write_text('', encoding='utf-8')
    env = {'CONVOY_GATE_SPEC': str(named), 'CLAUDE_PROJECT_DIR': str(tmp_path / 'repo')}
    assert find_gate_spec(tmp_path / 'repo', env) == named
    assert find_gate_spec(tmp_path / 'repo', {}) == project_spec


def test_a_missing_convoy_gate_spec_is_refused_not_walked_past(tmp_path: Path) -> None:
    _project_with_spec(tmp_path / 'repo')
    with pytest.raises(GateSpecNotFoundError, match='CONVOY_GATE_SPEC'):
        find_gate_spec(tmp_path / 'repo', {'CONVOY_GATE_SPEC': str(tmp_path / 'nope.toml')})


def test_gate_root_is_the_workspace_for_a_spec_outside_dot_convoy(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    assert gate_root(tmp_path / 'task' / 'gate.toml', workspace) == workspace.resolve()
    assert gate_root(tmp_path / 'repo' / '.convoy' / 'gate.toml', workspace) == tmp_path / 'repo'


def test_gate_spec_env_defaults_oracles_for_a_named_root(tmp_path: Path) -> None:
    env = {'CONVOY_HOME': str(tmp_path / 'home')}
    resolved = gate_spec_env(tmp_path / 'task' / 'gate.toml', env, root=tmp_path / 'ws')
    assert resolved['CONVOY_ORACLES'] == str(tmp_path / 'home' / 'oracles' / 'ws')
