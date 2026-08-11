"""CLI tests: ``convoy validate``, the hardened ``convoy run``, and ``convoy clean``.

Uses typer's ``CliRunner``. ``run`` is exercised with ``run_series`` monkeypatched (patched
on the ``cli`` module, where it is imported), so no real agent spawns and no git is driven —
the tests assert the CLI's own behavior: pre-flight before any side effect, clean exit codes,
and mapping runtime errors to ``EXIT_USAGE`` instead of a traceback.

``clean`` is the exception: it is exercised against a REAL temp git repo, because the whole
point of the verb is what it does to a dirty working tree, which a stubbed ``Git`` cannot
demonstrate. It drives git only — never a spawn.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import convoy.interface.cli as cli
from convoy.core.governance import GovernanceError
from convoy.interface.drivers.headless import (
    EXIT_BLOCKED,
    EXIT_BUDGET,
    EXIT_INFRASTRUCTURE,
    EXIT_OK,
    EXIT_USAGE,
    RunOutcome,
)
from convoy.interface.git import Git, GitError
from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.reporter import NullReporter, StderrReporter
from convoy.interface.run_summary import summarize_run
from convoy.interface.workspace_lock import lock_path

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


def test_validate_rejects_a_phase_tag_no_pr_declares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo'd phase would silently gate nothing, so it fails loud — a Problem, not advice."""
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(
        _series_toml(prompts, outputs).replace('blocking = true', 'blocking = true\nphases = ["x"]')
    )
    monkeypatch.chdir(workspace)

    result = runner.invoke(cli.app, ['validate', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    assert 'problem(s) found' in result.output
    assert 'phases' in result.output


def test_validate_advisory_on_a_pr_no_check_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    (prompts / 'pr2.md').write_text('docs only')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(
        _series_toml(prompts, outputs)
        # Scope the blocking check to 'core', then add a second PR in a 'docs' phase that
        # nothing gates. Both phases are declared, so there is no phases problem.
        .replace('blocking = true', 'blocking = true\nphases = ["core"]')
        + """
[[prs]]
id = "pr-2"
branch = "pr-2"
prompt = "pr2.md"
phase = "docs"
depends_on = []
"""
    )
    monkeypatch.chdir(workspace)

    result = runner.invoke(cli.app, ['validate', str(series_file)])
    assert result.exit_code == EXIT_OK
    assert 'advisory(ies)' in result.output
    assert 'pr-2' in result.output
    assert 'ok' in result.output


def test_validate_bad_toml_is_usage(tmp_path: Path) -> None:
    series_file = tmp_path / 'bad.toml'
    series_file.write_text('this is = = not valid toml')
    result = runner.invoke(cli.app, ['validate', str(series_file)])
    assert result.exit_code == EXIT_USAGE


def test_validate_ok_on_series_with_non_ascii_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A UTF-8 series file with non-ASCII text validates under any platform locale.

    'ѐ' (bytes D1 90) is undecodable under cp1252, so the unpinned read raised
    ``UnicodeDecodeError`` on Windows instead of parsing the series.
    """
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    non_ascii = _series_toml(prompts, outputs).replace('id = "cli-test"', 'id = "cli-tëst ✓ ѐ"')
    series_file.write_text(non_ascii, encoding='utf-8')
    monkeypatch.chdir(workspace)

    result = runner.invoke(cli.app, ['validate', str(series_file)])
    assert result.exit_code == EXIT_OK
    assert 'ok' in result.output


def test_validate_non_utf8_series_file_is_usage_not_a_traceback(tmp_path: Path) -> None:
    """A series file that is not valid UTF-8 exits ``EXIT_USAGE`` with a message.

    With the read pinned to UTF-8, a legacy-encoded file must surface as a located
    usage error like malformed TOML does — never as an uncaught ``UnicodeDecodeError``.
    """
    series_file = tmp_path / 'latin.toml'
    series_file.write_bytes('id = "café"\n'.encode('cp1252'))

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
    monkeypatch.setattr(
        'convoy.interface.run_service.run_series', lambda *a, **k: calls.append((a, k))
    )

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
    monkeypatch.setattr('convoy.interface.run_service.run_series', lambda *a, **k: called.append(1))

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

    monkeypatch.setattr('convoy.interface.run_service.run_series', _fake_run_series)

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

    monkeypatch.setattr('convoy.interface.run_service.run_series', _boom)

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
    monkeypatch.setattr('convoy.interface.run_service.run_series', lambda *a, **k: called.append(1))

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

    monkeypatch.setattr('convoy.interface.run_service.run_series', _fake)

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

    monkeypatch.setattr('convoy.interface.run_service.run_series', _fake)

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

    monkeypatch.setattr('convoy.interface.run_service.run_series', _fake)

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

    monkeypatch.setattr('convoy.interface.run_service.run_series', _boom)

    result = runner.invoke(cli.app, ['run', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    config_dir = captured['config_dir']
    assert isinstance(config_dir, Path)
    assert not config_dir.exists()  # the temp isolated dir was removed on exit


# --- --workspace --------------------------------------------------------------------------
#
# Before this option the workspace was implicitly the process cwd, which is not discoverable
# from `--help` and bit four separate campaigns. The default is unchanged; the flag makes the
# coupling explicit and lets validate/run target a tree the shell is not sitting in.


def test_validate_defaults_the_workspace_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No --workspace behaves exactly as before the option existed."""
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    result = runner.invoke(cli.app, ['validate', str(series_file)])
    assert result.exit_code == EXIT_OK


def test_validate_accepts_an_explicit_workspace_from_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check that keys on the workspace (outputs out-of-tree) follows --workspace, not cwd."""
    workspace, prompts, _ = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    # outputs lives INSIDE the explicit workspace, which is the one thing preflight rejects.
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, workspace / 'out'))
    # Sit somewhere else entirely, so a cwd-based workspace would NOT see the violation.
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    # Without the flag the cwd is the workspace and outputs is out-of-tree => clean.
    assert runner.invoke(cli.app, ['validate', str(series_file)]).exit_code == EXIT_OK
    # With it, the real workspace is probed and the violation surfaces.
    result = runner.invoke(cli.app, ['validate', str(series_file), '--workspace', str(workspace)])
    assert result.exit_code == EXIT_USAGE
    assert 'inside the scored workspace' in result.output


def test_workspace_short_flag_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ['validate', str(series_file), '-w', str(workspace)])
    assert result.exit_code == EXIT_OK


def test_a_missing_workspace_is_a_usage_error_not_a_confusing_later_failure(
    tmp_path: Path,
) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))

    result = runner.invoke(
        cli.app, ['validate', str(series_file), '--workspace', str(tmp_path / 'nope')]
    )
    assert result.exit_code == EXIT_USAGE
    assert 'not an existing directory' in result.output


def test_a_file_as_workspace_is_rejected(tmp_path: Path) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))

    result = runner.invoke(cli.app, ['validate', str(series_file), '--workspace', str(series_file)])
    assert result.exit_code == EXIT_USAGE
    assert 'not an existing directory' in result.output


def test_run_passes_the_explicit_workspace_through_to_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run --workspace` must reach run_series, not just pass pre-flight.

    The engine takes the workspace as its second positional argument; asserting on the
    recorded call is what proves the flag is threaded rather than merely accepted.
    """
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    seen: list[Path] = []

    def _fake_run_series(_series: object, ws: Path, **_k: object) -> RunOutcome:
        seen.append(ws)
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr('convoy.interface.run_service.run_series', _fake_run_series)

    result = runner.invoke(cli.app, ['run', str(series_file), '--workspace', str(workspace)])
    assert result.exit_code == EXIT_OK
    assert seen == [workspace]
    assert seen != [elsewhere]  # the cwd, which is what it would have been before


def test_run_threads_resume_through_to_the_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    seen: dict[str, object] = {}

    def _fake(*_a: object, **k: object) -> RunOutcome:
        seen.update(k)
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(cli, 'run_series_headless', _fake)

    assert runner.invoke(cli.app, ['run', str(series_file), '--resume']).exit_code == EXIT_OK
    assert seen['resume'] is True
    assert seen['fresh'] is False

    seen.clear()
    assert runner.invoke(cli.app, ['run', str(series_file)]).exit_code == EXIT_OK
    assert seen['resume'] is False


def test_run_without_the_flag_still_uses_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    seen: list[Path] = []

    def _fake_run_series(_series: object, ws: Path, **_k: object) -> RunOutcome:
        seen.append(ws)
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr('convoy.interface.run_service.run_series', _fake_run_series)

    assert runner.invoke(cli.app, ['run', str(series_file)]).exit_code == EXIT_OK
    assert seen == [Path.cwd()]


# --- clean --------------------------------------------------------------------------------
#
# The recovery path after a halted or killed run. Exercised against a REAL git repo: the
# whole value of the verb is what it does to a dirty tree, which a mocked Git cannot show.


def _repo_with_series(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A git repo on `base` with a committed seed, plus a series naming pr-1/integration."""
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    outputs = tmp_path / 'outputs'

    def _git(*args: str) -> None:
        subprocess.run(['git', *args], cwd=workspace, check=True, capture_output=True, text=True)

    _git('init', '-b', 'base')
    _git('config', 'user.email', 'test@example.com')
    _git('config', 'user.name', 'Test')
    (workspace / 'README.md').write_text('seed\n')
    _git('add', '-A')
    _git('commit', '-m', 'seed')

    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    return workspace, series_file, prompts


def test_clean_dry_run_changes_nothing(tmp_path: Path) -> None:
    workspace, series_file, _ = _repo_with_series(tmp_path)
    (workspace / 'README.md').write_text('modified\n')
    (workspace / 'debris.txt').write_text('left by a killed run\n')

    result = runner.invoke(
        cli.app, ['clean', str(series_file), '--workspace', str(workspace), '--dry-run']
    )
    assert result.exit_code == EXIT_OK
    assert 'would clean' in result.output
    assert 'debris.txt' in result.output
    # Nothing was actually touched.
    assert (workspace / 'debris.txt').exists()
    assert (workspace / 'README.md').read_text() == 'modified\n'


def test_clean_discards_tracked_changes_and_untracked_debris(tmp_path: Path) -> None:
    workspace, series_file, _ = _repo_with_series(tmp_path)
    (workspace / 'README.md').write_text('modified\n')
    (workspace / 'debris.txt').write_text('left by a killed run\n')
    (workspace / 'subdir').mkdir()
    (workspace / 'subdir' / 'more.txt').write_text('nested debris\n')

    result = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    assert result.exit_code == EXIT_OK
    assert (workspace / 'README.md').read_text() == 'seed\n'
    assert not (workspace / 'debris.txt').exists()
    assert not (workspace / 'subdir').exists()


def test_clean_deletes_the_series_branches_and_returns_to_base(tmp_path: Path) -> None:
    workspace, series_file, _ = _repo_with_series(tmp_path)
    git = Git(workspace)
    git.checkout('integration', create=True)
    git.checkout('pr-1', create=True)
    assert git.current_branch() == 'pr-1'

    result = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    assert result.exit_code == EXIT_OK
    assert git.current_branch() == 'base'
    assert not git.branch_exists('integration')
    assert not git.branch_exists('pr-1')


def test_clean_removes_a_stale_run_lock(tmp_path: Path) -> None:
    """The case --fresh cannot serve: --fresh acquires the lock before it resets anything."""
    workspace, series_file, _ = _repo_with_series(tmp_path)
    stale = lock_path(workspace)
    stale.write_text('99999')
    assert stale.exists()

    result = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    assert result.exit_code == EXIT_OK
    assert not stale.exists()
    assert 'removed the run lock' in result.output


def test_clean_closes_the_killed_runs_ledger_entry(tmp_path: Path) -> None:
    """Clearing the lock is the last moment the abandonment is establishable — so record it.

    A pid is reusable once its process is gone, so a live check asked tomorrow cannot answer
    for a run that died today. Without the line the entry reads ``running`` for ever.
    """
    workspace, series_file, _ = _repo_with_series(tmp_path)
    outputs = tmp_path / 'outputs'
    _unfinished_ledger(outputs)
    lock_path(workspace).write_text('99999')

    result = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    assert result.exit_code == EXIT_OK
    assert 'recorded run r1 as abandoned' in result.output

    written = [json.loads(line) for line in (outputs / 'spawns.jsonl').read_text().splitlines()]
    assert written[-1]['event'] == 'run_abandoned'
    assert written[-1]['run_id'] == 'r1'
    assert written[-1]['reason']
    # Append-only: nothing before it moved.
    assert [entry['event'] for entry in written[:-1]] == ['run_start', 'spawn_complete']


def test_a_run_closed_by_clean_reads_finished_and_abandoned(tmp_path: Path) -> None:
    """The whole point of the line: status stops answering ``running`` for a dead run."""
    workspace, series_file, _ = _repo_with_series(tmp_path)
    outputs = tmp_path / 'outputs'
    _unfinished_ledger(outputs)
    lock_path(workspace).write_text('99999')
    runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])

    result = runner.invoke(cli.app, ['status', str(series_file), '--json'])
    payload = json.loads(result.stdout.strip())

    assert payload['state'] == 'finished'
    assert payload['outcome'] == 'abandoned'
    assert payload['integrated'] is False
    assert payload['ok'] is False
    # Same exit code an infrastructure halt carries: outside the work, and re-runnable.
    assert payload['exit_code'] == EXIT_INFRASTRUCTURE


def test_clean_records_nothing_when_the_latest_run_already_finished(tmp_path: Path) -> None:
    workspace, series_file, _ = _repo_with_series(tmp_path)
    outputs = tmp_path / 'outputs'
    _ledger(
        outputs,
        [
            {'schema_version': 1, 'event': 'run_start', 'run_id': 'r1', 'series_id': 'cli-test'},
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': 'r1',
                'outcome': 'completed',
                'integrated': True,
                'halt': None,
            },
        ],
    )
    lock_path(workspace).write_text('99999')

    result = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    assert 'abandoned' not in result.output

    events = [
        json.loads(line)['event'] for line in (outputs / 'spawns.jsonl').read_text().splitlines()
    ]
    assert events == ['run_start', 'run_complete']


def test_clean_dry_run_names_the_abandonment_and_writes_nothing(tmp_path: Path) -> None:
    workspace, series_file, _ = _repo_with_series(tmp_path)
    outputs = tmp_path / 'outputs'
    _unfinished_ledger(outputs)
    before = (outputs / 'spawns.jsonl').read_text()
    lock_path(workspace).write_text('99999')

    result = runner.invoke(
        cli.app, ['clean', str(series_file), '--workspace', str(workspace), '--dry-run']
    )
    assert result.exit_code == EXIT_OK
    assert 'record run r1 as abandoned' in result.output
    assert (outputs / 'spawns.jsonl').read_text() == before


def test_clean_without_a_stale_lock_leaves_the_ledger_alone(tmp_path: Path) -> None:
    """The lock is what identifies this workspace as the one a killed run left behind."""
    workspace, series_file, _ = _repo_with_series(tmp_path)
    outputs = tmp_path / 'outputs'
    _unfinished_ledger(outputs)
    before = (outputs / 'spawns.jsonl').read_text()

    runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])

    assert (outputs / 'spawns.jsonl').read_text() == before


def test_clean_is_idempotent_on_an_already_clean_workspace(tmp_path: Path) -> None:
    workspace, series_file, _ = _repo_with_series(tmp_path)

    first = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    second = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    assert first.exit_code == EXIT_OK
    assert second.exit_code == EXIT_OK
    assert Git(workspace).current_branch() == 'base'


def test_clean_dry_run_on_a_clean_workspace_says_so(tmp_path: Path) -> None:
    workspace, series_file, _ = _repo_with_series(tmp_path)
    result = runner.invoke(
        cli.app, ['clean', str(series_file), '--workspace', str(workspace), '--dry-run']
    )
    assert result.exit_code == EXIT_OK
    assert 'already clean' in result.output


def test_clean_keeps_ignored_files(tmp_path: Path) -> None:
    """No -x: a local venv or editor state must survive the recovery."""
    workspace, series_file, _ = _repo_with_series(tmp_path)
    (workspace / '.gitignore').write_text('keepme/\n')
    subprocess.run(['git', 'add', '-A'], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(
        ['git', 'commit', '-m', 'ignore'], cwd=workspace, check=True, capture_output=True, text=True
    )
    (workspace / 'keepme').mkdir()
    (workspace / 'keepme' / 'venv.txt').write_text('expensive to rebuild\n')

    result = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    assert result.exit_code == EXIT_OK
    assert (workspace / 'keepme' / 'venv.txt').exists()


def test_clean_on_a_non_repo_is_a_usage_error(tmp_path: Path) -> None:
    workspace, series_file, _ = _repo_with_series(tmp_path)
    not_a_repo = tmp_path / 'plain'
    not_a_repo.mkdir()
    result = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(not_a_repo)])
    assert result.exit_code == EXIT_USAGE


def test_clean_takes_no_lock_and_runs_no_seat_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is the recovery path: it must not spend money or contend for the lock."""
    workspace, series_file, _ = _repo_with_series(tmp_path)

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError('clean must not probe the seat')

    monkeypatch.setattr('convoy.interface.seat_probe.seat_problem', _boom)
    # A lock held by a "live" run must not stop recovery, and must be cleared by it.
    lock_path(workspace).write_text('12345')

    result = runner.invoke(cli.app, ['clean', str(series_file), '--workspace', str(workspace)])
    assert result.exit_code == EXIT_OK
    assert not lock_path(workspace).exists()


# --- run --json ---------------------------------------------------------------------------
#
# The contract is narrow and worth pinning exactly: stdout carries ONE JSON object and
# nothing else, on every path, and only when asked. A measurement harness parses stdout;
# anything else there breaks it, and prose-on-failure forces it to special-case the case it
# most needs to classify.


def _stdout_json(result: object) -> dict[str, object]:
    """Parse the CliRunner result's stdout as a single JSON object."""
    payload = json.loads(result.stdout.strip())  # type: ignore[attr-defined]
    assert isinstance(payload, dict)
    return payload


def _fake_completed(monkeypatch: pytest.MonkeyPatch, outputs: Path) -> None:
    """Stub the engine so it writes a small real ledger and reports completed."""

    def _fake(_series: object, _ws: object, **k: object) -> RunOutcome:
        outputs.mkdir(parents=True, exist_ok=True)
        run_id = k['run_id']
        lines = [
            {'schema_version': 1, 'event': 'run_start', 'run_id': run_id, 'series_id': 'cli-test'},
            {
                'schema_version': 1,
                'event': 'spawn_complete',
                'run_id': run_id,
                'pr_id': 'pr-1',
                'role': 'implementation',
                'exit_code': 0,
                'input_tokens': 10,
                'output_tokens': 2,
                'num_turns': 3,
                'duration_s': 1.5,
                'cost_usd': 0.25,
                'effective_model': 'claude-haiku-4-5',
            },
        ]
        (outputs / 'spawns.jsonl').write_text(
            '\n'.join(json.dumps(line) for line in lines) + '\n', encoding='utf-8'
        )
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(cli, 'run_series_headless', _fake)


def test_stdout_is_empty_without_the_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The default is unchanged: a caller reading only the exit code sees nothing on stdout."""
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)
    _fake_completed(monkeypatch, outputs)

    result = runner.invoke(cli.app, ['run', str(series_file), '--quiet'])
    assert result.exit_code == EXIT_OK
    assert result.stdout.strip() == ''


def test_json_emits_the_run_envelope_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)
    _fake_completed(monkeypatch, outputs)

    result = runner.invoke(cli.app, ['run', str(series_file), '--json', '--quiet'])
    assert result.exit_code == EXIT_OK

    payload = _stdout_json(result)
    assert payload['ok'] is True
    assert payload['outcome'] == 'completed'
    assert payload['exit_code'] == EXIT_OK
    assert payload['series_id'] == 'cli-test'
    # The folded economy the harness came for -- not the raw ledger.
    assert payload['economy']['total_cost_usd'] == 0.25
    assert payload['economy']['spawn_count'] == 1
    assert payload['economy']['num_turns'] == 3
    # The full trace is referenced, never inlined.
    assert payload['telemetry_path'].endswith('spawns.jsonl')
    assert [pr['pr_id'] for pr in payload['prs']] == ['pr-1']
    assert payload['prs'][0]['effective_model'] == 'claude-haiku-4-5'


def test_json_failure_is_the_same_shape_the_mcp_tool_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A could-not-start run must still be ONE parseable object, not prose."""
    workspace, prompts, outputs = _layout(tmp_path)
    # No pr1.md -> a prompt pre-flight problem.
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    result = runner.invoke(cli.app, ['run', str(series_file), '--json'])
    assert result.exit_code == EXIT_USAGE

    payload = _stdout_json(result)
    assert payload['ok'] is False
    assert payload['outcome'] == 'usage'
    assert any(problem['kind'] == 'prompt' for problem in payload['problems'])


def test_json_failure_carries_the_error_kind_taxonomy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """error_kind comes from the shared module, so the two surfaces cannot drift."""
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)

    def _boom(*_a: object, **_k: object) -> RunOutcome:
        raise GitError('checkout failed')

    monkeypatch.setattr(cli, 'run_series_headless', _boom)

    result = runner.invoke(cli.app, ['run', str(series_file), '--json'])
    assert result.exit_code == EXIT_USAGE

    payload = _stdout_json(result)
    assert payload['ok'] is False
    assert payload['error_kind'] == 'git'
    assert 'checkout failed' in payload['error']


def test_the_json_envelope_matches_the_mcp_tools_for_the_same_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both surfaces fold one ledger through one function, so the totals cannot disagree.

    This is the reason summarize_run was lifted out of the MCP server rather than copied.
    """
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)
    _fake_completed(monkeypatch, outputs)

    result = runner.invoke(cli.app, ['run', str(series_file), '--json', '--quiet'])
    from_cli = _stdout_json(result)

    from_module = summarize_run(
        outputs / 'spawns.jsonl',
        run_id=from_cli['run_id'],
        series_id='cli-test',
        outcome=RunOutcome('completed', True, EXIT_OK),
    )
    assert from_cli == from_module


# --- convoy status ------------------------------------------------------------------------
#
# Reads the ledger only, so it reports on a run this process never started -- which is the
# point: the supported long-run pattern is `convoy run` in a background shell, and until
# now nothing could ask that run how it was doing.


def _ledger(outputs: Path, lines: list[dict[str, object]]) -> None:
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / 'spawns.jsonl').write_text(
        '\n'.join(json.dumps(line) for line in lines) + '\n', encoding='utf-8'
    )


def _spawn_line(run_id: str, pr_id: str, cost: float) -> dict[str, object]:
    return {
        'schema_version': 1,
        'event': 'spawn_complete',
        'run_id': run_id,
        'pr_id': pr_id,
        'role': 'implementation',
        'exit_code': 0,
        'input_tokens': 10,
        'output_tokens': 2,
        'num_turns': 4,
        'duration_s': 1.0,
        'cost_usd': cost,
        'effective_model': 'claude-haiku-4-5',
        'classification': 'ok',
    }


def _status_series(tmp_path: Path) -> tuple[Path, Path]:
    """A series file plus its outputs dir."""
    _, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    return series_file, outputs


def test_status_reports_a_run_still_in_progress(tmp_path: Path) -> None:
    """No run_complete line yet: terminal fields are null, the economy is a running total."""
    series_file, outputs = _status_series(tmp_path)
    _ledger(
        outputs,
        [
            {'schema_version': 1, 'event': 'run_start', 'run_id': 'r1', 'series_id': 'cli-test'},
            _spawn_line('r1', 'pr-1', 0.4),
        ],
    )

    result = runner.invoke(cli.app, ['status', str(series_file), '--json'])
    assert result.exit_code == EXIT_OK

    payload = json.loads(result.stdout.strip())
    assert payload['state'] == 'running'
    assert payload['outcome'] is None
    assert payload['exit_code'] is None
    assert payload['integrated'] is None
    assert payload['ok'] is False
    # The partial total is the useful thing to watch while it runs.
    assert payload['economy']['total_cost_usd'] == 0.4
    assert payload['economy']['spawn_count'] == 1


def test_status_reports_a_finished_run_with_its_halt(tmp_path: Path) -> None:
    series_file, outputs = _status_series(tmp_path)
    _ledger(
        outputs,
        [
            {'schema_version': 1, 'event': 'run_start', 'run_id': 'r1', 'series_id': 'cli-test'},
            _spawn_line('r1', 'pr-1', 1.5),
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': 'r1',
                'outcome': 'budget',
                'integrated': False,
                'halt': {
                    'pr_id': 'pr-1',
                    'phase': 'core',
                    'role': 'implementation',
                    'spend_usd': 1.5,
                    'cap_usd': 1.0,
                },
            },
        ],
    )

    result = runner.invoke(cli.app, ['status', str(series_file), '--json'])
    assert result.exit_code == EXIT_OK

    payload = json.loads(result.stdout.strip())
    assert payload['state'] == 'finished'
    assert payload['outcome'] == 'budget'
    # Rebuilt from the outcome by the published mapping -- no live RunOutcome existed.
    assert payload['exit_code'] == EXIT_BUDGET
    assert payload['integrated'] is False
    assert payload['halt']['cap_usd'] == 1.0


def test_status_exit_code_does_not_adopt_the_runs_verdict(tmp_path: Path) -> None:
    """Reporting a blocked run is a successful report, not a blocked status command."""
    series_file, outputs = _status_series(tmp_path)
    _ledger(
        outputs,
        [
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': 'r1',
                'outcome': 'blocked',
                'integrated': False,
                'halt': {
                    'pr_id': 'pr-1',
                    'phase': 'core',
                    'role': 'gate',
                    'spend_usd': None,
                    'cap_usd': None,
                },
            }
        ],
    )
    result = runner.invoke(cli.app, ['status', str(series_file), '--json'])
    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout.strip())['outcome'] == 'blocked'


def test_status_defaults_to_the_most_recent_run(tmp_path: Path) -> None:
    """Run ids sort lexicographically by start time, which is what makes 'latest' answerable."""
    series_file, outputs = _status_series(tmp_path)
    _ledger(
        outputs,
        [
            _spawn_line('20260101T000000Z-aa', 'pr-1', 0.1),
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': '20260101T000000Z-aa',
                'outcome': 'completed',
                'integrated': True,
                'halt': None,
            },
            _spawn_line('20260725T120000Z-bb', 'pr-1', 0.9),
        ],
    )

    result = runner.invoke(cli.app, ['status', str(series_file), '--json'])
    payload = json.loads(result.stdout.strip())
    assert payload['run_id'] == '20260725T120000Z-bb'
    assert payload['state'] == 'running'
    # The older run's economy must not leak into the newer run's totals.
    assert payload['economy']['total_cost_usd'] == 0.9


def test_status_can_target_an_older_run_explicitly(tmp_path: Path) -> None:
    series_file, outputs = _status_series(tmp_path)
    _ledger(
        outputs,
        [
            _spawn_line('20260101T000000Z-aa', 'pr-1', 0.1),
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': '20260101T000000Z-aa',
                'outcome': 'completed',
                'integrated': True,
                'halt': None,
            },
            _spawn_line('20260725T120000Z-bb', 'pr-1', 0.9),
        ],
    )

    result = runner.invoke(
        cli.app, ['status', str(series_file), '--run-id', '20260101T000000Z-aa', '--json']
    )
    payload = json.loads(result.stdout.strip())
    assert payload['state'] == 'finished'
    assert payload['ok'] is True
    assert payload['economy']['total_cost_usd'] == 0.1


def test_status_on_an_empty_ledger_is_unknown_not_an_error(tmp_path: Path) -> None:
    """A run that has not written its first line yet is a legitimate state to observe."""
    series_file, _ = _status_series(tmp_path)

    result = runner.invoke(cli.app, ['status', str(series_file), '--json'])
    assert result.exit_code == EXIT_OK

    payload = json.loads(result.stdout.strip())
    assert payload['state'] == 'unknown'
    assert payload['ok'] is False
    assert 'no run recorded' in payload['message']


def test_status_human_output_names_the_halt(tmp_path: Path) -> None:
    series_file, outputs = _status_series(tmp_path)
    _ledger(
        outputs,
        [
            _spawn_line('r1', 'pr-1', 1.5),
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': 'r1',
                'outcome': 'budget',
                'integrated': False,
                'halt': {
                    'pr_id': 'pr-1',
                    'phase': 'core',
                    'role': 'implementation',
                    'spend_usd': 1.5,
                    'cap_usd': 1.0,
                },
            },
        ],
    )

    result = runner.invoke(cli.app, ['status', str(series_file)])
    assert result.exit_code == EXIT_OK
    assert 'finished' in result.output
    assert 'halted at pr-1' in result.output
    assert '$1.50 of $1.00' in result.output


# --- --run-id -----------------------------------------------------------------------------
#
# A caller that must know the run id before the run starts (a detached launch returning a
# handle) pins it. The ledger is append-only across runs and every fold selects by run_id,
# so reusing one is refused rather than silently folding two runs into one summary.


def test_run_id_is_pinned_when_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    series_file = _valid_run_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        'convoy.interface.run_service.run_series',
        lambda *_a, **_k: RunOutcome('completed', True, EXIT_OK),
    )

    result = runner.invoke(cli.app, ['run', str(series_file), '--run-id', 'pinned-1', '--json'])

    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout.strip())['run_id'] == 'pinned-1'


def test_run_id_is_minted_when_omitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    series_file = _valid_run_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        'convoy.interface.run_service.run_series',
        lambda *_a, **_k: RunOutcome('completed', True, EXIT_OK),
    )

    result = runner.invoke(cli.app, ['run', str(series_file), '--json'])

    # The minted shape: a UTC stamp plus a random suffix, which is what makes ids sortable.
    assert re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{8}', json.loads(result.stdout.strip())['run_id'])


def test_a_reused_run_id_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Folding two runs under one id sums their economies -- undetectable downstream."""
    workspace, prompts, outputs = _layout(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    monkeypatch.chdir(workspace)
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / 'spawns.jsonl').write_text(
        json.dumps({'schema_version': 1, 'event': 'run_start', 'run_id': 'taken', 'series_id': 'x'})
        + '\n',
        encoding='utf-8',
    )

    called: list[object] = []
    monkeypatch.setattr(
        'convoy.interface.run_service.run_series', lambda *_a, **_k: called.append(1)
    )

    result = runner.invoke(cli.app, ['run', str(series_file), '--run-id', 'taken', '--json'])

    assert result.exit_code == EXIT_USAGE
    assert called == []
    payload = json.loads(result.stdout.strip())
    assert payload['outcome'] == 'usage'
    assert [p['kind'] for p in payload['problems']] == ['run_id']


# --- status of a run whose driver is gone --------------------------------------------------
#
# The ledger records only completions, so "running" was derived from the absence of a
# terminal line -- exactly what a killed driver leaves behind. The lock has always named its
# owner; reading it back is what separates the two.


def _dead_pid() -> int:
    """A pid that named a real process and no longer does."""
    child = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.DEVNULL)
    pid = child.pid
    child.wait()
    return pid


def _locked_workspace(tmp_path: Path, pid: int) -> Path:
    """A workspace holding a run lock owned by ``pid``."""
    workspace = tmp_path / 'ws'
    (workspace / '.git').mkdir(parents=True, exist_ok=True)
    lock_path(workspace).write_text(str(pid), encoding='utf-8')
    return workspace


def _unfinished_ledger(outputs: Path) -> None:
    _ledger(
        outputs,
        [
            {'schema_version': 1, 'event': 'run_start', 'run_id': 'r1', 'series_id': 'cli-test'},
            _spawn_line('r1', 'pr-1', 0.4),
        ],
    )


def test_status_reports_dead_when_the_lock_owner_is_gone(tmp_path: Path) -> None:
    series_file, outputs = _status_series(tmp_path)
    _unfinished_ledger(outputs)
    workspace = _locked_workspace(tmp_path, _dead_pid())

    result = runner.invoke(cli.app, ['status', str(series_file), '-w', str(workspace), '--json'])
    assert result.exit_code == EXIT_OK

    payload = json.loads(result.stdout.strip())
    assert payload['state'] == 'dead'
    # The terminal fields stay null -- dead is not an outcome, it is the absence of one.
    assert payload['outcome'] is None
    assert payload['ok'] is False
    # The economy is final rather than partial, and the message says how to recover.
    assert payload['economy']['total_cost_usd'] == 0.4
    assert 'resume' in payload['message']


def test_status_stays_running_while_the_lock_owner_lives(tmp_path: Path) -> None:
    series_file, outputs = _status_series(tmp_path)
    _unfinished_ledger(outputs)
    workspace = _locked_workspace(tmp_path, os.getpid())

    result = runner.invoke(cli.app, ['status', str(series_file), '-w', str(workspace), '--json'])

    assert json.loads(result.stdout.strip())['state'] == 'running'


def test_status_stays_running_when_no_lock_is_there_to_read(tmp_path: Path) -> None:
    """Asking from a directory that holds no lock is the commonest way to be wrong.

    A false ``dead`` sends an operator to restart a run that is still spending, so the
    claim is made only on positive evidence: a lock naming a process that is gone.
    """
    series_file, outputs = _status_series(tmp_path)
    _unfinished_ledger(outputs)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()

    result = runner.invoke(cli.app, ['status', str(series_file), '-w', str(elsewhere), '--json'])

    assert json.loads(result.stdout.strip())['state'] == 'running'


def test_status_human_output_says_how_to_recover_a_dead_run(tmp_path: Path) -> None:
    series_file, outputs = _status_series(tmp_path)
    _unfinished_ledger(outputs)
    workspace = _locked_workspace(tmp_path, _dead_pid())

    result = runner.invoke(cli.app, ['status', str(series_file), '-w', str(workspace)])

    assert 'dead' in result.stdout
    assert 'convoy clean' in result.stdout


# --- status of a detached run that never reached the ledger -------------------------------
#
# A detached run can die before writing its first ledger line (a busy workspace, an expired
# seat, a git failure). Reporting that as `running` forever would be the worst answer
# available, so status consults the envelope the child wrote under --json.


def _detached_envelope(outputs: Path, run_id: str, payload: dict[str, object]) -> None:
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / f'{run_id}.json').write_text(json.dumps(payload), encoding='utf-8')


