"""The telemetry model — convoy's ``spawns.jsonl`` events (pure; no I/O).

The append-only JSON-lines telemetry is convoy's economy record and primary
observability surface (see ``docs/design/02-formats.md``). This module defines the
five v1 events (``run_start`` / ``spawn_complete`` / ``gate_complete`` / ``pr_skipped`` /
``run_complete``) and how each serializes to one line; the file writing itself lives in
``interface/telemetry_writer.py``. Every line carries ``schema_version`` and an
``event`` tag, so a consumer keys on both and can ignore unknown fields — evolution is
additive.
"""

import dataclasses
import json
from dataclasses import dataclass

from convoy.core import pricing

SCHEMA_VERSION = 1

# The event tag written on each line, keyed by event dataclass. Kept next to the
# classes so ``to_json_line`` never has to branch on ``isinstance``.
_EVENT_TAGS: dict[type, str] = {}


@dataclass(frozen=True)
class RunStart:
    """Emitted once per ``convoy run``, grouping the invocation's events."""

    run_id: str
    series_id: str


@dataclass(frozen=True)
class SpawnComplete:
    """Emitted once per agent spawn — the per-spawn economy record.

    ``role`` is one of ``implementation``, ``review``, ``fix``. ``cost_estimated``
    marks a line whose ``cost_usd`` was substituted from a token estimate rather than
    reported by the provider (see ``apply_cost_fallback``).
    """

    run_id: str
    pr_id: str
    role: str
    exit_code: int
    input_tokens: int
    output_tokens: int
    num_turns: int
    duration_s: float
    cost_usd: float
    effective_model: str
    cost_estimated: bool = False


@dataclass(frozen=True)
class RunComplete:
    """Emitted once per ``convoy run``. ``outcome`` is one of ``completed``,
    ``blocked``, ``infrastructure``, ``budget``; ``integrated`` records whether the
    result reached the integration branch.
    """

    run_id: str
    outcome: str
    integrated: bool


@dataclass(frozen=True)
class GateCheckLine:
    """One check's outcome inside a ``gate_complete`` event — not itself an event.

    A plain nested record: no ``schema_version`` / ``event`` tag and no ``_EVENT_TAGS``
    entry. It serializes to a JSON object via ``dataclasses.asdict`` recursion when the
    enclosing :class:`GateComplete` is written.
    """

    name: str
    passed: bool
    blocking: bool
    independent: bool
    detail: str


@dataclass(frozen=True)
class GateComplete:
    """Emitted after every gate evaluation of a PR — the per-check verdict record.

    ``attempt`` is 0 for the initial gate and 1..N after the Nth fix spawn's re-gate.
    ``checks`` carries one :class:`GateCheckLine` per check in run order; ``blocking_red``
    and ``independent_red`` are the derived verdict flags (see ``core.gate``). This makes a
    blocked run self-explaining in telemetry: a consumer sees which check failed and why.
    """

    run_id: str
    pr_id: str
    attempt: int
    blocking_red: bool
    independent_red: bool
    checks: tuple[GateCheckLine, ...]


@dataclass(frozen=True)
class PRSkipped:
    """Emitted for each PR the run never processed because an earlier PR halted the series.

    ``reason`` is free-form provenance (e.g. ``'series halted at pr-a (blocked) before
    this PR started'``): it states why the series stopped, not a claim of a direct
    dependency edge.
    """

    run_id: str
    pr_id: str
    reason: str


Event = RunStart | SpawnComplete | RunComplete | GateComplete | PRSkipped

_EVENT_TAGS[RunStart] = 'run_start'
_EVENT_TAGS[SpawnComplete] = 'spawn_complete'
_EVENT_TAGS[RunComplete] = 'run_complete'
_EVENT_TAGS[GateComplete] = 'gate_complete'
_EVENT_TAGS[PRSkipped] = 'pr_skipped'


def to_json_line(event: Event) -> str:
    """Serialize an event to one compact JSON object (no trailing newline).

    Keys are ``schema_version``, ``event`` (the tag), then all of the event's own
    fields in declaration order.
    """
    payload: dict[str, object] = {
        'schema_version': SCHEMA_VERSION,
        'event': _EVENT_TAGS[type(event)],
    }
    payload.update(dataclasses.asdict(event))
    return json.dumps(payload, separators=(',', ':'))


def apply_cost_fallback(event: SpawnComplete) -> SpawnComplete:
    """Substitute a token-count cost estimate when the provider reported ``0.0``.

    If ``cost_usd`` is ``0.0``, return a copy with the estimated cost and
    ``cost_estimated = True``; otherwise return the event unchanged.
    """
    if event.cost_usd != 0.0:
        return event
    estimated = pricing.estimate_cost_usd(
        event.effective_model, event.input_tokens, event.output_tokens
    )
    return dataclasses.replace(event, cost_usd=estimated, cost_estimated=True)
