"""MCP server tests: the two tools' schema, results, telemetry summary, and stdout hygiene.

The async tools are driven via ``asyncio.run`` inside sync tests, so no pytest-asyncio
plugin is needed.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from convoy.interface.detached import Launch
from convoy.interface.drivers.headless import EXIT_OK, RunOutcome
from convoy.interface.git import GitError
from convoy.interface.mcp import server as srv
from convoy.interface.mcp.server import (
    build_server,
    convoy_init,
    convoy_run,
    summarize_run,
)
from convoy.interface.workspace_lock import WorkspaceBusyError, lock_path


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


def test_build_server_registers_every_tool() -> None:
    assert set(_tools()) == {'convoy_run', 'convoy_gate', 'convoy_init', 'convoy_status'}


def test_every_tool_schema_documents_every_parameter() -> None:
    tools = _tools()
    expected = {
        'convoy_run': {
            'series_file',
            'workspace',
            'dry_run',
            'config_isolation',
            'reset',
            'resume',
            'detach',
        },
        'convoy_gate': {'series_file', 'workspace', 'phases', 'brief'},
        'convoy_init': {'directory'},
        'convoy_status': {'series_file', 'run_id', 'workspace'},
    }
    for name, params in expected.items():
        props = tools[name].inputSchema['properties']
        assert set(props) == params, name
        for param in params:
            assert props[param].get('description', '').strip(), f'{name}.{param} has no description'
    assert set(tools['convoy_run'].inputSchema['required']) == {'series_file', 'workspace'}
    assert set(tools['convoy_gate'].inputSchema['required']) == {'workspace'}
    # run_id defaults to the latest run, so only the series file is required.
    assert set(tools['convoy_status'].inputSchema['required']) == {'series_file'}
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
    # Always present, so a consumer can read the key unconditionally.
    assert result['advisories'] == []


def test_the_envelope_surfaces_the_halt_from_the_ledger(tmp_path: Path) -> None:
    """A halted run's envelope answers which PR, which phase, and spend against the cap.

    Read from the ``run_complete`` line rather than threaded through ``RunOutcome``, so
    the envelope stays reconstructible from the ledger alone.
    """
    telem = tmp_path / 'spawns.jsonl'
    _write_jsonl(
        telem,
        [
            {'schema_version': 1, 'event': 'run_start', 'run_id': 'r', 'series_id': 's'},
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': 'r',
                'outcome': 'budget',
                'integrated': False,
                'halt': {
                    'pr_id': 'pr-2',
                    'phase': 'core',
                    'role': 'fix',
                    'spend_usd': 1.03,
                    'cap_usd': 1.0,
                },
            },
        ],
    )
    envelope = summarize_run(
        telem, run_id='r', series_id='s', outcome=RunOutcome('budget', False, 4)
    )
    assert envelope['halt'] == {
        'pr_id': 'pr-2',
        'phase': 'core',
        'role': 'fix',
        'spend_usd': 1.03,
        'cap_usd': 1.0,
    }


def test_the_envelope_halt_is_none_on_a_clean_run(tmp_path: Path) -> None:
    telem = tmp_path / 'spawns.jsonl'
    _write_jsonl(
        telem,
        [
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': 'r',
                'outcome': 'completed',
                'integrated': True,
                'halt': None,
            }
        ],
    )
    envelope = summarize_run(
        telem, run_id='r', series_id='s', outcome=RunOutcome('completed', True, 0)
    )
    assert envelope['halt'] is None


def test_convoy_run_dry_run_carries_advisories_without_failing(tmp_path: Path) -> None:
    """An ungated PR is reported as advice: the key fills, ok/outcome are untouched."""
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    (prompts / 'pr2.md').write_text('docs only')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(
        _series_toml(prompts, tmp_path / 'outputs').replace(
            'blocking = true', 'blocking = true\nphases = ["core"]'
        )
        + """
