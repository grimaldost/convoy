"""Tests for the shared headless run service (interface/run_service.py)."""

import subprocess
from pathlib import Path

import pytest

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
from convoy.interface import run_service
from convoy.interface.drivers.headless import EXIT_OK, RunOutcome
from convoy.interface.git import Git, GitError
from convoy.interface.headless_spawn import HeadlessSpawn
from convoy.interface.run_service import PreflightError, run_series_headless


def _series(prompts: Path, outputs: Path) -> Series:
    return Series(
        id='s',
        version='1',
        branches=Branches(base='base', integration='integration'),
        paths=Paths(prompts=str(prompts), outputs=str(outputs)),
        governance=Governance(
            effort='low',
            permission_mode='default',
            timeout_seconds=60,
            budgets=Budgets(implementation=1.0, review=1.0, fix=1.0),
            tools=Tools(implementation=('Read',), review=(), fix=()),
            model='claude-haiku-4-5',
        ),
        review=Review(blocking=False, max_fix_attempts=0),
        checks=(),
        prs=(PR(id='pr-1', branch='pr-1', prompt='pr1.md', phase='p'),),
    )


def _clean(tmp_path: Path) -> tuple[Path, Series, Path]:
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    outputs = tmp_path / 'outputs'
    return ws, _series(prompts, outputs), outputs


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def _init_repo(ws: Path) -> None:
    """Init a real git repo at ``ws`` on branch ``base`` with one commit — matches ``_series``."""
    _git(ws, 'init', '-b', 'base')
    _git(ws, 'config', 'user.email', 'test@example.com')
    _git(ws, 'config', 'user.name', 'Test User')
    (ws / 'README.md').write_text('initial\n', encoding='utf-8')
    _git(ws, 'add', '-A')
    _git(ws, 'commit', '-m', 'initial commit')


def test_preflight_failure_raises_before_any_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()  # no pr1.md -> a prompt problem
    outputs = tmp_path / 'outputs'
    series = _series(prompts, outputs)

    called: list[int] = []
    monkeypatch.setattr(run_service, 'run_series', lambda *a, **k: called.append(1))

    with pytest.raises(PreflightError) as excinfo:
        run_series_headless(series, ws, run_id='r')
    assert excinfo.value.problems  # the located problems ride along
    assert called == []  # engine never reached
    assert not outputs.exists()  # no output dir created before the run


def test_clean_run_isolates_by_default_and_returns_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, series, outputs = _clean(tmp_path)
    captured: dict[str, object] = {}

    def _fake(*_a: object, **k: object) -> RunOutcome:
        captured['spawn'] = k['spawn']
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(run_service, 'run_series', _fake)

    outcome = run_series_headless(series, ws, run_id='r')
    assert outcome == RunOutcome('completed', True, EXIT_OK)
    spawn = captured['spawn']
    assert isinstance(spawn, HeadlessSpawn)
    assert spawn._config_dir is not None  # a credential-only isolated dir was passed
    assert outputs.is_dir()  # the telemetry output dir was created


def test_config_isolation_off_inherits_the_operator_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, series, _outputs = _clean(tmp_path)
    captured: dict[str, object] = {}

    def _fake(*_a: object, **k: object) -> RunOutcome:
        captured['spawn'] = k['spawn']
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(run_service, 'run_series', _fake)

    run_series_headless(series, ws, run_id='r', config_isolation=False)
    spawn = captured['spawn']
    assert isinstance(spawn, HeadlessSpawn)
    assert spawn._config_dir is None  # inherits the operator config


def test_fresh_true_resets_the_workspace_before_the_engine_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, series, _outputs = _clean(tmp_path)
    _init_repo(ws)
    _git(ws, 'checkout', '-b', 'pr-1')
    _git(ws, 'checkout', '-b', 'integration')
    _git(ws, 'checkout', 'base')

    monkeypatch.setattr(
        run_service, 'run_series', lambda *_a, **_k: RunOutcome('completed', True, EXIT_OK)
    )

    run_series_headless(series, ws, run_id='r', fresh=True)

    assert Git(ws).current_branch() == 'base'
    result = subprocess.run(
        ['git', 'branch', '--list'], cwd=ws, capture_output=True, text=True, check=True
    )
    assert 'pr-1' not in result.stdout
    assert 'integration' not in result.stdout


def test_fresh_false_leaves_existing_branches_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, series, _outputs = _clean(tmp_path)
    _init_repo(ws)
    _git(ws, 'checkout', '-b', 'pr-1')
    _git(ws, 'checkout', 'base')

    monkeypatch.setattr(
        run_service, 'run_series', lambda *_a, **_k: RunOutcome('completed', True, EXIT_OK)
    )

    run_series_headless(series, ws, run_id='r', fresh=False)

    result = subprocess.run(
        ['git', 'branch', '--list'], cwd=ws, capture_output=True, text=True, check=True
    )
    assert 'pr-1' in result.stdout


def test_rerun_without_fresh_fails_where_fresh_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, series, outputs = _clean(tmp_path)
    _init_repo(ws)

    from convoy.interface.drivers.headless import run_series
    from convoy.interface.gate_runner import SubprocessGateRunner
    from convoy.interface.spawn import FakeSpawn, ok_result
    from convoy.interface.telemetry_writer import TelemetryWriter

    outputs.mkdir(parents=True, exist_ok=True)
    run_series(
        series,
        ws,
        spawn=FakeSpawn([ok_result()]),
        git=Git(ws),
        gate_runner=SubprocessGateRunner(series.governance.timeout_seconds),
        telemetry=TelemetryWriter(outputs / 'spawns.jsonl'),
        run_id='r1',
    )  # first run: branches into pr-1 and integration, then merges back to base

    # A bare re-run would recreate the same branches and fail loud.
    with pytest.raises(GitError):
        Git(ws).checkout('pr-1', create=True)
    Git(ws).checkout('base')

    # fresh=True resets the workspace first, so a second run's checkout -b calls succeed
    # where they would otherwise collide with the branches the first run left behind.
    monkeypatch.setattr(
        run_service, 'run_series', lambda *_a, **_k: RunOutcome('completed', True, EXIT_OK)
    )
    run_series_headless(series, ws, run_id='r2', fresh=True)
    Git(ws).checkout('pr-1', create=True)  # would have raised GitError before the reset
