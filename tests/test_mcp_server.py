"""MCP server tests: the two tools' schema, results, telemetry summary, and stdout hygiene.

The async tools are driven via ``asyncio.run`` inside sync tests, so no pytest-asyncio
plugin is needed.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from convoy.interface.drivers.headless import EXIT_OK, RunOutcome
from convoy.interface.git import GitError
from convoy.interface.mcp import server as srv
from convoy.interface.mcp.server import (
    build_server,
    convoy_init,
    convoy_run,
    summarize_run,
)
from convoy.interface.workspace_lock import WorkspaceBusyError


def _tools() -> dict[str, Any]:
    return {t.name: t for t in asyncio.run(build_server().list_tools())}


def _series_toml(prompts: Path, outputs: Path) -> str:
    return f"""
[series]
id = "mcp-test"
version = "1"
[branches]
base = "base"
integration = "integration"
[paths]
prompts = "{prompts.as_posix()}"
outputs = "{outputs.as_posix()}"
[governance]
model = "claude-haiku-4-5"
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
"""


def _spawn_line(run_id: str, pr_id: str, **over: Any) -> dict[str, Any]:
    line = {
        'schema_version': 1,
        'event': 'spawn_complete',
        'run_id': run_id,
        'pr_id': pr_id,
        'role': 'implementation',
        'exit_code': 0,
        'input_tokens': 10,
        'output_tokens': 5,
        'num_turns': 1,
        'duration_s': 1.0,
        'cost_usd': 0.01,
        'effective_model': 'm',
        'cost_estimated': False,
    }
    line.update(over)
    return line


def _write_jsonl(path: Path, lines: list[dict[str, Any]]) -> None:
    path.write_text('\n'.join(json.dumps(line) for line in lines), encoding='utf-8')


# --- schema (the dead-surface guard) ------------------------------------------------------


def test_build_server_registers_both_tools() -> None:
    assert set(_tools()) == {'convoy_run', 'convoy_init'}


def test_every_tool_schema_documents_every_parameter() -> None:
    tools = _tools()
    expected = {
        'convoy_run': {'series_file', 'workspace', 'dry_run', 'config_isolation', 'reset'},
        'convoy_init': {'directory'},
    }
    for name, params in expected.items():
        props = tools[name].inputSchema['properties']
        assert set(props) == params, name
        for param in params:
            assert props[param].get('description', '').strip(), f'{name}.{param} has no description'
    assert set(tools['convoy_run'].inputSchema['required']) == {'series_file', 'workspace'}
    assert tools['convoy_init'].inputSchema['required'] == ['directory']


# --- convoy_run: dry_run (no spend) -------------------------------------------------------


def test_convoy_run_dry_run_validates_a_clean_series(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, tmp_path / 'outputs'))

    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws), dry_run=True))
    assert result['ok'] is True
    assert result['outcome'] == 'validated'
    assert result['problems'] == []


def test_convoy_run_dry_run_reports_problems(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()  # no pr1.md -> a prompt problem
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, tmp_path / 'outputs'))

    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws), dry_run=True))
    assert result['ok'] is False
    assert result['outcome'] == 'usage'
    assert any(problem['kind'] == 'prompt' for problem in result['problems'])


def test_convoy_run_bad_spec_is_a_usage_result_not_an_exception(tmp_path: Path) -> None:
    series_file = tmp_path / 'bad.toml'
    series_file.write_text('not = = valid toml')
    result = asyncio.run(
        convoy_run(series_file=str(series_file), workspace=str(tmp_path), dry_run=True)
    )
    assert result['ok'] is False
    assert result['outcome'] == 'usage'
    assert 'error' in result
    assert result['error_kind'] == 'spec'


def test_convoy_run_runtime_git_error_is_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A runtime GitError (pre-flight passed, then git failed) returns a structured usage
    # result carrying error_kind='git', never a raised exception.
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, tmp_path / 'outputs'))

    def _boom(*_a: Any, **_k: Any) -> RunOutcome:
        raise GitError('merge conflict on integration')

    monkeypatch.setattr(srv, 'run_series_headless', _boom)
    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws)))
    assert result['ok'] is False
    assert result['outcome'] == 'usage'
    assert result['error_kind'] == 'git'
    assert 'merge conflict' in result['error']


def test_convoy_run_workspace_busy_is_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A concurrent run holding the workspace lock returns a structured usage result carrying
    # error_kind='busy', never a raised exception.
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, tmp_path / 'outputs'))

    def _boom(*_a: Any, **_k: Any) -> RunOutcome:
        raise WorkspaceBusyError('workspace is locked by another run')

    monkeypatch.setattr(srv, 'run_series_headless', _boom)
    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws)))
    assert result['ok'] is False
    assert result['outcome'] == 'usage'
    assert result['error_kind'] == 'busy'
    assert 'locked' in result['error']


# --- convoy_run: real run summarizes telemetry --------------------------------------------


def test_convoy_run_summarizes_telemetry_by_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # run_series_headless is stubbed to write a fake telemetry file and return an outcome; the
    # tool result must carry economy totals + the per-PR gate view, and reference the trace BY
    # PATH rather than inlining it.
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    outputs = tmp_path / 'outputs'
    outputs.mkdir()
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    telem = outputs / 'spawns.jsonl'

    def _fake_run(
        series: Any,
        workspace: Any,
        *,
        run_id: str,
        config_isolation: bool = True,
        reporter: Any = None,
        fresh: bool = False,
    ) -> RunOutcome:
        _write_jsonl(
            telem,
            [
                {
                    'schema_version': 1,
                    'event': 'run_start',
                    'run_id': run_id,
                    'series_id': 'mcp-test',
                },
                _spawn_line(run_id, 'pr-1', cost_usd=0.04, num_turns=3),
                {
                    'schema_version': 1,
                    'event': 'gate_complete',
                    'run_id': run_id,
                    'pr_id': 'pr-1',
                    'attempt': 0,
                    'blocking_red': False,
                    'independent_red': False,
                    'checks': [
                        {
                            'name': 'suite',
                            'passed': True,
                            'blocking': True,
                            'independent': False,
                            'detail': '',
                        }
                    ],
                },
                {
                    'schema_version': 1,
                    'event': 'run_complete',
                    'run_id': run_id,
                    'outcome': 'completed',
                    'integrated': True,
                },
            ],
        )
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(srv, 'run_series_headless', _fake_run)

    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws)))
    assert result['ok'] is True
    assert result['outcome'] == 'completed'
    assert result['integrated'] is True
    assert result['economy']['spawn_count'] == 1
    assert result['economy']['total_cost_usd'] == 0.04
    assert result['prs'][0]['pr_id'] == 'pr-1'
    assert result['prs'][0]['gate']['blocking_red'] is False
    assert result['prs'][0]['gate']['failing_checks'] == []
    assert result['telemetry_path'] == str(telem)  # trace by path, not inlined
    assert result['truncated']['any'] is False


def test_convoy_run_reset_threads_through_to_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    outputs = tmp_path / 'outputs'
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))

    captured: dict[str, Any] = {}

    def _fake_run(
        series: Any,
        workspace: Any,
        *,
        run_id: str,
        config_isolation: bool = True,
        reporter: Any = None,
        fresh: bool = False,
    ) -> RunOutcome:
        captured['fresh'] = fresh
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(srv, 'run_series_headless', _fake_run)

    asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws), reset=True))
    assert captured['fresh'] is True


def test_summarize_run_aggregates_filters_by_run_id_and_truncates(tmp_path: Path) -> None:
    telem = tmp_path / 'spawns.jsonl'
    run_id = 'r'
    lines: list[dict[str, Any]] = [_spawn_line(run_id, f'pr-{i}') for i in range(3)]
    lines.append(
        {
            'schema_version': 1,
            'event': 'pr_skipped',
            'run_id': run_id,
            'pr_id': 'pr-3',
            'reason': 'upstream pr-0 blocked',
        }
    )
    # A line from ANOTHER run (with an inflated, estimated cost) must be ignored entirely.
    lines.append(_spawn_line('other', 'x', cost_usd=9.9, input_tokens=999, cost_estimated=True))
    _write_jsonl(telem, lines)

    summary = summarize_run(
        telem, run_id=run_id, series_id='s', outcome=RunOutcome('blocked', False, 1), pr_cap=2
    )
    assert summary['economy']['spawn_count'] == 3
    assert abs(summary['economy']['total_cost_usd'] - 0.03) < 1e-9
    assert summary['economy']['cost_estimated'] is False  # the estimated line was another run
    assert len(summary['prs']) == 2  # capped
    assert summary['truncated'] == {'any': True, 'prs': 2}  # pr-0..pr-3 -> 4 total, 2 dropped
    assert summary['telemetry_path'] == str(telem)


# --- convoy_init + stdout hygiene ---------------------------------------------------------


def test_convoy_init_scaffolds_and_names_the_paths(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    result = asyncio.run(convoy_init(directory=str(root)))
    assert result['ok'] is True
    assert (root / 'series.toml').is_file()
    assert result['series_file'] == str(root / 'series.toml')
    assert result['workspace'] == str(root / 'workspace')
    assert 'convoy_run' in result['next']


def test_convoy_init_refuses_to_clobber(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    asyncio.run(convoy_init(directory=str(root)))
    result = asyncio.run(convoy_init(directory=str(root)))
    assert result['ok'] is False
    assert 'error' in result


def test_tools_write_nothing_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The stdio MCP server owns stdout for JSON-RPC; the tools must print nothing there.
    asyncio.run(convoy_init(directory=str(tmp_path / 'proj')))
    assert capsys.readouterr().out == ''
