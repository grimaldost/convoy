"""Tests for ``convoy hook`` (interface/hook.py): the gate as a PostToolUse hook.

The payloads are the ones Claude Code 2.1.258 actually sends (tests/fixtures/hooks, paths
scrubbed), so the field names pinned here are the real protocol, not a reading of it.
Every test that expects the gate to run trusts its project first, under a ``CONVOY_HOME``
inside ``tmp_path`` — the hook executes nothing in an untrusted project, and no test
touches the real home directory.
"""

import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import convoy.interface.cli as cli
import convoy.interface.gate_scaffold as gate_scaffold
import convoy.interface.hook as hook_module
from convoy import __version__
from convoy.core.spec import DEFAULT_GATE_TIMEOUT_SECONDS, Check
from convoy.interface.gate_scaffold import Toolchain, scaffold_gate
from convoy.interface.gate_service import (
    GATE_BUDGET_SECONDS,
    HOOK_MARGIN_SECONDS,
    HOOK_TIMEOUT_SECONDS,
    JUDGE_MIN_WAIT_SECONDS,
    trust_project,
)
from convoy.interface.hook import (
    HOOK_EXIT_FEEDBACK,
    HOOK_EXIT_SILENT,
    append_log,
    decide,
    parse_event,
    parse_phase_markers,
    read_transcript,
    run_hook,
)
from convoy.interface.workspace_lock import judge_lock, lock_path

FIXTURES = Path(__file__).parent / 'fixtures' / 'hooks'
runner = CliRunner()

_OK = f'"{sys.executable}" -c "exit(0)"'
_PY_QUOTED = f'"{sys.executable}"'
_RED = f'"{sys.executable}" -c "import sys; sys.stderr.write(\'hook-red-marker\'); sys.exit(1)"'


def _toml_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _check(name: str, run: str, *, phases: str = '', hint: str = '') -> str:
    lines = [
        '[[checks]]',
        f'name = "{name}"',
        f'run = {_toml_string(run)}',
        'blocking = true',
        'independent = false',
    ]
    if phases:
        lines.append(f'phases = [{phases}]')
    if hint:
        lines.append(f'repair_hint = {_toml_string(hint)}')
    return '\n'.join(lines) + '\n'


def _project(root: Path, *checks: str) -> Path:
    (root / '.convoy').mkdir(parents=True, exist_ok=True)
    spec = root / '.convoy' / 'gate.toml'
    spec.write_text('[series]\nid = "hooked"\n\n' + '\n'.join(checks), encoding='utf-8')
    return spec


def _home(tmp_path: Path) -> dict[str, str]:
    """An environment whose convoy home lives under ``tmp_path`` (trusting nothing yet)."""
    return {'CONVOY_HOME': str(tmp_path / 'convoy-home')}


def _env_trusting(tmp_path: Path, root: Path) -> dict[str, str]:
    """An environment whose convoy home trusts *root*.

    Not named ``_trusted``: CodeQL reads a call to a function named like ``trusted`` as a
    secret, and this mapping reaches the hook's stderr through the log path it locates.
    """
    env = _home(tmp_path)
    trust_project(root, env)
    return env


def _payload(cwd: Path, **over: Any) -> dict[str, Any]:
    payload = json.loads((FIXTURES / 'posttooluse_agent.json').read_text(encoding='utf-8'))
    payload['cwd'] = str(cwd)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return payload


def _log_lines(root: Path) -> list[dict[str, Any]]:
    log = root / '.convoy' / 'hook.log'
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if line]


# --- the fixture is the protocol ------------------------------------------------------------


def test_the_captured_payload_carries_the_fields_the_hook_reads() -> None:
    payload = json.loads((FIXTURES / 'posttooluse_agent.json').read_text(encoding='utf-8'))
    assert payload['hook_event_name'] == 'PostToolUse'
    assert payload['tool_name'] == 'Agent'
    assert set(payload['tool_input']) >= {'prompt', 'model'}
    assert set(payload['tool_response']) >= {'status', 'agentId', 'resolvedModel', 'usage'}
    assert payload['tool_response']['status'] == 'completed'
    assert payload['tool_use_id'].startswith('toolu_')
    assert 'cwd' in payload and 'session_id' in payload


def test_phase_markers_parse_in_order_without_duplicates() -> None:
    prompt = 'Implement it. [convoy-phase: core] then [convoy-phase: api, core] done'
    assert parse_phase_markers(prompt) == ('core', 'api')
    assert parse_phase_markers('no markers here') == ()


# --- decide: the switches --------------------------------------------------------------------