[[prs]]
id = "pr-2"
branch = "pr-2"
prompt = "pr2.md"
phase = "docs"
depends_on = []
"""
    )

    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws), dry_run=True))
    assert result['ok'] is True
    assert result['outcome'] == 'validated'
    assert result['problems'] == []
    assert [a['where'] for a in result['advisories']] == ["[[prs]] 'pr-2'"]
    assert result['advisories'][0]['kind'] == 'gate'


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


def test_convoy_run_legacy_encoded_series_is_a_usage_result_not_an_exception(
    tmp_path: Path,
) -> None:
    # A legacy-encoded series file raises UnicodeDecodeError (a ValueError, not an
    # OSError) from the strict UTF-8 read; the tool must still return the usage
    # envelope, never a raised exception — the CLI's _load_or_exit already does.
    series_file = tmp_path / 'legacy.toml'
    series_file.write_bytes('# une série\nnot valid'.encode('cp1252'))
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
        resume: bool = False,
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
                _spawn_line(run_id, 'pr-1', cost_usd=0.04, num_turns=3, effective_model='ran-as'),
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
    assert result['prs'][0]['effective_model'] == 'ran-as'
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
        resume: bool = False,
    ) -> RunOutcome:
        captured['fresh'] = fresh
        return RunOutcome('completed', True, EXIT_OK)

    monkeypatch.setattr(srv, 'run_series_headless', _fake_run)

    asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws), reset=True))
    assert captured['fresh'] is True


def test_summarize_run_aggregates_filters_by_run_id_and_truncates(tmp_path: Path) -> None:
    telem = tmp_path / 'spawns.jsonl'
    run_id = 'r'
    lines: list[dict[str, Any]] = [
        _spawn_line(run_id, f'pr-{i}', effective_model=f'impl-model-{i}') for i in range(3)
    ]
    lines.append(
        {
            'schema_version': 1,
            'event': 'pr_skipped',
            'run_id': run_id,
            'pr_id': 'pr-3',
            'reason': 'series halted at pr-0 (blocked) before this PR started',
        }
    )
    # A line from ANOTHER run (with an inflated, estimated cost and its own model) must be
    # ignored entirely.
    lines.append(
        _spawn_line(
            'other',
            'x',
            cost_usd=9.9,
            input_tokens=999,
            cost_estimated=True,
            effective_model='leaked',
        )
    )
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
    # The cap keeps pr-0 and pr-1 only; each carries its OWN spawn's model...
    assert summary['prs'][0]['effective_model'] == 'impl-model-0'
    assert summary['prs'][1]['effective_model'] == 'impl-model-1'
    # ...and the other run's model never leaks in.
    assert all(pr['effective_model'] != 'leaked' for pr in summary['prs'])


def test_summarize_run_reports_the_implementation_spawn_model_over_a_fix_spawn(
    tmp_path: Path,
) -> None:
    # A PR gets one implementation spawn and up to max_fix_attempts fix spawns. The envelope
    # reports the IMPLEMENTATION spawn's model: that is the spawn the tier decision governed
    # and the one whose output the gate judged. Fix spawns are repair, not the measured
    # attempt. Distinct models per line, so the fix spawn's model can't sneak in unseen.
    telem = tmp_path / 'spawns.jsonl'
    run_id = 'r'
    _write_jsonl(
        telem,
        [
            _spawn_line(run_id, 'pr-1', effective_model='impl-model'),
            _spawn_line(run_id, 'pr-1', role='fix', effective_model='fix-model'),
        ],
    )

    summary = summarize_run(
        telem, run_id=run_id, series_id='s', outcome=RunOutcome('completed', True, EXIT_OK)
    )
    assert summary['prs'][0]['effective_model'] == 'impl-model'
    assert summary['prs'][0]['spawns'] == 2


def test_summarize_run_selects_the_implementation_model_by_role_not_line_order(
    tmp_path: Path,
) -> None:
    # The implementation spawn is picked by its role, not by being the first spawn_complete
    # line. Production telemetry always records the implementation before any fix, so this
    # reversed order (fix line first) cannot occur on disk — it is here to pin the contract:
    # a pure first-wins-by-file-order fold would report 'fix-model', role selection reports
    # 'impl-model'. This is the assertion that fails if the fold ever regresses to line order.
    telem = tmp_path / 'spawns.jsonl'
    run_id = 'r'
    _write_jsonl(
        telem,
        [
            _spawn_line(run_id, 'pr-1', role='fix', effective_model='fix-model'),
            _spawn_line(run_id, 'pr-1', role='implementation', effective_model='impl-model'),
        ],
    )

    summary = summarize_run(
        telem, run_id=run_id, series_id='s', outcome=RunOutcome('completed', True, EXIT_OK)
    )
    assert summary['prs'][0]['effective_model'] == 'impl-model'
    assert summary['prs'][0]['spawns'] == 2


def test_summarize_run_reports_no_model_for_a_skipped_pr(tmp_path: Path) -> None:
    # A halted-past PR never spawned, so it has no model: null, not '' (which would falsely
    # imply one) and not a missing key (which would make consumers guard every read).
    telem = tmp_path / 'spawns.jsonl'
    run_id = 'r'
    _write_jsonl(
        telem,
        [
            {
                'schema_version': 1,
                'event': 'pr_skipped',
                'run_id': run_id,
                'pr_id': 'pr-9',
                'reason': 'series halted at pr-0 (blocked) before this PR started',
            }
        ],
    )

    summary = summarize_run(
        telem, run_id=run_id, series_id='s', outcome=RunOutcome('blocked', False, 1)
    )
    entry = summary['prs'][0]
    assert entry['pr_id'] == 'pr-9'
    assert entry['skipped'] is True
    assert entry['effective_model'] is None


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


# --- convoy_run: detach ---------------------------------------------------------------------
#
# The launch itself is covered end to end in test_detached.py; here the tool's own wiring is
# what matters -- what it returns, and what it refuses before spending a process on it.


def _detach_setup(tmp_path: Path) -> tuple[Path, Path]:
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, tmp_path / 'outputs'))
    return series_file, ws


def _record_launch(recorded: list[dict[str, Any]]) -> Any:
    def _fake(series_file: Path, workspace: Path, outputs: Path, **kwargs: Any) -> Launch:
        recorded.append({'series_file': series_file, 'workspace': workspace, **kwargs})
        run_id = str(kwargs['run_id'])
        return Launch(
            run_id=run_id,
            pid=31337,
            result_path=outputs / f'{run_id}.json',
            log_path=outputs / f'{run_id}.log',
        )

    return _fake


def test_convoy_run_detach_returns_a_handle_not_a_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series_file, ws = _detach_setup(tmp_path)
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(srv, 'launch_detached', _record_launch(recorded))

    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws), detach=True))

    # ok reports the operation -- the launch -- since the run itself has no verdict yet.
    assert result['ok'] is True
    assert result['outcome'] == 'started'
    # The same vocabulary convoy_status answers in, so one branch handles both envelopes.
    assert result['state'] == 'running'
    assert result['run_id'] == recorded[0]['run_id']
    assert result['pid'] == 31337
    assert result['result_path'].endswith(f'{result["run_id"]}.json')
    assert result['log_path'].endswith(f'{result["run_id"]}.log')
    assert result['telemetry_path'].endswith('spawns.jsonl')
    assert result['run_id'] in result['next']


def test_convoy_run_detach_passes_its_options_to_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series_file, ws = _detach_setup(tmp_path)
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(srv, 'launch_detached', _record_launch(recorded))

    asyncio.run(
        convoy_run(
            series_file=str(series_file),
            workspace=str(ws),
            detach=True,
            config_isolation=False,
            reset=True,
        )
    )

    assert recorded[0]['config_isolation'] is False
    assert recorded[0]['fresh'] is True
    assert recorded[0]['resume'] is False


def test_convoy_run_detach_refuses_a_bad_series_before_launching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detaching is about not waiting for the run, not about deferring what is knowable now."""
    ws = tmp_path / 'ws'
    ws.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()  # no pr1.md -> a prompt problem
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, tmp_path / 'outputs'))
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(srv, 'launch_detached', _record_launch(recorded))

    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws), detach=True))

    assert result['ok'] is False
    assert result['outcome'] == 'usage'
    assert [p['kind'] for p in result['problems']] == ['prompt']
    assert recorded == []


