"""CLI tests: ``convoy validate`` and the hardened ``convoy run``.

Uses typer's ``CliRunner``. ``run`` is exercised with ``run_series`` monkeypatched (patched
on the ``cli`` module, where it is imported), so no real agent spawns and no git is driven —
the tests assert the CLI's own behavior: pre-flight before any side effect, clean exit codes,
and mapping runtime errors to ``EXIT_USAGE`` instead of a traceback.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import convoy.interface.cli as cli
from convoy.core.governance import GovernanceError
from convoy.interface.drivers.headless import (
    EXIT_BLOCKED,
    EXIT_OK,
    EXIT_USAGE,
    RunOutcome,
)
from convoy.interface.git import GitError
from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.reporter import NullReporter, StderrReporter

runner = CliRunner()


def _series_toml(
    prompts: Path, outputs: Path, *, model: str = 'claude-haiku-4-5', tier: str = ''
) -> str:
    model_line = f'model = "{model}"' if model else ''
    tier_line = f'tier = "{tier}"' if tier else ''
    return f"""
[series]
id = "cli-test"
version = "1"
[branches]
base = "base"
integration = "integration"
[paths]
prompts = "{prompts.as_posix()}"
outputs = "{outputs.as_posix()}"
[governance]
{model_line}
{tier_line}
effort = "low"
permission_mode = "acceptEdits"
timeout_seconds = 60
[governance.budgets]
implementation = 0.5
review = 0.25
fix = 0.25
[governance.tools]
implementation = ["Read", "Write"]
review = ["Read"]
fix = ["Read", "Write"]
[review]
blocking = false
max_fix_attempts = 0
[[checks]]
name = "noop"
run = "python -c pass"
blocking = true
independent = false
[[prs]]
id = "pr-1"
branch = "pr-1"
prompt = "pr1.md"
phase = "core"
depends_on = []
"""


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A workspace to chdir into, an out-of-tree prompts dir, and an out-of-tree outputs dir."""
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    outputs = tmp_path / 'outputs'
    return workspace, prompts, outputs


# --- validate -----------------------------------------------------------------------------


def test_validate_ok_on_clean_series(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    result = runner.invoke(cli.app, ['validate', str(series_file)])
    assert result.exit_code == EXIT_OK
    assert 'ok' in result.output


def test_validate_reports_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    # No pr1.md written -> a prompt problem.
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    result = runner.invoke(cli.app, ['validate', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    assert 'problem(s) found' in result.output


def test_validate_bad_toml_is_usage(tmp_path: Path) -> None:
    series_file = tmp_path / 'bad.toml'
    series_file.write_text('this is = = not valid toml')
    result = runner.invoke(cli.app, ['validate', str(series_file)])
    assert result.exit_code == EXIT_USAGE


def test_validate_missing_file_is_usage(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ['validate', str(tmp_path / 'nope.toml')])
    assert result.exit_code == EXIT_USAGE


# --- run: pre-flight before side effects --------------------------------------------------


def test_run_aborts_before_running_when_a_problem_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    # Missing pr1.md -> pre-flight fails; run_series must never be called.
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    calls: list[object] = []
    monkeypatch.setattr(cli, 'run_series', lambda *a, **k: calls.append((a, k)))

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    assert calls == []


def test_run_unknown_tier_is_usage_not_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs, model='', tier='banana'))
    monkeypatch.chdir(workspace)

    called: list[object] = []
    monkeypatch.setattr(cli, 'run_series', lambda *a, **k: called.append(1))

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    assert result.exit_code != EXIT_BLOCKED
    assert called == []


def test_run_clean_series_reaches_run_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    called: list[object] = []

    def _fake_run_series(*_a: object, **_k: object) -> RunOutcome:
        called.append(1)
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(cli, 'run_series', _fake_run_series)

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_OK
    assert called == [1]


@pytest.mark.parametrize('exc', [GovernanceError, GitError, OSError])
def test_run_maps_runtime_error_to_usage(
    exc: type[Exception], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every runtime failure type the handler contracts to catch must map to EXIT_USAGE with a
    # message, not escape as a traceback (and not collide with EXIT_BLOCKED).
    series_file = _valid_run_setup(tmp_path, monkeypatch)

    def _boom(*_a: object, **_k: object) -> RunOutcome:
        raise exc('runtime failure')

    monkeypatch.setattr(cli, 'run_series', _boom)

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    assert 'Traceback' not in result.output


def test_run_outputs_mkdir_failure_maps_to_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An ANCESTOR of [paths].outputs is a regular file, so mkdir(parents=True) raises OSError.
    # Pre-flight passes (it only checks the final component), so this exercises run's own guard:
    # the failure must map to EXIT_USAGE before any run, never an uncaught traceback.
    workspace, prompts, _outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    afile = tmp_path / 'afile'
    afile.write_text('i am a file, not a directory')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, afile / 'sub' / 'out'))
    monkeypatch.chdir(workspace)

    called: list[object] = []
    monkeypatch.setattr(cli, 'run_series', lambda *a, **k: called.append(1))

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    assert 'Traceback' not in result.output
    assert called == []  # aborted before the run