def test_status_reports_a_detached_run_that_failed_to_start(tmp_path: Path) -> None:
    series_file, outputs = _status_series(tmp_path)
    _detached_envelope(
        outputs,
        'r1',
        {'ok': False, 'outcome': 'usage', 'series_id': 'cli-test', 'error_kind': 'busy'},
    )

    result = runner.invoke(cli.app, ['status', str(series_file), '--run-id', 'r1', '--json'])

    assert result.exit_code == EXIT_OK
    payload = json.loads(result.stdout.strip())
    # `finished` is filled in: the could-not-start shape predates `state`, and a run that
    # never started will not advance.
    assert payload['state'] == 'finished'
    assert payload['ok'] is False
    assert payload['error_kind'] == 'busy'


def test_status_prefers_the_ledger_over_the_detached_result_file(tmp_path: Path) -> None:
    """The ledger is the record of a run that actually got going; the file is the gap-filler."""
    series_file, outputs = _status_series(tmp_path)
    _ledger(
        outputs,
        [
            {'schema_version': 1, 'event': 'run_start', 'run_id': 'r1', 'series_id': 'cli-test'},
            _spawn_line('r1', 'pr-1', 0.7),
        ],
    )
    _detached_envelope(outputs, 'r1', {'ok': False, 'outcome': 'usage', 'error_kind': 'busy'})

    result = runner.invoke(cli.app, ['status', str(series_file), '--run-id', 'r1', '--json'])

    payload = json.loads(result.stdout.strip())
    assert payload['state'] == 'running'
    assert payload['economy']['total_cost_usd'] == 0.7
    assert 'error_kind' not in payload


def test_status_treats_a_half_written_result_file_as_absent(tmp_path: Path) -> None:
    """Caught mid-flush it does not parse, which means the child is evidently still going."""
    series_file, outputs = _status_series(tmp_path)
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / 'r1.json').write_text('{"ok": fal', encoding='utf-8')

    result = runner.invoke(cli.app, ['status', str(series_file), '--run-id', 'r1', '--json'])

    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout.strip())['state'] == 'running'


def test_status_reports_the_runs_advisories(tmp_path: Path) -> None:
    """A run this process never started still reports what its pre-flight said."""
    series_file, outputs = _status_series(tmp_path)
    _ledger(
        outputs,
        [
            {
                'schema_version': 1,
                'event': 'run_start',
                'run_id': 'r1',
                'series_id': 'cli-test',
                'advisories': [
                    {'kind': 'gate', 'where': "[[prs]] 'pr-1'", 'message': 'integrates unverified'}
                ],
            },
            _spawn_line('r1', 'pr-1', 0.2),
        ],
    )

    result = runner.invoke(cli.app, ['status', str(series_file), '--json'])

    assert result.exit_code == EXIT_OK
    payload = json.loads(result.stdout.strip())
    assert [a['kind'] for a in payload['advisories']] == ['gate']