def test_convoy_run_detach_reports_a_child_that_could_not_be_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series_file, ws = _detach_setup(tmp_path)

    def _boom(*_a: Any, **_k: Any) -> Launch:
        raise OSError('no interpreter')

    monkeypatch.setattr(srv, 'launch_detached', _boom)

    result = asyncio.run(convoy_run(series_file=str(series_file), workspace=str(ws), detach=True))

    assert result['ok'] is False
    assert result['outcome'] == 'usage'
    assert result['error_kind'] == 'filesystem'


def test_dry_run_takes_precedence_over_detach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-flight is free and instant, so there is nothing to detach."""
    series_file, ws = _detach_setup(tmp_path)
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(srv, 'launch_detached', _record_launch(recorded))

    result = asyncio.run(
        convoy_run(series_file=str(series_file), workspace=str(ws), dry_run=True, detach=True)
    )

    assert result['outcome'] == 'validated'
    assert recorded == []


# --- advisories in the run envelope --------------------------------------------------------
#
# Read from the run_start line for the same reason `halt` is read from run_complete: the
# envelope stays reconstructible from the ledger alone, so `convoy_status` can report a
# run's advisories without having been the process that pre-flighted it.


def test_the_envelope_carries_the_runs_advisories(tmp_path: Path) -> None:
    telem = tmp_path / 'spawns.jsonl'
    _write_jsonl(
        telem,
        [
            {
                'schema_version': 1,
                'event': 'run_start',
                'run_id': 'r',
                'series_id': 's',
                'advisories': [
                    {'kind': 'gate', 'where': "[[prs]] 'pr-1'", 'message': 'integrates unverified'}
                ],
            },
            {
                'schema_version': 1,
                'event': 'run_complete',
                'run_id': 'r',
                'outcome': 'completed',
                'integrated': True,
                'halt': None,
            },
        ],
    )

    envelope = summarize_run(
        telem, run_id='r', series_id='s', outcome=RunOutcome('completed', True, EXIT_OK)
    )

    assert envelope['advisories'] == [
        {'kind': 'gate', 'where': "[[prs]] 'pr-1'", 'message': 'integrates unverified'}
    ]


def test_the_envelope_advisories_key_is_always_present(tmp_path: Path) -> None:
    """Empty, not absent — the same guarantee the dry-run envelope already gives."""
    telem = tmp_path / 'spawns.jsonl'
    _write_jsonl(
        telem, [{'schema_version': 1, 'event': 'run_start', 'run_id': 'r', 'series_id': 's'}]
    )

    envelope = summarize_run(telem, run_id='r', series_id='s', outcome=None)

    assert envelope['advisories'] == []


def test_an_advisory_from_another_run_does_not_leak_in(tmp_path: Path) -> None:
    """The ledger accumulates runs; every fold selects by run_id and this one is no exception."""
    telem = tmp_path / 'spawns.jsonl'
    _write_jsonl(
        telem,
        [
            {
                'schema_version': 1,
                'event': 'run_start',
                'run_id': 'other',
                'series_id': 's',
                'advisories': [{'kind': 'gate', 'where': 'x', 'message': 'not mine'}],
            },
            {'schema_version': 1, 'event': 'run_start', 'run_id': 'r', 'series_id': 's'},
        ],
    )

    envelope = summarize_run(telem, run_id='r', series_id='s', outcome=None)

    assert envelope['advisories'] == []


# --- convoy_status: the workspace is what makes "dead" answerable --------------------------


def test_status_reports_dead_when_the_given_workspace_lock_owner_is_gone(tmp_path: Path) -> None:
    prompts, outputs = tmp_path / 'prompts', tmp_path / 'outputs'
    prompts.mkdir()
    outputs.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    _write_jsonl(
        outputs / 'spawns.jsonl',
        [{'schema_version': 1, 'event': 'run_start', 'run_id': 'r', 'series_id': 'mcp-test'}],
    )
    workspace = tmp_path / 'ws'
    (workspace / '.git').mkdir(parents=True)
    child = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.DEVNULL)
    dead_pid = child.pid
    child.wait()
    lock_path(workspace).write_text(str(dead_pid), encoding='utf-8')

    envelope = asyncio.run(
        srv.convoy_status(str(series_file), run_id='r', workspace=str(workspace))
    )

    assert envelope['state'] == 'dead'


def test_status_without_a_workspace_answers_exactly_as_before(tmp_path: Path) -> None:
    """The server's cwd is not the caller's, so an absent workspace is never guessed at."""
    prompts, outputs = tmp_path / 'prompts', tmp_path / 'outputs'
    prompts.mkdir()
    outputs.mkdir()
    (prompts / 'pr1.md').write_text('do it')
    series_file = tmp_path / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs))
    _write_jsonl(
        outputs / 'spawns.jsonl',
        [{'schema_version': 1, 'event': 'run_start', 'run_id': 'r', 'series_id': 'mcp-test'}],
    )

    envelope = asyncio.run(srv.convoy_status(str(series_file), run_id='r'))

    assert envelope['state'] == 'running'


# --- in_flight: which PR the run is working on right now ------------------------------------


def test_the_envelope_names_the_spawn_still_in_flight(tmp_path: Path) -> None:
    telem = tmp_path / 'spawns.jsonl'
    _write_jsonl(
        telem,
        [
            {'schema_version': 1, 'event': 'run_start', 'run_id': 'r', 'series_id': 's'},
            {
                'schema_version': 1,
                'event': 'spawn_start',
                'run_id': 'r',
                'pr_id': 'pr-1',
                'role': 'implementation',
            },
            _spawn_line('r', 'pr-1'),
            {
                'schema_version': 1,
                'event': 'spawn_start',
                'run_id': 'r',
                'pr_id': 'pr-2',
                'role': 'implementation',
            },
        ],
    )

    envelope = summarize_run(telem, run_id='r', series_id='s', outcome=None)
    by_id = {pr['pr_id']: pr for pr in envelope['prs']}

    # pr-1 started and finished; pr-2 started and did not.
    assert by_id['pr-1']['in_flight'] is None
    assert by_id['pr-2']['in_flight'] == 'implementation'


def test_a_fix_spawn_in_flight_is_named_under_its_own_role(tmp_path: Path) -> None:
    telem = tmp_path / 'spawns.jsonl'
    _write_jsonl(
        telem,
        [
            {
                'schema_version': 1,
                'event': 'spawn_start',
                'run_id': 'r',
                'pr_id': 'pr-1',
                'role': 'implementation',
            },
            _spawn_line('r', 'pr-1'),
            {
                'schema_version': 1,
                'event': 'spawn_start',
                'run_id': 'r',
                'pr_id': 'pr-1',
                'role': 'fix',
            },
        ],
    )

    envelope = summarize_run(telem, run_id='r', series_id='s', outcome=None)

    assert envelope['prs'][0]['in_flight'] == 'fix'


def test_in_flight_is_always_present_and_null_on_a_finished_run(tmp_path: Path) -> None:
    telem = tmp_path / 'spawns.jsonl'
    _write_jsonl(
        telem,
        [
            {
                'schema_version': 1,
                'event': 'spawn_start',
                'run_id': 'r',
                'pr_id': 'pr-1',
                'role': 'implementation',
            },
            _spawn_line('r', 'pr-1'),
        ],
    )

    envelope = summarize_run(
        telem, run_id='r', series_id='s', outcome=RunOutcome('completed', True, EXIT_OK)
    )

    assert envelope['prs'][0]['in_flight'] is None


# --- convoy_gate --------------------------------------------------------------------------


_GATE_PY = sys.executable


def _gate_only_toml(*, red: bool = False) -> str:
    ok = f'"{_GATE_PY}" -c "exit(0)"'
    bad = f'"{_GATE_PY}" -c "import sys; sys.exit(1)"'
    second = bad if red else ok
    ok_escaped = ok.replace('\\', '\\\\').replace('"', '\\"')
    second_escaped = second.replace('\\', '\\\\').replace('"', '\\"')
    return (
        '[series]\nid = "mcp-gate"\n\n'
        f'[[checks]]\nname = "first"\nrun = "{ok_escaped}"\n'
        'blocking = true\nindependent = false\n\n'
        f'[[checks]]\nname = "second"\nrun = "{second_escaped}"\n'
        'blocking = true\nindependent = false\n'
    )


def test_convoy_gate_green_envelope(tmp_path: Path) -> None:
    series_file = tmp_path / 'gate.toml'
    series_file.write_text(_gate_only_toml(), encoding='utf-8')
    result = asyncio.run(srv.convoy_gate(str(tmp_path), str(series_file)))
    assert result['ok'] is True
    assert result['outcome'] == 'completed'
    assert [check['name'] for check in result['checks']] == ['first', 'second']
    assert result['exit_code'] == 0


def test_convoy_gate_red_envelope(tmp_path: Path) -> None:
    series_file = tmp_path / 'gate.toml'
    series_file.write_text(_gate_only_toml(red=True), encoding='utf-8')
    result = asyncio.run(srv.convoy_gate(str(tmp_path), str(series_file)))
    assert result['ok'] is False
    assert result['outcome'] == 'blocked'
    assert result['blocking_red'] is True
    assert result['checks'][1]['passed'] is False


def test_convoy_gate_matches_the_cli_envelope(tmp_path: Path) -> None:
    """The parity doctrine, asserted end to end: BOTH surfaces are actually invoked.

    The earlier form of this test recomputed the expected object from the same
    `gate_service` primitives the MCP tool calls, which could never catch a CLI-side
    divergence. This one runs `convoy gate --json` through the CLI runner and the MCP
    tool against the identical fixture and compares the parsed objects.
    """
    from typer.testing import CliRunner

    import convoy.interface.cli as cli

    series_file = tmp_path / 'gate.toml'
    series_file.write_text(_gate_only_toml(red=True), encoding='utf-8')
    cli_result = CliRunner().invoke(
        cli.app, ['gate', str(series_file), '--workspace', str(tmp_path), '--json']
    )
    mcp_result = asyncio.run(srv.convoy_gate(str(tmp_path), str(series_file)))
    assert json.loads(cli_result.stdout) == mcp_result
    assert cli_result.exit_code == mcp_result['exit_code']


def test_convoy_gate_bad_spec_is_a_usage_result_not_an_exception(tmp_path: Path) -> None:
    series_file = tmp_path / 'gate.toml'
    series_file.write_text('[series]\nid = "no-checks"\n', encoding='utf-8')
    result = asyncio.run(srv.convoy_gate(str(tmp_path), str(series_file)))
    assert result['ok'] is False
    assert result['outcome'] == 'usage'
    assert result['error_kind'] == 'spec'
    assert result['exit_code'] == 3
    assert 'checks' in result['error']


def test_convoy_gate_unknown_phase_is_a_usage_result(tmp_path: Path) -> None:
    text = (
        '[series]\nid = "scoped"\n\n'
        '[[checks]]\nname = "core-only"\nrun = "x"\nblocking = true\n'
        'independent = false\nphases = ["core"]\n'
    )
    series_file = tmp_path / 'gate.toml'
    series_file.write_text(text, encoding='utf-8')
    result = asyncio.run(srv.convoy_gate(str(tmp_path), str(series_file), phases=['nope']))
    assert result['ok'] is False
    assert result['outcome'] == 'usage'
    # Once mislabeled 'filesystem' by error_kind's OSError catch-all.
    assert result['error_kind'] == 'spec'
    assert result['series_id'] == 'scoped'
    assert result['exit_code'] == 3
    assert "'nope'" in result['error']


def test_convoy_gate_bad_workspace_is_a_usage_result_not_an_exception(tmp_path: Path) -> None:
    """A missing workspace (or one that is a file) surfaces from Popen as OSError.

    An exception escaping `_gate_impl` becomes a protocol-level tool error with no
    outcome to branch on — the most likely caller mistake must come back as data.
    """
    series_file = tmp_path / 'gate.toml'
    series_file.write_text(_gate_only_toml(), encoding='utf-8')
    for bad in (str(tmp_path / 'absent'), str(series_file)):
        result = asyncio.run(srv.convoy_gate(bad, str(series_file)))
        assert result['ok'] is False, bad
        assert result['outcome'] == 'usage', bad
        assert result['error_kind'] == 'filesystem', bad
        assert result['exit_code'] == 3, bad


def test_convoy_gate_discovers_the_project_spec_from_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    (tmp_path / '.convoy').mkdir()
    (tmp_path / '.convoy' / 'gate.toml').write_text(_gate_only_toml(), encoding='utf-8')
    result = asyncio.run(srv.convoy_gate(workspace=str(tmp_path)))
    assert result['ok'] is True
    assert result['series_id'] == 'mcp-gate'


def test_convoy_gate_without_a_spec_is_a_usage_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    result = asyncio.run(srv.convoy_gate(workspace=str(tmp_path)))
    assert result['outcome'] == 'usage'
    assert result['error_kind'] == 'spec'
    assert 'gate.toml' in result['error']


def test_convoy_gate_brief_returns_the_compact_envelope(tmp_path: Path) -> None:
    series_file = tmp_path / 'gate.toml'
    series_file.write_text(_gate_only_toml(red=True), encoding='utf-8')
    result = asyncio.run(
        srv.convoy_gate(workspace=str(tmp_path), series_file=str(series_file), brief=True)
    )
    assert set(result) == {'ok', 'outcome', 'repair_brief', 'convoy_version'}
    assert result['outcome'] == 'blocked'
    assert 'second' in result['repair_brief']