# --- reporter selection -------------------------------------------------------------------


def test_select_reporter_quiet_is_null() -> None:
    assert isinstance(cli._select_reporter(quiet=True), NullReporter)


def test_select_reporter_default_narrates_to_stderr() -> None:
    assert isinstance(cli._select_reporter(quiet=False), StderrReporter)


# --- init (scaffold) end-to-end -----------------------------------------------------------


def test_init_then_validate_is_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / 'proj'
    assert runner.invoke(cli.app, ['init', str(root)]).exit_code == EXIT_OK
    # The scaffolded series must validate clean from its scored workspace.
    monkeypatch.chdir(root / 'workspace')
    validated = runner.invoke(cli.app, ['validate', str(root / 'series.toml')])
    assert validated.exit_code == EXIT_OK
    assert 'ok' in validated.output


def test_init_refuses_to_clobber_with_usage_exit(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    assert runner.invoke(cli.app, ['init', str(root)]).exit_code == EXIT_OK
    assert runner.invoke(cli.app, ['init', str(root)]).exit_code == EXIT_USAGE


# --- config isolation wiring --------------------------------------------------------------


@pytest.mark.parametrize(
    ('env', 'flag', 'expected'),
    [
        ({}, False, False),
        ({}, True, True),
        ({'CONVOY_NO_CONFIG_ISOLATION': '1'}, False, True),
        ({'CONVOY_NO_CONFIG_ISOLATION': 'true'}, False, True),
        ({'CONVOY_NO_CONFIG_ISOLATION': 'on'}, False, True),
        ({'CONVOY_NO_CONFIG_ISOLATION': 'no'}, False, False),
        ({'CONVOY_NO_CONFIG_ISOLATION': ''}, False, False),
    ],
)
def test_isolation_disabled_table(env: dict[str, str], flag: bool, expected: bool) -> None:
    assert cli._isolation_disabled(env, flag) is expected


def _valid_run_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A chdir'd workspace + a clean series file, ready for a monkeypatched `run`."""
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)
    return series_file


def test_run_uses_isolated_config_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series_file = _valid_run_setup(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def _fake(*_a: object, **k: object) -> RunOutcome:
        captured['spawn'] = k['spawn']
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(cli, 'run_series', _fake)

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_OK
    spawn = captured['spawn']
    assert isinstance(spawn, HeadlessSpawn)
    assert spawn._config_dir is not None  # a credential-only isolated dir was passed


def test_run_flag_opts_out_of_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    series_file = _valid_run_setup(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def _fake(*_a: object, **k: object) -> RunOutcome:
        captured['spawn'] = k['spawn']
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(cli, 'run_series', _fake)

    result = runner.invoke(cli.app, ['run', '--no-config-isolation', str(series_file)])
    assert result.exit_code == EXIT_OK
    spawn = captured['spawn']
    assert isinstance(spawn, HeadlessSpawn)
    assert spawn._config_dir is None  # inherits the operator config


def test_run_env_opts_out_of_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    series_file = _valid_run_setup(tmp_path, monkeypatch)
    monkeypatch.setenv('CONVOY_NO_CONFIG_ISOLATION', '1')
    captured: dict[str, object] = {}

    def _fake(*_a: object, **k: object) -> RunOutcome:
        captured['spawn'] = k['spawn']
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(cli, 'run_series', _fake)

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_OK
    spawn = captured['spawn']
    assert isinstance(spawn, HeadlessSpawn)
    assert spawn._config_dir is None


def test_isolated_config_is_cleaned_up_even_when_run_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series_file = _valid_run_setup(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def _boom(*_a: object, **k: object) -> RunOutcome:
        spawn = k['spawn']
        assert isinstance(spawn, HeadlessSpawn)
        captured['config_dir'] = spawn._config_dir
        raise GovernanceError('boom at runtime')

    monkeypatch.setattr(cli, 'run_series', _boom)

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    config_dir = captured['config_dir']
    assert isinstance(config_dir, Path)
    assert not config_dir.exists()  # the temp isolated dir was removed on exit
