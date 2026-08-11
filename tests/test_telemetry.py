"""Tests for the telemetry model: serialization, the cost fallback, and the writer."""

import dataclasses
import json
from pathlib import Path

import pytest

from convoy.core.telemetry import (
    _EVENT_TAGS,
    BUDGET_NEARING_FRACTION,
    SCHEMA_VERSION,
    GateCheckLine,
    GateComplete,
    HaltDetail,
    PRSkipped,
    RunAbandoned,
    RunComplete,
    RunStart,
    SpawnComplete,
    apply_cost_fallback,
    budget_is_nearing,
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
        # Always emitted, empty on the ordinary run, so a consumer reads the key
        # unconditionally rather than branching on its presence.
        'advisories': [],
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
        'classification': 'ok',
        'budget_cap_usd': None,
        'budget_nearing': False,
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
        'halt': None,
    }


def test_run_complete_carries_a_located_halt_when_the_run_stopped() -> None:
    event = RunComplete(
        run_id='r',
        outcome='budget',
        integrated=False,
        halt=HaltDetail(pr_id='pr-2-parser', phase='core', role='fix', spend_usd=1.03, cap_usd=1.0),
    )
    parsed = json.loads(to_json_line(event))
    # The nested record serializes as a plain object, like GateCheckLine does.
    assert parsed['halt'] == {
        'pr_id': 'pr-2-parser',
        'phase': 'core',
        'role': 'fix',
        'spend_usd': 1.03,
        'cap_usd': 1.0,
    }


def test_a_halt_with_no_ceiling_involved_reports_no_money() -> None:
    """A blocked run hit no cap, so reporting one would send the reader after a wrong fix."""
    event = RunComplete(
        run_id='r',
        outcome='blocked',
        integrated=False,
        halt=HaltDetail(pr_id='pr-1', phase='core', role='gate'),
    )
    parsed = json.loads(to_json_line(event))
    assert parsed['halt']['spend_usd'] is None
    assert parsed['halt']['cap_usd'] is None
    assert parsed['halt']['role'] == 'gate'


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


def test_run_abandoned_json_line_has_schema_tag_and_all_fields() -> None:
    reason = 'workspace lock cleared by convoy clean; the run never returned'
    event = RunAbandoned(run_id='20260703T142210Z-a1', reason=reason)
    parsed = json.loads(to_json_line(event))
    assert parsed == {
        'schema_version': 1,
        'event': 'run_abandoned',
        'run_id': '20260703T142210Z-a1',
        'reason': reason,
    }


def test_run_abandoned_claims_nothing_the_writer_could_not_know() -> None:
    """No halt, no integrated: whoever writes this was not there for the run."""
    parsed = json.loads(to_json_line(RunAbandoned(run_id='r', reason='x')))
    assert 'halt' not in parsed
    assert 'integrated' not in parsed


def test_gate_check_line_is_not_a_standalone_event() -> None:
    # A nested record inside gate_complete, never written on its own line.
    assert GateCheckLine not in _EVENT_TAGS


# --- the near-cap signal ------------------------------------------------------------------


@pytest.mark.parametrize('spend', [18.0, 19.5, 20.0, 21.0])
def test_budget_is_nearing_at_the_threshold_and_above(spend: float) -> None:
    # 0.9 * 20.0 == 18.0, so the threshold itself counts: the point is to speak BEFORE the
    # bust, and a spawn sitting exactly on the line has already spent the safe part.
    assert budget_is_nearing(spend, 20.0) is True


@pytest.mark.parametrize('spend', [0.0, 8.79, 17.99])
def test_budget_is_not_nearing_below_the_threshold(spend: float) -> None:
    assert budget_is_nearing(spend, 20.0) is False


@pytest.mark.parametrize('cap', [None, 0.0, -1.0])
def test_budget_is_not_nearing_without_a_ceiling(cap: float | None) -> None:
    # No ceiling to near. False rather than an error: an uncapped spawn is not close to a
    # cap it does not have, and a telemetry helper must never be the thing that raises.
    assert budget_is_nearing(1_000.0, cap) is False


def test_the_nearing_fraction_leaves_room_to_act() -> None:
    assert 0.0 < BUDGET_NEARING_FRACTION < 1.0


def test_spawn_complete_carries_the_cap_and_the_nearing_flag() -> None:
    event = _spawn(cost_usd=19.4, budget_cap_usd=20.0, budget_nearing=True)
    parsed = json.loads(to_json_line(event))
    assert parsed['budget_cap_usd'] == 20.0
    assert parsed['budget_nearing'] is True
