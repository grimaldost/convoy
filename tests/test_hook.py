"""Tests for ``convoy hook`` (interface/hook.py): the gate as a PostToolUse hook.

The payloads are the ones Claude Code 2.1.258 actually sends (tests/fixtures/hooks, paths
scrubbed), so the field names pinned here are the real protocol, not a reading of it.
Every test that expects the gate to run trusts its project first, under a ``CONVOY_HOME``
inside ``tmp_path`` — the hook executes nothing in an untrusted project, and no test
touches the real home directory.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import convoy.interface.cli as cli
from convoy import __version__
from convoy.interface.gate_service import trust_project
from convoy.interface.hook import (
    HOOK_EXIT_FEEDBACK,
    HOOK_EXIT_SILENT,
    decide,
    parse_event,
    parse_phase_markers,
    read_transcript,
    run_hook,
)
from convoy.interface.workspace_lock import lock_path

FIXTURES = Path(__file__).parent / 'fixtures' / 'hooks'
runner = CliRunner()

_OK = f'"{sys.executable}" -c "exit(0)"'
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


def _trusted(tmp_path: Path, root: Path) -> dict[str, str]:
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
    result = decide(_payload(root, tool_name='Bash'), _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == '' and result.record is None


def test_no_project_spec_means_the_hook_is_unarmed(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    root.mkdir()
    result = decide(_payload(root), _trusted(tmp_path, root))
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
    result = decide(_payload(root), _trusted(tmp_path, root))
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
    result = decide(_payload(root), _trusted(tmp_path, root))
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
    result = decide(payload, _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None
    assert result.record['phases'] == ['api']
    assert [check['name'] for check in result.record['checks']] == ['api-only']


def test_an_unknown_phase_tag_is_reported_not_narrowed(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK, phases='"core"'))
    payload = _payload(root, tool_input={'prompt': '[convoy-phase: nope]'})
    result = decide(payload, _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'could not run' in result.stderr and 'nope' in result.stderr
    assert result.record is not None and result.record['outcome'] == 'usage'


def test_a_dispatch_that_did_not_complete_is_skipped_but_recorded(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    payload = _payload(root, tool_response={'status': 'async_launched'})
    result = decide(payload, _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == ''
    assert result.record is not None and result.record['outcome'] == 'skipped'
    assert 'async_launched' in result.record['reason']


def test_an_invalid_spec_is_loud(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    (root / '.convoy').mkdir(parents=True)
    (root / '.convoy' / 'gate.toml').write_text('not = [toml', encoding='utf-8')
    result = decide(_payload(root), _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'could not run' in result.stderr


def test_the_task_alias_is_gated_too(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    result = decide(_payload(root, tool_name='Task'), _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK


def test_claude_project_dir_wins_over_the_payload_cwd(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    _project(project, _check('bad', _RED))
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    env = {**_trusted(tmp_path, project), 'CLAUDE_PROJECT_DIR': str(project)}
    result = decide(_payload(elsewhere), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK


# --- run_hook and the CLI ---------------------------------------------------------------------


def test_run_hook_appends_one_log_line_per_firing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _trusted(tmp_path, root)
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
    env = _trusted(tmp_path, root)
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
    monkeypatch.setenv('CONVOY_HOME', _trusted(tmp_path, root)['CONVOY_HOME'])
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
    assert 'convoy hook' in command['command']
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
    result = decide(_stop_payload(root, transcript), _trusted(tmp_path, root))
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
    result = decide(payload, _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == ''
    assert result.record is not None
    assert result.record['outcome'] == 'blocked'
    assert result.record['blocked_stop'] is False


def test_a_green_stop_is_silent_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    transcript = _transcript(tmp_path / 't.jsonl', 'Implement the thing', 'Bash')
    result = decide(_stop_payload(root, transcript), _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['outcome'] == 'completed'


def test_a_read_only_subagent_is_not_gated(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    transcript = _transcript(tmp_path / 't.jsonl', 'Survey the code', 'Read', 'Grep', 'Glob')
    result = decide(_stop_payload(root, transcript), _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None
    assert result.record['outcome'] == 'skipped'
    assert 'read-only' in result.record['reason']
    assert result.record['leg'] == 'judge'


def test_a_missing_transcript_is_gated_conservatively(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    result = decide(_stop_payload(root, tmp_path / 'missing.jsonl'), _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK


def test_the_phase_marker_in_the_subagent_brief_scopes_the_stop_gate(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(
        root,
        _check('core-only', _RED, phases='"core"'),
        _check('api-only', _OK, phases='"api"'),
    )
    transcript = _transcript(tmp_path / 't.jsonl', 'API work [convoy-phase: api]', 'Edit')
    result = decide(_stop_payload(root, transcript), _trusted(tmp_path, root))
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
    env = _trusted(tmp_path, root)
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
    env = _trusted(tmp_path, root)
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
    assert 'convoy hook' in command['command']
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
    assert run_hook(raw, _trusted(tmp_path, root)) == HOOK_EXIT_FEEDBACK


def test_a_gate_that_cannot_run_lets_the_subagent_stop_on_the_retry(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK, phases='"core"'))
    env = _trusted(tmp_path, root)
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
    env = _trusted(tmp_path, root)
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
    result = decide(_stop_payload(root, transcript), _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    nested = _transcript(tmp_path / 'n.jsonl', 'delegate', 'Agent')
    assert (
        decide(_stop_payload(root, nested), _trusted(tmp_path, root)).exit_code
        == HOOK_EXIT_FEEDBACK
    )


def test_a_naive_or_foreign_session_verdict_is_not_reused(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _trusted(tmp_path, root)
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
    env = _trusted(tmp_path, root)
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
    env = _trusted(tmp_path, root)
    spec.write_text(spec.read_text(encoding='utf-8').replace('"ok"', '"ok2"'), encoding='utf-8')
    result = decide(_payload(root), env)
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'changed since' in result.stderr
    assert result.record is not None and result.record['outcome'] == 'spec_changed'


def test_a_driven_workspace_is_refused(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('ok', _OK))
    env = _trusted(tmp_path, root)
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
    result = decide(_stop_payload(root, path), _trusted(tmp_path, root))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None and result.record['phases'] == ['api']
    assert result.record['model'] == 'm'


def test_every_record_carries_the_attestation_fields(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    _project(root, _check('bad', _RED))
    transcript = _transcript(tmp_path / 't.jsonl', 'work', 'Write')
    result = decide(_stop_payload(root, transcript), _trusted(tmp_path, root))
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
