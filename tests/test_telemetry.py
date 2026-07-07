"""Tests for the telemetry model: serialization, the cost fallback, and the writer."""

import dataclasses
import json
from pathlib import Path

from convoy.core.telemetry import (
    _EVENT_TAGS,
    SCHEMA_VERSION,
    GateCheckLine,
    GateComplete,
    PRSkipped,
    RunComplete,
    RunStart,
    SpawnComplete,
    apply_cost_fallback,
    to_json_line,
)
from convoy.interface.telemetry_writer import TelemetryWriter

# A complete spawn_complete event; ``_spawn`` clones it with per-field overrides.
_BASE_SPAWN = SpawnComplete(
    run_id='20260703T142210Z-a1',
    pr_id='pr-1-lexer',
    role='implementation',
    exit_code=0,
    input_tokens=18422,
    output_tokens=3110,
    num_turns=9,
    duration_s=74.2,
    cost_usd=0.11,
    effective_model='claude-sonnet-5',
)


def _spawn(**overrides: object) -> SpawnComplete:
    """The base spawn_complete event with ``overrides`` replacing individual fields."""
    return dataclasses.replace(_BASE_SPAWN, **overrides)


def test_run_start_json_line_has_schema_tag_and_all_fields() -> None:
    event = RunStart(run_id='20260703T142210Z-a1', series_id='add-comparison-ops')
    parsed = json.loads(to_json_line(event))
    assert parsed == {
        'schema_version': SCHEMA_VERSION,
        'event': 'run_start',
        'run_id': '20260703T142210Z-a1',
        'series_id': 'add-comparison-ops',
    }
    assert parsed['schema_version'] == 1


def test_spawn_complete_json_line_has_schema_tag_and_all_fields() -> None:
    event = _spawn()
    parsed = json.loads(to_json_line(event))
    assert parsed == {
        'schema_version': 1,
        'event': 'spawn_complete',
        'run_id': '20260703T142210Z-a1',
        'pr_id': 'pr-1-lexer',
        'role': 'implementation',
        'exit_code': 0,
        'input_tokens': 18422,
        'output_tokens': 3110,
        'num_turns': 9,
        'duration_s': 74.2,
        'cost_usd': 0.11,
        'effective_model': 'claude-sonnet-5',
        'cost_estimated': False,
        'output_tail': '',
    }


def test_run_complete_json_line_has_schema_tag_and_all_fields() -> None:
    event = RunComplete(run_id='20260703T142210Z-a1', outcome='completed', integrated=True)
    parsed = json.loads(to_json_line(event))
    assert parsed == {
        'schema_version': 1,
        'event': 'run_complete',
        'run_id': '20260703T142210Z-a1',
        'outcome': 'completed',
        'integrated': True,
    }


def test_json_line_is_single_line_without_trailing_newline() -> None:
    line = to_json_line(RunStart(run_id='r', series_id='s'))
    assert '\n' not in line


def test_cost_fallback_estimates_when_cost_is_zero() -> None:
    # sonnet 3/15: 1,000,000 in + 200,000 out = 3.0 + 3.0 = 6.0.
    event = _spawn(cost_usd=0.0, input_tokens=1_000_000, output_tokens=200_000)
    result = apply_cost_fallback(event)
    assert result.cost_usd == 6.0
    assert result.cost_estimated is True
    # Every other field is preserved.
    assert result.run_id == event.run_id
    assert result.effective_model == event.effective_model


def test_cost_fallback_leaves_nonzero_cost_unchanged() -> None:
    event = _spawn(cost_usd=0.11)
    result = apply_cost_fallback(event)
    assert result is event
    assert result.cost_estimated is False


def test_writer_appends_three_lines_that_parse_back(tmp_path: Path) -> None:
    path = tmp_path / 'nested' / 'spawns.jsonl'
    writer = TelemetryWriter(path)
    events = [
        RunStart(run_id='20260703T142210Z-a1', series_id='add-comparison-ops'),
        _spawn(),
        RunComplete(run_id='20260703T142210Z-a1', outcome='completed', integrated=True),
    ]
    for event in events:
        writer.write(event)

    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]['event'] == 'run_start'
    assert parsed[1]['event'] == 'spawn_complete'
    assert parsed[2]['event'] == 'run_complete'
    assert all(entry['schema_version'] == 1 for entry in parsed)
    assert parsed[1]['pr_id'] == 'pr-1-lexer'


# --- additive v1 events: gate_complete + pr_skipped (schema_version stays 1) -------------


def test_gate_complete_json_line_has_schema_tag_and_all_fields() -> None:
    event = GateComplete(
        run_id='20260703T142210Z-a1',
        pr_id='pr-1',
        attempt=0,
        blocking_red=True,
        independent_red=False,
        checks=(
            GateCheckLine(
                name='suite',
                passed=False,
                blocking=True,
                independent=False,
                detail='exited 1: boom',
            ),
            GateCheckLine(name='types', passed=True, blocking=True, independent=True, detail=''),
        ),
    )
    parsed = json.loads(to_json_line(event))
    assert parsed == {
        'schema_version': 1,
        'event': 'gate_complete',
        'run_id': '20260703T142210Z-a1',
        'pr_id': 'pr-1',
        'attempt': 0,
        'blocking_red': True,
        'independent_red': False,
        'checks': [
            {
                'name': 'suite',
                'passed': False,
                'blocking': True,
                'independent': False,
                'detail': 'exited 1: boom',
            },
            {'name': 'types', 'passed': True, 'blocking': True, 'independent': True, 'detail': ''},
        ],
    }


def test_gate_complete_with_no_checks_serializes_an_empty_list() -> None:
    event = GateComplete(
        run_id='r', pr_id='p', attempt=2, blocking_red=False, independent_red=False, checks=()
    )
    parsed = json.loads(to_json_line(event))
    assert parsed['checks'] == []
    assert parsed['attempt'] == 2


def test_pr_skipped_json_line_has_schema_tag_and_all_fields() -> None:
    reason = 'series halted at pr-a (blocked) before this PR started'
    event = PRSkipped(run_id='r', pr_id='pr-b', reason=reason)
    parsed = json.loads(to_json_line(event))
    assert parsed == {
        'schema_version': 1,
        'event': 'pr_skipped',
        'run_id': 'r',
        'pr_id': 'pr-b',
        'reason': reason,
    }


def test_spawn_complete_output_tail_defaults_empty() -> None:
    # Additive field: every line carries it; ok spawns leave it empty.
    parsed = json.loads(to_json_line(_spawn()))
    assert parsed['output_tail'] == ''


def test_spawn_complete_carries_output_tail_when_set() -> None:
    event = _spawn(output_tail='Not logged in - please run /login')
    parsed = json.loads(to_json_line(event))
    assert parsed['output_tail'] == 'Not logged in - please run /login'


def test_new_events_do_not_bump_schema_version() -> None:
    lines = (
        to_json_line(
            GateComplete(
                run_id='r',
                pr_id='p',
                attempt=0,
                blocking_red=False,
                independent_red=False,
                checks=(),
            )
        ),
        to_json_line(PRSkipped(run_id='r', pr_id='p', reason='x')),
    )
    for line in lines:
        assert json.loads(line)['schema_version'] == SCHEMA_VERSION
    assert SCHEMA_VERSION == 1


def test_gate_check_line_is_not_a_standalone_event() -> None:
    # A nested record inside gate_complete, never written on its own line.
    assert GateCheckLine not in _EVENT_TAGS
