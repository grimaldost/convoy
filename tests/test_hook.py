"""Tests for ``convoy hook`` (interface/hook.py): the gate as a PostToolUse hook.

The payloads are the ones Claude Code 2.1.258 actually sends (tests/fixtures/hooks, paths
scrubbed), so the field names pinned here are the real protocol, not a reading of it.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import convoy.interface.cli as cli
from convoy import __version__
from convoy.interface.hook import (
    HOOK_EXIT_FEEDBACK,
    HOOK_EXIT_SILENT,
    decide,
    parse_phase_markers,
    run_hook,
)

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


# --- decide ----------------------------------------------------------------------------------


def test_a_non_dispatch_tool_is_ignored_silently(tmp_path: Path) -> None:
    _project(tmp_path, _check('bad', _RED))
    result = decide(_payload(tmp_path, tool_name='Bash'), {})
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == '' and result.record is None


def test_no_project_spec_means_the_hook_is_unarmed(tmp_path: Path) -> None:
    result = decide(_payload(tmp_path), {})
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == '' and result.record is None


def test_a_green_gate_says_nothing_and_records_the_firing(tmp_path: Path) -> None:
    _project(tmp_path, _check('ok', _OK))
    result = decide(_payload(tmp_path), {})
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
    _project(tmp_path, _check('ok', _OK), _check('bad', _RED, hint='rerun the fixture build'))
    result = decide(_payload(tmp_path), {})
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert result.stderr.startswith('convoy gate: BLOCKED after subagent a1b909db97960854e')
    assert 'bad' in result.stderr
    assert 'rerun the fixture build' in result.stderr
    assert 'hook-red-marker' in result.stderr
    assert result.record is not None and result.record['outcome'] == 'blocked'
    assert result.record['blocking_red'] is True


def test_a_phase_marker_in_the_brief_scopes_the_gate(tmp_path: Path) -> None:
    _project(
        tmp_path,
        _check('core-only', _RED, phases='"core"'),
        _check('api-only', _OK, phases='"api"'),
    )
    payload = _payload(tmp_path, tool_input={'prompt': 'Do the API work. [convoy-phase: api]'})
    result = decide(payload, {})
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.record is not None
    assert result.record['phases'] == ['api']
    assert [check['name'] for check in result.record['checks']] == ['api-only']
    assert 'phase api' not in result.stderr


def test_an_unknown_phase_tag_is_reported_not_narrowed(tmp_path: Path) -> None:
    _project(tmp_path, _check('ok', _OK, phases='"core"'))
    payload = _payload(tmp_path, tool_input={'prompt': '[convoy-phase: nope]'})
    result = decide(payload, {})
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'could not run' in result.stderr and 'nope' in result.stderr
    assert result.record is not None and result.record['outcome'] == 'usage'


def test_a_dispatch_that_did_not_complete_is_skipped_but_recorded(tmp_path: Path) -> None:
    _project(tmp_path, _check('bad', _RED))
    payload = _payload(tmp_path, tool_response={'status': 'running'})
    result = decide(payload, {})
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stderr == ''
    assert result.record is not None and result.record['outcome'] == 'skipped'


def test_an_invalid_spec_is_loud(tmp_path: Path) -> None:
    (tmp_path / '.convoy').mkdir()
    (tmp_path / '.convoy' / 'gate.toml').write_text('not = [toml', encoding='utf-8')
    result = decide(_payload(tmp_path), {})
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert 'could not run' in result.stderr


def test_the_task_alias_is_gated_too(tmp_path: Path) -> None:
    _project(tmp_path, _check('bad', _RED))
    result = decide(_payload(tmp_path, tool_name='Task'), {})
    assert result.exit_code == HOOK_EXIT_FEEDBACK


def test_claude_project_dir_wins_over_the_payload_cwd(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    _project(project, _check('bad', _RED))
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    result = decide(_payload(elsewhere), {'CLAUDE_PROJECT_DIR': str(project)})
    assert result.exit_code == HOOK_EXIT_FEEDBACK


# --- run_hook and the CLI ---------------------------------------------------------------------


def test_run_hook_appends_one_log_line_per_firing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _project(tmp_path, _check('ok', _OK))
    assert run_hook(json.dumps(_payload(tmp_path)), {}) == HOOK_EXIT_SILENT
    assert run_hook(json.dumps(_payload(tmp_path)), {}) == HOOK_EXIT_SILENT
    captured = capsys.readouterr()
    assert captured.out == '' and captured.err == ''
    lines = _log_lines(tmp_path)
    assert len(lines) == 2
    assert lines[0]['outcome'] == 'completed'
    assert lines[0]['spec'].endswith('gate.toml')


def test_run_hook_rejects_non_json_stdin(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_hook('not json', {}) == HOOK_EXIT_FEEDBACK
    assert 'not hook JSON' in capsys.readouterr().err


def test_cli_hook_reads_stdin_and_exits_with_the_hook_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    _project(tmp_path, _check('bad', _RED, hint='fix it'))
    result = runner.invoke(cli.app, ['hook'], input=json.dumps(_payload(tmp_path)))
    assert result.exit_code == HOOK_EXIT_FEEDBACK
    assert result.stdout == ''
    assert 'BLOCKED' in result.stderr and 'fix it' in result.stderr
    assert _log_lines(tmp_path)[0]['outcome'] == 'blocked'


def test_cli_hook_is_silent_on_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    _project(tmp_path, _check('ok', _OK))
    result = runner.invoke(cli.app, ['hook'], input=json.dumps(_payload(tmp_path)))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stdout == '' and result.stderr == ''


def test_cli_hook_is_silent_where_no_project_opted_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    result = runner.invoke(cli.app, ['hook'], input=json.dumps(_payload(tmp_path)))
    assert result.exit_code == HOOK_EXIT_SILENT
    assert result.stdout == '' and result.stderr == ''
    assert _log_lines(tmp_path) == []


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