def test_a_non_dispatch_tool_is_ignored_silently(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    result = decide(_payload(root, tool_name='Bash'), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == '' and result.record is None


def test_no_project_spec_means_the_hook_is_unarmed(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    root.mkdir()
    result = decide(_payload(root), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == '' and result.record is None


def test_an_untrusted_project_is_logged_and_not_executed(tmp_path: Path) -> None:
    root = tmp_path / 'cloned'
    marker = tmp_path / 'ran.txt'
    _project(root, _check('side-effect', f'"{sys.executable}" -c "open(r\'{marker}\', \'w\')"'))
    result = decide(_payload(root), _home(tmp_path))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == ''
    assert result.record is not None
    assert result.record['outcome'] == 'untrusted'
    assert 'convoy gate --trust' in result.record['reason']
    assert not marker.exists()


def test_a_malformed_trust_list_trusts_nothing(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _home(tmp_path)
    home = Path(env['CONVOY_HOME'])
    home.mkdir()
    (home / 'hook-trust.toml').write_text('trust = [broken', encoding='utf-8')
    result = decide(_payload(root), env)
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None
    assert result.record['outcome'] == 'untrusted'
    assert 'invalid TOML' in result.record['reason']


# --- decide: the verdicts --------------------------------------------------------------------


def test_a_green_gate_says_nothing_and_records_the_firing(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    result = decide(_payload(root), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == ''
    assert result.record is not None
    assert result.record['outcome'] == 'completed'
    assert result.record['agent_id'] == 'a1b909db97960854e'
    assert result.record['model'] == 'claude-haiku-4-5-20251001'
    assert result.record['tool_use_id'] == 'toolu_01Fr9iy3TK1N1d3DwjYdgF79'
    assert result.record['convoy_version'] == __version__
    assert result.record['counts'] == {'selected': 1, 'passed': 1, 'failed': 0}
    assert isinstance(result.record['gate_ms'], int)


def test_a_red_gate_feeds_the_repair_brief_back(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK), _check('bad', _RED, hint='rerun the fixture build'))
    result = decide(_payload(root), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert result.stderr.startswith('convoy gate: BLOCKED after subagent a1b909db97960854e')
    assert 'bad' in result.stderr
    assert 'rerun the fixture build' in result.stderr
    assert 'hook-red-marker' in result.stderr
    assert result.record is not None and result.record['outcome'] == 'blocked'
    assert result.record['blocking_red'] is True


def test_a_phase_marker_in_the_brief_scopes_the_gate(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(
        root,
        _check('core-only', _RED, phases='"core"'),
        _check('api-only', _OK, phases='"api"'),
    )
    payload = _payload(root, tool_input={'prompt': 'Do the API work. [convoy-phase: api]'})
    result = decide(payload, _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None
    assert result.record['phases'] == ['api']
    assert [check['name'] for check in result.record['checks']] == ['api-only']


def test_an_unknown_phase_tag_is_reported_not_narrowed(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK, phases='"core"'))
    payload = _payload(root, tool_input={'prompt': '[convoy-phase: nope]'})
    result = decide(payload, _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'could not run' in result.stderr and 'nope' in result.stderr
    assert result.record is not None and result.record['outcome'] == 'usage'


def test_a_dispatch_that_did_not_complete_is_skipped_but_recorded(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    payload = _payload(root, tool_response={'status': 'async_launched'})
    result = decide(payload, _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == ''
    assert result.record is not None and result.record['outcome'] == 'skipped'
    assert 'async_launched' in result.record['reason']


def test_an_invalid_spec_is_loud(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    (root / '.convoy').mkdir(parents=True)
    (root / '.convoy' / 'gate.toml').write_text('not = [toml', encoding='utf-8')
    result = decide(_payload(root), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'could not run' in result.stderr


def test_the_task_alias_is_gated_too(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    result = decide(_payload(root, tool_name='Task'), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK


def test_claude_project_dir_wins_over_the_payload_cwd(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    _project(project, _check('bad', _RED))
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    result = decide(_payload(elsewhere), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK


# --- run_hook and the CLI ---------------------------------------------------------------------


def test_run_hook_appends_one_log_line_per_firing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    assert run_hook(json.dumps(_payload(root)).encode(), env) == HOOK_EXIT_SILENT
    assert run_hook(json.dumps(_payload(root)).encode(), env) == HOOK_EXIT_SILENT
    captured = capsys.readouterr()
    assert captured.out == '' and captured.err == ''
    lines = _log_lines(root)
    assert len(lines) == 2
    assert lines[0]['outcome'] == 'completed'
    assert lines[0]['spec'].endswith('gate.toml')


def test_run_hook_rejects_non_json_stdin(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_hook(b'not json', {}) == HOOK_EXIT_FEEDBACK
    assert 'not hook JSON' in capsys.readouterr().err


def test_cli_hook_reads_stdin_and_exits_with_the_hook_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED, hint='fix it'))
    env = _env_trusting(tmp_path, root)
    monkeypatch.setenv('CONVOY_HOME', env['CONVOY_HOME'])
    result = runner.invoke(cli.app, ['hook'], input=json.dumps(_payload(root)))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert result.stdout == ''
    assert 'BLOCKED' in result.stderr and 'fix it' in result.stderr
    assert _log_lines(root)[0]['outcome'] == 'blocked'


def test_cli_hook_is_silent_on_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    monkeypatch.setenv('CONVOY_HOME', _env_trusting(tmp_path, root)['CONVOY_HOME'])
    result = runner.invoke(cli.app, ['hook'], input=json.dumps(_payload(root)))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stdout == '' and result.stderr == ''


def test_cli_hook_is_silent_where_no_project_opted_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    monkeypatch.setenv('CONVOY_HOME', _home(tmp_path)['CONVOY_HOME'])
    root = tmp_path / 'proj'
    root.mkdir()
    result = runner.invoke(cli.app, ['hook'], input=json.dumps(_payload(root)))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stdout == '' and result.stderr == ''
    assert _log_lines(root) == []


def test_the_plugin_ships_the_hook() -> None:
    hooks = json.loads(
        (Path(__file__).parent.parent / 'hooks' / 'hooks.json').read_text(encoding='utf-8')
    )
    (entry,) = hooks['hooks']['PostToolUse']
    assert entry['matcher'] == 'Agent|Task'
    (command,) = entry['hooks']
    assert command['type'] == 'command'
    # The handler runs the guard, which delegates to `convoy hook` (tests/test_manifest.py).
    assert '/src/convoy/interface/hook_guard.py' in command['command']
    assert '${CLAUDE_PLUGIN_ROOT}' in command['command']
    assert command['timeout'] > 600


# --- SubagentStop: the judge ------------------------------------------------------------------


def _stop_payload(cwd: Path, transcript: Path | None, **over: Any) -> dict[str, Any]:
    payload = json.loads((FIXTURES / 'subagentstop.json').read_text(encoding='utf-8'))
    payload['cwd'] = str(cwd)
    payload['agent_transcript_path'] = str(transcript) if transcript else ''
    payload['stop_hook_active'] = False
    payload.update(over)
    return payload


def _transcript(path: Path, brief: str, *tools: str) -> Path:
    lines = [{'type': 'user', 'message': {'role': 'user', 'content': brief}}]
    for tool in tools:
        lines.append(
            {
                'type': 'assistant',
                'message': {
                    'role': 'assistant',
                    'content': [{'type': 'tool_use', 'name': tool, 'input': {}}],
                },
            }
        )
    lines.append(
        {
            'type': 'assistant',
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'done'}]},
        }
    )
    path.write_text('\n'.join(json.dumps(line) for line in lines) + '\n', encoding='utf-8')
    return path


def test_the_captured_stop_payload_carries_the_fields_the_judge_reads() -> None:
    payload = json.loads((FIXTURES / 'subagentstop.json').read_text(encoding='utf-8'))
    assert payload['hook_event_name'] == 'SubagentStop'
    assert set(payload) >= {'agent_id', 'agent_transcript_path', 'stop_hook_active', 'cwd'}


def test_read_transcript_finds_the_brief_and_the_mutation(tmp_path: Path) -> None:
    path = _transcript(tmp_path / 't.jsonl', 'Build it. [convoy-phase: core]', 'Read', 'Edit')
    facts = read_transcript(path)
    assert facts.readable and facts.mutated
    assert parse_phase_markers(facts.brief) == ('core',)
    read_only = read_transcript(_transcript(tmp_path / 'r.jsonl', 'Look around', 'Read', 'Grep'))
    assert read_only.readable and not read_only.mutated
    missing = read_transcript(tmp_path / 'nope.jsonl')
    assert not missing.readable and missing.mutated


def test_a_red_stop_blocks_the_subagent_once_with_the_brief(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED, hint='rerun the fixture build'))
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement the thing', 'Write')
    result = decide(_stop_payload(root, transcript), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert result.stderr.startswith('convoy gate: BLOCKED')
    assert 'before finishing' in result.stderr
    assert 'rerun the fixture build' in result.stderr
    assert result.record is not None
    assert result.record['event'] == 'SubagentStop'
    assert result.record['outcome'] == 'blocked'
    assert result.record['blocked_stop'] is True
    assert 'bad' in result.record['repair_brief']
    assert result.record['agent_id'] == 'a1b909db97960854e'


def test_a_residual_red_on_the_retry_lets_the_subagent_stop(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement the thing', 'Write')
    payload = _stop_payload(root, transcript, stop_hook_active=True)
    result = decide(payload, _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == ''
    assert result.record is not None
    assert result.record['outcome'] == 'blocked'
    assert result.record['blocked_stop'] is False


def test_a_green_stop_is_silent_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement the thing', 'Bash')
    result = decide(_stop_payload(root, transcript), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['outcome'] == 'completed'


def test_a_read_only_subagent_is_not_gated(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    transcript = _transcript(tmp_path / 't.jsonl', 'Survey the code', 'Read', 'Grep', 'Glob')
    result = decide(_stop_payload(root, transcript), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None
    assert result.record['outcome'] == 'skipped'
    assert 'read-only' in result.record['reason']
    assert result.record['leg'] == 'judge'


def test_a_missing_transcript_is_gated_conservatively(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    result = decide(_stop_payload(root, tmp_path / 'missing.jsonl'), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK


def test_the_phase_marker_in_the_subagent_brief_scopes_the_stop_gate(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(
        root,
        _check('core-only', _RED, phases='"core"'),
        _check('api-only', _OK, phases='"api"'),
    )
    transcript = _transcript(tmp_path / 't.jsonl', 'API work [convoy-phase: api]', 'Edit')
    result = decide(_stop_payload(root, transcript), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['phases'] == ['api']


def test_an_untrusted_project_is_not_judged_either(tmp_path: Path) -> None:
    root = tmp_path / 'cloned'
    _project(root, _check('bad', _RED))
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement', 'Write')
    result = decide(_stop_payload(root, transcript), _home(tmp_path))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['outcome'] == 'untrusted'


# --- the messenger reuses the judge's verdict ----------------------------------------------


def test_the_messenger_reuses_the_judges_verdict_instead_of_rerunning(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    stored = {
        'ts': datetime.now(UTC).isoformat(timespec='seconds'),
        'event': 'SubagentStop',
        'agent_id': 'a1b909db97960854e',
        'session_id': 'session-0000',
        'outcome': 'blocked',
        'phases': ['core'],
        'counts': {'selected': 1, 'passed': 0, 'failed': 1},
        'repair_brief': 'stored-brief-marker',
    }
    (root / '.convoy' / 'hook.log').write_text(json.dumps(stored) + '\n', encoding='utf-8')
    result = decide(_payload(root), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'stored-brief-marker' in result.stderr
    assert 'phase core' in result.stderr
    assert result.record is not None
    assert result.record['reused_from'] == stored['ts']
    assert result.record['outcome'] == 'blocked'


def test_the_messenger_ignores_a_stale_or_foreign_verdict(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    stale = {
        'ts': '2020-01-01T00:00:00+00:00',
        'event': 'SubagentStop',
        'agent_id': 'a1b909db97960854e',
        'session_id': 'session-0000',
        'outcome': 'blocked',
        'repair_brief': 'stale-marker',
    }
    foreign = {**stale, 'ts': datetime.now(UTC).isoformat(timespec='seconds'), 'agent_id': 'x'}
    (root / '.convoy' / 'hook.log').write_text(
        json.dumps(stale) + '\n' + json.dumps(foreign) + '\n', encoding='utf-8'
    )
    result = decide(_payload(root), env)
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None
    assert result.record['outcome'] == 'completed'
    assert 'reused_from' not in result.record


def test_the_plugin_ships_the_judge_too() -> None:
    hooks = json.loads(
        (Path(__file__).parent.parent / 'hooks' / 'hooks.json').read_text(encoding='utf-8')
    )
    (entry,) = hooks['hooks']['SubagentStop']
    assert 'matcher' not in entry
    (command,) = entry['hooks']
    # The handler runs the guard, which delegates to `convoy hook` (tests/test_manifest.py).
    assert '/src/convoy/interface/hook_guard.py' in command['command']
    assert command['timeout'] > 600


# --- $CONVOY_GATE_SPEC: the spec lives outside the tree it judges -----------------------------


def test_an_env_named_spec_is_judged_logged_and_trusted_at_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    spec = tmp_path / 'task' / 'gate.toml'
    spec.parent.mkdir()
    spec.write_text(
        '[series]\nid = "outside"\n\n' + _check('bad', _RED, hint='fix it'), encoding='utf-8'
    )
    env = {
        **_home(tmp_path),
        'CONVOY_GATE_SPEC': str(spec),
        'CONVOY_TRUSTED_ROOTS': str(workspace),
    }
    assert run_hook(json.dumps(_payload(workspace)).encode(), env) == HOOK_EXIT_FEEDBACK
    lines = _log_lines(workspace)
    assert len(lines) == 1
    assert lines[0]['outcome'] == 'blocked'
    assert lines[0]['spec'] == str(spec)
    assert not (spec.parent / '.convoy').exists()


def test_a_missing_env_named_spec_is_loud(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    env = {**_home(tmp_path), 'CONVOY_GATE_SPEC': str(tmp_path / 'nope.toml')}
    result = decide(_payload(workspace), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'CONVOY_GATE_SPEC' in result.stderr


# --- the review's cases -------------------------------------------------------------------


def test_the_event_is_decoded_as_utf8_whatever_the_locale(tmp_path: Path) -> None:
    root = tmp_path / 'José-proj'
    _project(root, _check('bad', _RED))
    raw = json.dumps(_payload(root), ensure_ascii=False).encode('utf-8')
    payload = parse_event(raw)
    assert isinstance(payload, dict) and payload['cwd'] == str(root)
    assert run_hook(raw, _env_trusting(tmp_path, root)) == HOOK_EXIT_FEEDBACK


def test_a_gate_that_cannot_run_lets_the_subagent_stop_on_the_retry(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK, phases='"core"'))
    env = _env_trusting(tmp_path, root)
    transcript = _transcript(tmp_path / 't.jsonl', 'work [convoy-phase: nope]', 'Write')
    first = decide(_stop_payload(root, transcript), env)
    assert first.exit_code == HOOK_EXIT_FEEDBACK
    retry = decide(_stop_payload(root, transcript, stop_hook_active=True), env)
    assert retry.exit_code == HOOK_EXIT_SILENT
    assert retry.record is not None and retry.record['outcome'] == 'usage'
    assert 'may stop' in retry.record['reason']


def test_the_gate_runs_in_the_project_root_not_the_session_cwd(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    here = f'"{sys.executable}"'
    _project(
        root,
        _check(
            'where',
            here
            + ' -c "import os,sys; '
            + "sys.exit(0 if os.path.basename(os.getcwd()) == 'proj' else 1)\"",
        ),
    )
    env = _env_trusting(tmp_path, root)
    deep = root / 'docs' / 'deep'
    deep.mkdir(parents=True)
    result = decide(_payload(deep), env)
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['outcome'] == 'completed'
    assert result.record['workspace'] == str(root.resolve())


def test_an_unknown_tool_counts_as_a_write(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    transcript = _transcript(tmp_path / 't.jsonl', 'write via mcp', 'Read', 'mcp__fs__create_file')
    result = decide(_stop_payload(root, transcript), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    nested = _transcript(tmp_path / 'n.jsonl', 'delegate', 'Agent')
    assert (
        decide(_stop_payload(root, nested), _env_trusting(tmp_path, root)).exit_code
        == HOOK_EXIT_FEEDBACK
    )


def test_a_naive_or_foreign_session_verdict_is_not_reused(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    naive = {
        'ts': '2026-09-02T10:00:00',
        'event': 'SubagentStop',
        'agent_id': 'a1b909db97960854e',
        'session_id': 'session-0000',
        'outcome': 'blocked',
        'repair_brief': 'naive-marker',
    }
    other_session = {**naive, 'ts': datetime.now(UTC).isoformat(), 'session_id': 'someone-else'}
    (root / '.convoy' / 'hook.log').write_text(
        json.dumps(naive) + '\n' + json.dumps(other_session) + '\n', encoding='utf-8'
    )
    result = decide(_payload(root), env)
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and 'reused_from' not in result.record


def test_the_messenger_reuses_a_skipped_verdict_silently(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    env = _env_trusting(tmp_path, root)
    skipped = {
        'ts': datetime.now(UTC).isoformat(),
        'event': 'SubagentStop',
        'agent_id': 'a1b909db97960854e',
        'session_id': 'session-0000',
        'outcome': 'skipped',
    }
    (root / '.convoy' / 'hook.log').write_text(json.dumps(skipped) + '\n', encoding='utf-8')
    result = decide(_payload(root), env)
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['outcome'] == 'skipped'


def test_an_untrusted_project_gets_no_log_written_into_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / 'cloned'
    _project(root, _check('bad', _RED))
    assert run_hook(json.dumps(_payload(root)).encode(), _home(tmp_path)) == HOOK_EXIT_SILENT
    assert not (root / '.convoy' / 'hook.log').exists()
    assert capsys.readouterr().err == ''


def test_a_spec_changed_since_trust_is_refused_loudly(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    spec = _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    spec.write_text(spec.read_text(encoding='utf-8').replace('"ok"', '"ok2"'), encoding='utf-8')
    result = decide(_payload(root), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'changed since' in result.stderr
    assert result.record is not None and result.record['outcome'] == 'spec_changed'


def test_a_driven_workspace_is_refused(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    (root / '.git').mkdir()
    lock_path(root).write_text('12345', encoding='utf-8')
    result = decide(_payload(root), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'convoy run holds' in result.stderr


def test_the_real_subagent_transcript_reads_as_a_read_only_haiku_agent() -> None:
    facts = read_transcript(FIXTURES / 'agent_transcript.jsonl')
    assert facts.readable and not facts.mutated
    assert facts.brief.startswith('Reply with the single word DONE')
    assert facts.model == 'claude-haiku-4-5-20251001'


def test_a_list_content_brief_still_scopes_the_gate(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(
        root, _check('core-only', _RED, phases='"core"'), _check('api-only', _OK, phases='"api"')
    )
    path = tmp_path / 't.jsonl'
    lines = [
        {
            'type': 'user',
            'message': {
                'role': 'user',
                'content': [{'type': 'text', 'text': 'api [convoy-phase: api]'}],
            },
        },
        {
            'type': 'assistant',
            'message': {
                'role': 'assistant',
                'model': 'm',
                'content': [{'type': 'tool_use', 'name': 'Edit', 'input': {}}],
            },
        },
    ]
    path.write_text('\n'.join(json.dumps(line) for line in lines) + '\n', encoding='utf-8')
    result = decide(_stop_payload(root, path), _env_trusting(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['phases'] == ['api']
    assert result.record['model'] == 'm'


def test_every_record_carries_the_attestation_fields(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    transcript = _transcript(tmp_path / 't.jsonl', 'work', 'Write')
    result = decide(_stop_payload(root, transcript), _env_trusting(tmp_path, root))
    record = result.record
    assert record is not None
    for key in (
        'leg',
        'exit_code',
        'stop_hook_active',
        'cwd',
        'workspace',
        'spec',
        'spec_sha256',
        'series_id',
        'checks',
    ):
        assert key in record, key
    assert record['exit_code'] == HOOK_EXIT_FEEDBACK
    assert record['checks'][0].keys() >= {
        'name',
        'passed',
        'blocking',
        'independent',
        'exit_code',
        'timed_out',
        'detail',
    }
    assert record['ts'].endswith('+00:00') and '.' in record['ts']


def test_no_recorded_fixture_carries_a_user_profile_path() -> None:
    # The recorded hook fixtures are real captures; a profile path would publish the
    # capturing machine's account name.
    profile = re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+|/Users/|/home/', re.IGNORECASE)
    for path in sorted(FIXTURES.iterdir()):
        text = path.read_text(encoding='utf-8')
        assert not profile.search(text), f'{path.name} carries a user profile path'


# --- concurrent firings in one tree (CONV-B62) ------------------------------------------------
#
# Several subagents stopping at once each fire the judge. The gate is replaced by a probe
# that wraps the real one and counts how many firings are inside it at the same moment, so
# "never at once" is measured rather than inferred from timings.


@dataclass
class _GateProbe:
    active: int = 0
    peak: int = 0
    entered: threading.Event = field(default_factory=threading.Event)
    guard: threading.Lock = field(default_factory=threading.Lock)


def _probe_the_gate(monkeypatch: pytest.MonkeyPatch, hold_seconds: float) -> _GateProbe:
    probe = _GateProbe()
    real_run_gate = hook_module.run_gate

    def probing(spec: Any, workspace: Path, phases: tuple[str, ...] = ()) -> Any:
        with probe.guard:
            probe.active += 1
            probe.peak = max(probe.peak, probe.active)
        probe.entered.set()
        try:
            time.sleep(hold_seconds)
            return real_run_gate(spec, workspace, phases)
        finally:
            with probe.guard:
                probe.active -= 1

    monkeypatch.setattr(hook_module, 'run_gate', probing)
    return probe


def _writer_stop(tmp_path: Path, root: Path, agent: str, **over: Any) -> bytes:
    transcript = _transcript(tmp_path / f'{agent}.jsonl', f'work for {agent}', 'Edit')
    return json.dumps(_stop_payload(root, transcript, agent_id=agent, **over)).encode()


def _fire_in_thread(
    raw: bytes, env: dict[str, str], codes: dict[str, int], key: str
) -> threading.Thread:
    thread = threading.Thread(
        target=lambda: codes.__setitem__(key, run_hook(raw, env)), daemon=True
    )
    thread.start()
    return thread


def test_two_judges_in_one_tree_take_turns_and_the_log_stays_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    probe = _probe_the_gate(monkeypatch, hold_seconds=0.3)
    codes: dict[str, int] = {}
    threads = [
        _fire_in_thread(_writer_stop(tmp_path, root, agent), env, codes, agent)
        for agent in ('agent-a', 'agent-b')
    ]
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()
    assert codes == {'agent-a': HOOK_EXIT_SILENT, 'agent-b': HOOK_EXIT_SILENT}
    assert probe.peak == 1, 'two firings ran the gate in one tree at the same time'
    lines = _log_lines(root)  # every line parses as JSON, or this raises
    assert sorted(line['agent_id'] for line in lines) == ['agent-a', 'agent-b']
    assert {line['outcome'] for line in lines} == {'completed'}


def test_a_judge_that_waits_out_the_bound_exits_2_and_nothing_interleaves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    # The bound is read when a firing starts waiting; a short one keeps the test fast.
    monkeypatch.setattr(hook_module, 'JUDGE_WAIT_SECONDS', 0.2)
    monkeypatch.setattr(hook_module, 'JUDGE_POLL_SECONDS', 0.02)
    probe = _probe_the_gate(monkeypatch, hold_seconds=1.5)
    codes: dict[str, int] = {}
    holder = _fire_in_thread(_writer_stop(tmp_path, root, 'agent-a'), env, codes, 'agent-a')
    assert probe.entered.wait(timeout=10)
    started = time.monotonic()
    loser = run_hook(_writer_stop(tmp_path, root, 'agent-b'), env)
    waited = time.monotonic() - started
    holder.join(timeout=30)
    assert not holder.is_alive()
    assert codes == {'agent-a': HOOK_EXIT_SILENT}
    assert loser == HOOK_EXIT_FEEDBACK
    assert probe.peak == 1, 'the loser ran the gate while the holder was still in it'
    assert waited >= 0.2
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'judge.lock' in err
    # The subagent cannot tell whether the holder runs, so it is told only to stop again.
    assert 'stopping again retries' in err and 'by hand' not in err
    by_agent = {line['agent_id']: line for line in _log_lines(root)}
    assert by_agent['agent-a']['outcome'] == 'completed'
    # Its own outcome, not `usage`: a busy tree is not a gate that is broken.
    assert by_agent['agent-b']['outcome'] == 'busy'
    assert 'judge.lock' in by_agent['agent-b']['error']
    assert by_agent['agent-b']['exit_code'] == HOOK_EXIT_FEEDBACK


def test_an_append_waits_for_the_append_lock(tmp_path: Path) -> None:
    """The loser's line is written outside the judge lock; the append lock keeps it whole."""
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    log = root / '.convoy' / 'hook.log'
    failures: list[str | None] = []
    with judge_lock(log.with_name('hook.log.lock'), wait_seconds=0, poll_seconds=0.01):
        writer = threading.Thread(
            target=lambda: failures.append(append_log(log, {'line': 1})), daemon=True
        )
        writer.start()
        writer.join(timeout=0.3)
        assert writer.is_alive() and not log.exists(), 'the append did not wait for the lock'
    writer.join(timeout=10)
    assert failures == [None]
    assert _log_lines(root) == [{'line': 1}]


def test_a_judge_lock_still_held_on_the_retry_is_recorded_as_an_ungated_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One blocked stop, then it may stop, as for any gate that could not run.

    The repair round stays the bound: the subagent cannot free the lock, and blocking every
    stop until it frees would spin a gate that leaves no room to wait. But the stop is
    recorded as `busy`, apart from a gate that could not run, so the log counts the
    subagents that stopped without a verdict because the tree was busy.
    """
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    monkeypatch.setattr(hook_module, 'JUDGE_WAIT_SECONDS', 0.05)
    monkeypatch.setattr(hook_module, 'JUDGE_POLL_SECONDS', 0.01)
    lock = root / '.convoy' / hook_module.JUDGE_LOCK_NAME
    with judge_lock(lock, wait_seconds=0, poll_seconds=0.01):
        first = run_hook(_writer_stop(tmp_path, root, 'agent-a'), env)
        retry = run_hook(_writer_stop(tmp_path, root, 'agent-a', stop_hook_active=True), env)
    assert (first, retry) == (HOOK_EXIT_FEEDBACK, HOOK_EXIT_SILENT)
    blocked, released = _log_lines(root)
    assert blocked['outcome'] == released['outcome'] == 'busy'
    assert released['reason'] == 'judge lock still held on the retry; the subagent stops ungated'


def test_a_firing_that_runs_no_gate_does_not_wait_for_the_judge_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _env_trusting(tmp_path, root)
    monkeypatch.setattr(hook_module, 'JUDGE_WAIT_SECONDS', 5.0)
    reader = _transcript(tmp_path / 'reader.jsonl', 'look around', 'Read', 'Grep')
    lock = root / '.convoy' / hook_module.JUDGE_LOCK_NAME
    with judge_lock(lock, wait_seconds=0, poll_seconds=0.01):
        started = time.monotonic()
        code = run_hook(json.dumps(_stop_payload(root, reader)).encode(), env)
        assert time.monotonic() - started < 2.0, 'a read-only stop waited for the judge lock'
    assert code == HOOK_EXIT_SILENT
    assert _log_lines(root)[0]['outcome'] == 'skipped'


def test_a_scaffolded_tree_stays_clean_while_a_judge_holds_its_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run refuses an untracked file, and a gate may check the tree is clean."""
    root = tmp_path / 'proj'
    root.mkdir()
    scaffold_gate(root, {})

    def git(*args: str) -> str:
        done = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=False)
        assert done.returncode == 0, done.stderr
        return done.stdout

    git('init', '-q')
    git('config', 'user.email', 'test@example.com')
    git('config', 'user.name', 'Test User')
    git('add', '-A')
    git('commit', '-q', '-m', 'scaffold the gate')
    env = _env_trusting(tmp_path, root)
    seen: list[str] = []
    real_run_gate = hook_module.run_gate

    def probing(spec: Any, workspace: Path, phases: tuple[str, ...] = ()) -> Any:
        assert (root / '.convoy' / hook_module.JUDGE_LOCK_NAME).exists()
        seen.append(git('status', '--porcelain', '--untracked-files=all'))
        return real_run_gate(spec, workspace, phases)

    monkeypatch.setattr(hook_module, 'run_gate', probing)
    run_hook(_writer_stop(tmp_path, root, 'agent-a'), env)
    assert seen == ['']
    assert git('status', '--porcelain', '--untracked-files=all') == ''


def test_the_judge_waits_a_third_of_the_hook_timeout() -> None:
    """The docs state the bound as 600 s; this keeps the number and the constant together."""
    assert hook_module.JUDGE_WAIT_SECONDS == hook_module.HOOK_TIMEOUT_SECONDS / 3 == 600


@pytest.mark.parametrize('worst_case', [0, 1, 300, 1200, 1500, 1769, 1770, 1800, 5400])
def test_the_wait_and_the_gate_together_fit_the_hook_timeout(worst_case: int) -> None:
    """A waiter that gets the lock after the whole wait still has its gate's worst case left."""
    wait = hook_module.judge_wait_seconds(worst_case)
    assert 0 <= wait <= hook_module.JUDGE_WAIT_SECONDS
    if worst_case <= hook_module.HOOK_TIMEOUT_SECONDS - hook_module.HOOK_MARGIN_SECONDS:
        assert (
            wait + worst_case <= hook_module.HOOK_TIMEOUT_SECONDS - hook_module.HOOK_MARGIN_SECONDS
        )
    else:
        assert wait == 0


def test_a_gate_that_fills_the_hook_timeout_does_not_wait_for_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Waiting any time first would let the firing outlast the hook timeout, in silence."""
    root = tmp_path / 'proj'
    spec = _project(root, _check('ok', _OK))
    governance = f'[governance]\ntimeout_seconds = {hook_module.HOOK_TIMEOUT_SECONDS}\n\n'
    spec.write_text(
        spec.read_text(encoding='utf-8').replace('[[checks]]', governance + '[[checks]]', 1),
        encoding='utf-8',
    )
    env = _env_trusting(tmp_path, root)
    monkeypatch.setattr(hook_module, 'JUDGE_WAIT_SECONDS', 30.0)
    lock = root / '.convoy' / hook_module.JUDGE_LOCK_NAME
    with judge_lock(lock, wait_seconds=0, poll_seconds=0.01):
        started = time.monotonic()
        code = run_hook(_writer_stop(tmp_path, root, 'agent-a'), env)
        assert time.monotonic() - started < 5.0, (
            'the firing waited though its gate fills the timeout'
        )
    assert code == HOOK_EXIT_FEEDBACK
    assert 'judge.lock' in capsys.readouterr().err
    assert _log_lines(root)[0]['outcome'] == 'busy'


# --- the gate budget: one threshold for the scaffold, validate and the wait (CONV-B61/B62) ----


def test_the_gate_budget_leaves_the_margin_and_the_minimum_wait() -> None:
    """The budget is five checks at the default 300 s, so a Python scaffold keeps 300 s."""
    assert (
        GATE_BUDGET_SECONDS + HOOK_MARGIN_SECONDS + JUDGE_MIN_WAIT_SECONDS == HOOK_TIMEOUT_SECONDS
    )
    assert GATE_BUDGET_SECONDS == 5 * DEFAULT_GATE_TIMEOUT_SECONDS
    assert JUDGE_MIN_WAIT_SECONDS > 0
    assert hook_module.HOOK_MARGIN_SECONDS == HOOK_MARGIN_SECONDS


@pytest.mark.parametrize('worst_case', [0, 1, 300, 1200, 1499, 1500])
def test_a_gate_inside_the_budget_leaves_a_firing_the_minimum_wait(worst_case: int) -> None:
    assert hook_module.judge_wait_seconds(worst_case) >= JUDGE_MIN_WAIT_SECONDS


def _six_check_scaffold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, str]]:
    """What ``convoy gate --init --independent oracle`` writes for a Python project, made runnable.

    Five toolchain checks plus the oracle, with the timeout the scaffold chose. The checks
    and the oracle are replaced by ones that pass with this interpreter, so the test runs
    no toolchain.
    """
    root = tmp_path / 'proj'
    root.mkdir()
    five = Toolchain('python', tuple(Check(name=f'c{i}', run=_OK, blocking=True) for i in range(5)))
    monkeypatch.setattr(gate_scaffold, 'detect_toolchain', lambda _root: five)
    oracles = tmp_path / 'oracles'
    env = {**_home(tmp_path), 'CONVOY_ORACLES': str(oracles)}
    scaffold_gate(root, env, independent='oracle')
    (oracles / 'oracle.py').write_text('raise SystemExit(0)\n', encoding='utf-8')
    spec_path = root / '.convoy' / 'gate.toml'
    interpreter = f'run = "\\"{sys.executable}\\" "'.replace('\\', '\\\\')
    text = spec_path.read_text(encoding='utf-8').replace('run = "python "', interpreter, 1)
    spec_path.write_text(text, encoding='utf-8')
    trust_project(root, env)
    return root, env


def test_two_judges_under_the_six_check_scaffold_take_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loser waits for the holder's gate, then runs its own.

    Six checks at 300 s filled the 1800 s hook timeout, so the second firing did not wait
    at all: it exited 2 at once, and its retry, seconds later and with the first gate still
    running, let the subagent stop without a gate.
    """
    root, env = _six_check_scaffold(tmp_path, monkeypatch)
    monkeypatch.setattr(hook_module, 'JUDGE_POLL_SECONDS', 0.02)
    probe = _probe_the_gate(monkeypatch, hold_seconds=1.0)
    codes: dict[str, int] = {}
    holder = _fire_in_thread(_writer_stop(tmp_path, root, 'agent-a'), env, codes, 'agent-a')
    assert probe.entered.wait(timeout=10)
    started = time.monotonic()
    loser = run_hook(_writer_stop(tmp_path, root, 'agent-b'), env)
    waited = time.monotonic() - started
    holder.join(timeout=60)
    assert not holder.is_alive()
    assert codes == {'agent-a': HOOK_EXIT_SILENT}
    assert loser == HOOK_EXIT_SILENT
    assert probe.peak == 1, 'the loser ran the gate while the holder was still in it'
    assert waited >= 0.5, 'the loser did not wait for the holder'
    by_agent = {line['agent_id']: line for line in _log_lines(root)}
    assert by_agent['agent-a']['outcome'] == by_agent['agent-b']['outcome'] == 'completed'
    assert by_agent['agent-b']['counts'] == {'selected': 6, 'passed': 6, 'failed': 0}


# --- a worktree-isolated subagent is judged in its own worktree (CONV-B75) -------------------

# Red only where ``broken.txt`` exists in the tree the gate runs in.
_RED_IF_BROKEN = (
    f'"{sys.executable}" -c "import pathlib, sys; '
    "sys.exit(1 if pathlib.Path('broken.txt').exists() else 0)\""
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com', *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _project_with_worktree(tmp_path: Path, *checks: str) -> tuple[Path, Path]:
    """A git project whose committed spec carries *checks*, and a linked worktree under it.

    The worktree sits where Claude Code puts an isolated agent's:
    ``<project>/.claude/worktrees/<id>``.
    """
    project = tmp_path / 'project'
    _project(project, *checks)
    _git(project, 'init', '-q', '-b', 'main')
    _git(project, 'add', '-A')
    _git(project, 'commit', '-q', '-m', 'spec')
    worktree = project / '.claude' / 'worktrees' / 'agent-1'
    _git(project, 'worktree', 'add', '-q', '-b', 'agent-1', str(worktree))
    return project, worktree


def test_a_worktree_agent_is_judged_in_its_own_worktree(tmp_path: Path) -> None:
    """The probe's case: payload cwd is the worktree, ``$CLAUDE_PROJECT_DIR`` the project.

    The only red is in the worktree, so a gate run in the main checkout passes it.
    """
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    (worktree / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(worktree, transcript), env)
    assert result.record is not None
    assert result.record['workspace'] == str(worktree.resolve())
    assert result.record['spec'] == str(worktree.resolve() / '.convoy' / 'gate.toml')
    assert result.record['outcome'] == 'blocked'
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    # The brief names the tree it judged, so a reader can tell which one that was.
    assert str(worktree.resolve()) in result.stderr
    assert str(worktree.resolve() / '.convoy' / 'gate.toml') in result.stderr


def test_the_main_checkout_agent_is_still_judged_in_the_main_checkout(tmp_path: Path) -> None:
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    (worktree / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(project, transcript), env)
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None
    assert result.record['workspace'] == str(project.resolve())


def test_a_worktree_that_rewrote_its_gate_is_refused_loudly(tmp_path: Path) -> None:
    """A worktree inherits its main checkout's trust only for the spec hash that was pinned."""
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    spec = worktree / '.convoy' / 'gate.toml'
    spec.write_text(spec.read_text(encoding='utf-8').replace('"clean"', '"lax"'), encoding='utf-8')
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(worktree, transcript), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'differs from the spec trusted for' in result.stderr
    assert result.record is not None and result.record['outcome'] == 'spec_changed'


def test_a_worktree_of_an_untrusted_project_is_not_judged(tmp_path: Path) -> None:
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_home(tmp_path), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(worktree, transcript), env)
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['outcome'] == 'untrusted'


def test_run_hook_logs_a_worktree_verdict_in_its_anchors_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The worktree is deleted when its agent is done; the anchor's log outlives it."""
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    (worktree / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    raw = json.dumps(_stop_payload(worktree, transcript)).encode()
    assert run_hook(raw, env) == HOOK_EXIT_FEEDBACK
    assert f'judged {worktree.resolve()}' in capsys.readouterr().err
    (line,) = _log_lines(project)
    assert line['outcome'] == 'blocked'
    assert line['workspace'] == str(worktree.resolve())
    assert line['anchor'] == str(project.resolve())
    assert _log_lines(worktree) == []


# --- the review of CONV-B75 -------------------------------------------------------------------

# An independent check whose oracle lives out of tree, under the default oracles dir.
_ORACLE_CHECK = (
    '\n'.join(
        [
            '[[checks]]',
            'name = "oracle"',
            f'run = {_toml_string(f"{_PY_QUOTED} ${{CONVOY_ORACLES}}/oracle1.py")}',
            'asset = "${CONVOY_ORACLES}/oracle1.py"',
            'blocking = true',
            'independent = true',
        ]
    )
    + '\n'
)


def test_an_oracle_check_in_a_worktree_runs_the_projects_oracle(tmp_path: Path) -> None:
    """MAJOR 1: the default oracles dir keys on the anchor, not on the worktree's name."""
    project, worktree = _project_with_worktree(tmp_path, _ORACLE_CHECK)
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    oracles = Path(env['CONVOY_HOME']) / 'oracles' / 'project'
    oracles.mkdir(parents=True)
    (oracles / 'oracle1.py').write_text('raise SystemExit(0)\n', encoding='utf-8')
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    for cwd in (project, worktree):
        result = decide(_stop_payload(cwd, transcript), env)
        assert result.record is not None
        assert result.record['outcome'] == 'completed', (cwd, result.record)
        assert result.exit_code == HOOK_EXIT_SILENT


@pytest.mark.parametrize('eol', [b'\r\n', b'\r'], ids=['crlf', 'cr'])
def test_a_worktree_spec_differing_only_in_line_endings_is_judged(
    tmp_path: Path, eol: bytes
) -> None:
    """MAJOR 2 (i): git's eol conversion is no difference in the gate."""
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    (worktree / 'broken.txt').write_text('red\n', encoding='utf-8')
    spec = worktree / '.convoy' / 'gate.toml'
    spec.write_bytes(spec.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', eol))
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(worktree, transcript), env)
    assert result.record is not None and result.record['outcome'] == 'blocked'


def test_a_differing_worktree_spec_is_refused_once_then_let_through(tmp_path: Path) -> None:
    """MAJOR 2 (ii, iii): loud once, addressed to the operator; the retry stops, recorded."""
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    spec = worktree / '.convoy' / 'gate.toml'
    spec.write_text(spec.read_text(encoding='utf-8').replace('"clean"', '"lax"'), encoding='utf-8')
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    first = run_hook(json.dumps(_stop_payload(worktree, transcript)).encode(), env)
    assert first == HOOK_EXIT_FEEDBACK
    retry_payload = _stop_payload(worktree, transcript, stop_hook_active=True)
    retry = decide(retry_payload, env)
    assert retry.exit_code == HOOK_EXIT_SILENT
    assert retry.record is not None and retry.record['outcome'] == 'spec_changed'
    assert run_hook(json.dumps(retry_payload).encode(), env) == HOOK_EXIT_SILENT
    lines = _log_lines(project)
    assert [line['outcome'] for line in lines] == ['spec_changed', 'spec_changed']
    assert str(project.resolve()) in lines[0]['reason']
    assert '--trust' not in lines[0]['reason']
    # The orchestrator hears of it from the messenger, which reads the anchor's log.
    messenger = decide(
        _payload(
            project,
            tool_response={'agentId': lines[0]['agent_id']},
            session_id=lines[0]['session_id'],
        ),
        env,
    )
    assert messenger.exit_code == HOOK_EXIT_FEEDBACK
    assert 'REFUSED' in messenger.stderr and 'differs from the spec trusted for' in messenger.stderr


def test_the_refusal_message_never_tells_the_subagent_to_trust(tmp_path: Path) -> None:
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    spec = worktree / '.convoy' / 'gate.toml'
    spec.write_text(spec.read_text(encoding='utf-8') + '\n# edited\n', encoding='utf-8')
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(worktree, transcript), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert '--trust' not in result.stderr
    assert 'operator' in result.stderr
    assert 'changed since this machine trusted it' not in result.stderr


def test_a_session_in_a_linked_worktree_still_gates_its_agents_worktrees(tmp_path: Path) -> None:
    """MAJOR 3, probe A: the session project S is a worktree of M; the agent's is made from S."""
    main, _worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    session = tmp_path / 'session'
    _git(main, 'worktree', 'add', '-q', '-b', 'session', str(session))
    agent = session / '.claude' / 'worktrees' / 'agent-2'
    _git(session, 'worktree', 'add', '-q', '-b', 'agent-2', str(agent))
    (agent / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = {**_env_trusting(tmp_path, session), 'CLAUDE_PROJECT_DIR': str(session)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(agent, transcript), env)
    assert result.record is not None
    assert result.record['outcome'] == 'blocked'
    assert result.record['workspace'] == str(agent.resolve())
    assert result.record['anchor'] == str(session.resolve())


def _write_unpinned_entry(env: dict[str, str], root: Path) -> None:
    """A trust entry for *root* with no pinned spec hash."""
    home = Path(env['CONVOY_HOME'])
    home.mkdir(parents=True, exist_ok=True)
    (home / 'hook-trust.toml').write_text(
        f'[[projects]]\nroot = {json.dumps(root.resolve().as_posix())}\n', encoding='utf-8'
    )


def _env_vouching(tmp_path: Path, project: Path, trust: str) -> dict[str, str]:
    """An environment that trusts *project* without a pin: vouched for, or an unpinned entry."""
    env = _home(tmp_path)
    if trust == 'vouched':
        env['CONVOY_TRUSTED_ROOTS'] = str(project)
    else:
        _write_unpinned_entry(env, project)
    return env


@pytest.mark.parametrize('project_dir', [True, False], ids=['project-dir', 'no-project-dir'])
@pytest.mark.parametrize('trust', ['vouched', 'unpinned'])
def test_a_project_that_cannot_vouch_for_a_worktree_spec_judges_the_worktree(
    tmp_path: Path, trust: str, project_dir: bool
) -> None:
    """Third review, MAJOR (S8, S8b): the project's own spec runs in the agent's worktree.

    The worktree's copy of the spec cannot be vouched for by an entry with no pin, so the
    project's spec is judged instead, and it runs where the agent worked: the only red is
    there.
    """
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    (worktree / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = _env_vouching(tmp_path, project, trust)
    if project_dir:
        env['CLAUDE_PROJECT_DIR'] = str(project)
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(worktree, transcript), env)
    assert result.record is not None
    assert result.record['outcome'] == 'blocked'
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert result.record['workspace'] == str(worktree.resolve())
    assert result.record['spec'] == str(project.resolve() / '.convoy' / 'gate.toml')
    assert result.record['anchor'] == str(project.resolve())
    assert result.record['tree_mismatch'] is False
    assert result.record['fallback_from'] == str(worktree.resolve() / '.convoy' / 'gate.toml')
    assert f'judged {worktree.resolve()}' in result.stderr
    assert 'not vouched for' in result.stderr


def _project_with_untracked_spec(
    tmp_path: Path, *checks: str, sibling: bool = False
) -> tuple[Path, Path]:
    """A git project whose spec is written but not committed, and a linked worktree of it.

    The state `convoy gate --init` leaves until the operator commits: the worktree has no
    spec. *sibling* puts the worktree beside the project instead of under it.
    """
    project = tmp_path / 'project'
    project.mkdir()
    _git(project, 'init', '-q', '-b', 'main')
    (project / 'README').write_text('x\n', encoding='utf-8')
    _git(project, 'add', '-A')
    _git(project, 'commit', '-q', '-m', 'init')
    _project(project, *checks)
    worktree = tmp_path / 'agent-wt' if sibling else project / '.claude' / 'worktrees' / 'agent-3'
    _git(project, 'worktree', 'add', '-q', '-b', 'agent-3', str(worktree))
    return project, worktree


@pytest.mark.parametrize('project_dir', [True, False], ids=['project-dir', 'no-project-dir'])
@pytest.mark.parametrize('sibling', [False, True], ids=['nested', 'sibling'])
def test_an_untracked_project_spec_judges_the_agents_worktree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sibling: bool, project_dir: bool
) -> None:
    """Third review, MAJOR (S3, S3b, S6) and MINOR (S6b).

    The worktree has no spec, so discovery finds the project's: on the walk (nested), from
    `$CLAUDE_PROJECT_DIR`, or from git's main checkout (sibling, no project dir). It runs in
    the agent's worktree and is logged in the project; nothing is written into the worktree.
    """
    project, worktree = _project_with_untracked_spec(
        tmp_path, _check('clean', _RED_IF_BROKEN), sibling=sibling
    )
    (worktree / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = _env_trusting(tmp_path, project)
    if project_dir:
        env['CLAUDE_PROJECT_DIR'] = str(project)
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    raw = json.dumps(_stop_payload(worktree, transcript)).encode()
    assert run_hook(raw, env) == HOOK_EXIT_FEEDBACK
    spec = project.resolve() / '.convoy' / 'gate.toml'
    assert f'judged {worktree.resolve()} against {spec}' in capsys.readouterr().err
    (line,) = _log_lines(project)
    assert line['outcome'] == 'blocked'
    assert line['workspace'] == str(worktree.resolve())
    assert line['spec'] == str(spec)
    assert line['anchor'] == str(project.resolve())
    assert line['agent_tree'] == str(worktree.resolve())
    assert line['tree_mismatch'] is False
    assert not (worktree / '.convoy').exists()


def test_a_worktree_judged_by_the_projects_spec_does_not_wait_for_the_projects_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two trees, two judge locks: a gate running in the project does not hold the worktree's."""
    project, worktree = _project_with_untracked_spec(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    monkeypatch.setattr(hook_module, 'JUDGE_WAIT_SECONDS', 0.05)
    monkeypatch.setattr(hook_module, 'JUDGE_POLL_SECONDS', 0.01)
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    held = project / '.convoy' / hook_module.JUDGE_LOCK_NAME
    with judge_lock(held, wait_seconds=0, poll_seconds=0.01):
        code = run_hook(json.dumps(_stop_payload(worktree, transcript)).encode(), env)
    assert code == HOOK_EXIT_SILENT
    (line,) = _log_lines(project)
    assert line['outcome'] == 'completed'
    assert line['workspace'] == str(worktree.resolve())


def test_a_nested_repository_is_judged_in_the_project_and_says_so(tmp_path: Path) -> None:
    """A separate repository under the project is no worktree of it: the project is judged.

    A green there says which tree it judged, on stderr and in `tree_mismatch`.
    """
    project = tmp_path / 'project'
    _project(project, _check('clean', _RED_IF_BROKEN))
    _git(project, 'init', '-q', '-b', 'main')
    nested = project / 'vendor' / 'lib'
    nested.mkdir(parents=True)
    _git(nested, 'init', '-q', '-b', 'main')
    (nested / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(nested, transcript), env)
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['outcome'] == 'completed'
    assert result.record['workspace'] == str(project.resolve())
    assert result.record['tree_mismatch'] is True
    assert result.record['agent_tree'] == str(nested.resolve())
    assert f'judged {project.resolve()}' in result.stderr
    assert str(nested.resolve()) in result.stderr


# Writes side-effect.txt in the tree it runs in: proof that a check ran.
_TOUCH = f"{_PY_QUOTED} -c \"open('side-effect.txt', 'w').close()\""


@pytest.mark.parametrize('trust', ['vouched', 'unpinned'])
def test_a_worktree_spec_nothing_trusted_can_vouch_for_leaves_a_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], trust: str
) -> None:
    """Third review, MINOR (S4): the project is trusted, has no spec, the worktree has one.

    Nothing trusted vouches for the worktree's spec, so it is not run; the firing says so on
    stderr (exit 0) and leaves an `untrusted` line in the trusted project's log.
    """
    project = tmp_path / 'project'
    project.mkdir()
    _git(project, 'init', '-q', '-b', 'main')
    (project / 'README').write_text('x\n', encoding='utf-8')
    _git(project, 'add', '-A')
    _git(project, 'commit', '-q', '-m', 'init')
    worktree = project / '.claude' / 'worktrees' / 'agent-4'
    _git(project, 'worktree', 'add', '-q', '-b', 'agent-4', str(worktree))
    _project(worktree, _check('touch', _TOUCH))
    env = {**_env_vouching(tmp_path, project, trust), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    raw = json.dumps(_stop_payload(worktree, transcript)).encode()
    assert run_hook(raw, env) == HOOK_EXIT_SILENT
    err = capsys.readouterr().err
    assert f'convoy gate: {worktree.resolve()} was not judged' in err
    assert f'`convoy gate --trust` in {project.resolve()}' in err
    (line,) = _log_lines(project)
    assert line['outcome'] == 'untrusted'
    assert line['agent_tree'] == str(worktree.resolve())
    assert not (worktree / 'side-effect.txt').exists()
    assert not (worktree / '.convoy' / 'hook.log').exists()


def test_a_worktree_of_an_untrusted_project_leaves_no_file(tmp_path: Path) -> None:
    """The per-machine switch is unchanged: an untrusted project gets nothing written."""
    project, worktree = _project_with_untracked_spec(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_home(tmp_path), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    raw = json.dumps(_stop_payload(worktree, transcript)).encode()
    assert run_hook(raw, env) == HOOK_EXIT_SILENT
    assert _log_lines(project) == []
    assert not (worktree / '.convoy').exists()


def test_a_worktree_agent_is_judged_and_reused_without_a_project_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Third review, NIT (S2, S5b): with `$CLAUDE_PROJECT_DIR` unset, the main checkout anchors."""
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    (worktree / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = _env_trusting(tmp_path, project)
    assert 'CLAUDE_PROJECT_DIR' not in env
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    stop = _stop_payload(worktree, transcript, stop_hook_active=True)
    assert run_hook(json.dumps(stop).encode(), env) == HOOK_EXIT_SILENT  # residual red, recorded
    (judged,) = _log_lines(project)
    assert judged['outcome'] == 'blocked' and judged['blocked_stop'] is False
    assert judged['workspace'] == str(worktree.resolve())
    assert judged['anchor'] == str(project.resolve())
    capsys.readouterr()
    messenger = _payload(
        project, tool_response={'agentId': judged['agent_id']}, session_id=judged['session_id']
    )
    assert run_hook(json.dumps(messenger).encode(), env) == HOOK_EXIT_FEEDBACK
    assert f'judged {worktree.resolve()}' in capsys.readouterr().err
    assert _log_lines(project)[-1]['reused_from'] == judged['ts']


@pytest.mark.parametrize('trust', ['vouched', 'unpinned'])
def test_convoy_gate_in_a_worktree_says_what_the_hook_judges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust: str
) -> None:
    """Third review, MINOR (S8): the note describes the hook's decision, not `trust_decision`'s."""
    project, worktree = _project_with_worktree(tmp_path, _check('ok', _OK))
    env = _env_vouching(tmp_path, project, trust)
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    monkeypatch.delenv('CONVOY_TRUSTED_ROOTS', raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    result = runner.invoke(cli.app, ['gate', '--workspace', str(worktree)])
    assert result.exit_code == 0, result.stderr + result.stdout
    assert 'not armed' not in result.stderr
    spec = project.resolve() / '.convoy' / 'gate.toml'
    assert f'the hook judges {worktree.resolve()} with {spec}' in result.stderr


def test_a_green_in_the_agents_own_tree_says_nothing(tmp_path: Path) -> None:
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(worktree, transcript), env)
    assert result.exit_code == HOOK_EXIT_SILENT and result.stderr == ''
    assert result.record is not None and result.record['tree_mismatch'] is False


def test_the_messenger_reuses_a_worktree_judges_verdict(tmp_path: Path) -> None:
    """MINOR 5: the judge logs in the anchor, where the orchestrator's messenger looks."""
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    (worktree / 'broken.txt').write_text('red\n', encoding='utf-8')
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    stop = _stop_payload(worktree, transcript, stop_hook_active=True)
    assert run_hook(json.dumps(stop).encode(), env) == HOOK_EXIT_SILENT  # residual red, recorded
    (judged,) = _log_lines(project)
    messenger = decide(
        _payload(
            project, tool_response={'agentId': judged['agent_id']}, session_id=judged['session_id']
        ),
        env,
    )
    assert messenger.exit_code == HOOK_EXIT_FEEDBACK
    assert messenger.record is not None and messenger.record['reused_from'] == judged['ts']
    assert f'judged {worktree.resolve()}' in messenger.stderr


def test_a_nul_byte_in_a_git_pointer_does_not_crash_the_hook(tmp_path: Path) -> None:
    """MINOR 7."""
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    (root / '.git').write_text('gitdir: bad\x00path\n', encoding='utf-8')
    result = decide(_payload(root), _home(tmp_path))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['outcome'] == 'untrusted'


# --- the second review of CONV-B75 -------------------------------------------------------------


def _session_worktree(tmp_path: Path, *checks: str) -> tuple[Path, Path]:
    """The owner's layout: a main checkout M and a session checkout S, a worktree of M."""
    main, _agent = _project_with_worktree(tmp_path, *checks)
    session = tmp_path / 'session-wt'
    _git(main, 'worktree', 'add', '-q', '-b', 'session', str(session))
    return main, session


@pytest.mark.parametrize('main_listed', [False, True], ids=['main-unlisted', 'main-listed'])
def test_a_trusted_session_worktree_finds_the_oracles_its_scaffold_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, main_listed: bool
) -> None:
    """MAJOR 1: S is a linked worktree with its own entry; init, gate and hook agree on S."""
    monkeypatch.delenv('CONVOY_ORACLES', raising=False)
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    main, session = _session_worktree(tmp_path, _check('ok', _OK))
    one = Toolchain('python', (Check(name='c0', run=_OK, blocking=True),))
    monkeypatch.setattr(gate_scaffold, 'detect_toolchain', lambda _root: one)
    env = _home(tmp_path)
    if main_listed:
        trust_project(main, env)
    (session / '.convoy' / 'gate.toml').unlink()
    written = scaffold_gate(session, env, independent='oracle1')
    oracle = next(path for path in written if path.name == 'oracle1.py')
    assert oracle.parent.name == 'session-wt'
    oracle.write_text('raise SystemExit(0)\n', encoding='utf-8')
    spec_path = session / '.convoy' / 'gate.toml'
    interpreter = f'run = "\\"{sys.executable}\\" "'.replace('\\', '\\\\')
    text = spec_path.read_text(encoding='utf-8').replace('run = "python "', interpreter, 1)
    spec_path.write_text(text, encoding='utf-8')
    trust_project(session, env)
    monkeypatch.setenv('CONVOY_HOME', env['CONVOY_HOME'])
    gated = runner.invoke(cli.app, ['gate', '--workspace', str(session)])
    assert gated.exit_code == 0, gated.stderr + gated.stdout
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    hooked = decide(_stop_payload(session, transcript), {**env, 'CLAUDE_PROJECT_DIR': str(session)})
    assert hooked.record is not None and hooked.record['outcome'] == 'completed', hooked.record


def test_a_changed_anchor_spec_reached_from_a_worktree_is_refused_once(tmp_path: Path) -> None:
    """MINOR m2: the fallback judges the main checkout, whose spec changed since it was trusted."""
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    spec = project / '.convoy' / 'gate.toml'
    spec.write_text(spec.read_text(encoding='utf-8') + '\n# edited after trust\n', 'utf-8')
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    first = decide(_stop_payload(worktree, transcript), env)
    assert first.exit_code == HOOK_EXIT_FEEDBACK
    assert first.record is not None and first.record['outcome'] == 'spec_changed'
    assert 'operator' in first.stderr
    assert str(worktree.resolve()) in first.stderr
    assert f'`convoy gate --trust` in {project.resolve()}' in first.stderr
    retry = decide(_stop_payload(worktree, transcript, stop_hook_active=True), env)
    assert retry.exit_code == HOOK_EXIT_SILENT
    assert retry.record is not None and retry.record['outcome'] == 'spec_changed'


def test_a_changed_main_checkout_spec_still_refuses_its_own_agents_every_time(
    tmp_path: Path,
) -> None:
    """The main checkout's own `changed` behaviour is unchanged."""
    project, _worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_env_trusting(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    spec = project / '.convoy' / 'gate.toml'
    spec.write_text(spec.read_text(encoding='utf-8') + '\n# edited after trust\n', 'utf-8')
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    retry = decide(_stop_payload(project, transcript, stop_hook_active=True), env)
    assert retry.exit_code == HOOK_EXIT_FEEDBACK
    assert 'changed since' in retry.stderr


def test_an_untrusted_worktree_is_never_told_to_trust_itself(tmp_path: Path) -> None:
    """MAJOR 2: the advice names the checkout the worktree is made from."""
    project, worktree = _project_with_worktree(tmp_path, _check('clean', _RED_IF_BROKEN))
    env = {**_home(tmp_path), 'CLAUDE_PROJECT_DIR': str(project)}
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement it', 'Write')
    result = decide(_stop_payload(worktree, transcript), env)
    assert result.record is not None and result.record['outcome'] == 'untrusted'
    reason = result.record['reason']
    assert f'`convoy gate --trust` in {project.resolve()}' in reason
    assert f'in {worktree.resolve()}' not in reason
