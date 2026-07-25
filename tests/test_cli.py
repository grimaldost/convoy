"""CLI tests: ``convoy validate``, the hardened ``convoy run``, and ``convoy clean``.

Uses typer's ``CliRunner``. ``run`` is exercised with ``run_series`` monkeypatched (patched
on the ``cli`` module, where it is imported), so no real agent spawns and no git is driven —
the tests assert the CLI's own behavior: pre-flight before any side effect, clean exit codes,
and mapping runtime errors to ``EXIT_USAGE`` instead of a traceback.

``clean`` is the exception: it is exercised against a REAL temp git repo, because the whole
point of the verb is what it does to a dirty working tree, which a stubbed ``Git`` cannot
demonstrate. It drives git only — never a spawn.
"""

import subprocess
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
from convoy.interface.git import Git, GitError
from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.reporter import NullReporter, StderrReporter
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
