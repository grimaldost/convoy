"""``convoy hook`` — the gate as a Claude Code ``PostToolUse`` hook on subagent dispatch.

The orchestrator dispatches a subagent; when the dispatch returns, Claude Code runs this
hook with the event JSON on stdin. The hook finds the project's gate spec (the same
discovery ``convoy gate`` uses), runs the gate through the same fold, and answers in the
hook protocol's vocabulary, which is not convoy's: exit 0 with nothing on stdout when the
gate is green — nothing enters the orchestrator's context — and exit 2 with the compact
repair brief on stderr when it is red, which Claude Code shows to the orchestrator as
feedback on a tool call that has already completed. Every re-dispatch re-fires the hook,
so the loop closes without the orchestrator ever running or reading a gate itself.

The presence of a project spec is the per-project switch: with none found the hook exits
0 silently, so shipping it in the plugin arms nothing until a project opts in. A gate
that cannot run (an unreadable or invalid spec, a refused invocation, a dead workspace) is
exit 2 with a one-line reason — the loud answer, because a hook that swallowed its own
misconfiguration would look like a green gate.

Attestation: one JSON line per firing is appended to ``.convoy/hook.log`` under the
project root (the scaffold gitignores it) — the verdict, the subagent's dated model and
id, the phases, the counts, the gate's wall-clock — so an experiment counts firings from
the log rather than from transcripts. Writing the log is best-effort and never changes
the verdict.
"""

import json
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from convoy import __version__
from convoy.core.gate import GateUsageError, repair_brief
from convoy.core.spec import SpecError
from convoy.interface.gate_service import (
    GateOutcome,
    find_gate_spec,
    load_gate_spec_file,
    project_root_of,
    run_gate,
)

# The hook protocol's exit codes — not convoy's. 0: nothing to say; 2: stderr is shown to
# the model as feedback (the tool call already completed either way).
HOOK_EXIT_SILENT = 0
HOOK_EXIT_FEEDBACK = 2

# The dispatch tools this hook gates: ``Agent``, and its pre-2.1.63 name ``Task``.
DISPATCH_TOOLS = frozenset({'Agent', 'Task'})

HOOK_LOG_RELPATH = Path('.convoy') / 'hook.log'

# ``[convoy-phase: core]`` in the subagent's brief scopes the gate to that PR's checks —
# the same selection ``convoy gate --phase core`` makes. Repeatable; tags union.
_PHASE_MARKER = re.compile(r'\[convoy-phase:\s*([^\]]+)\]')


@dataclass(frozen=True)
class HookResult:
    """What the hook decided: the exit code, what to say on stderr, and the log record."""

    exit_code: int
    stderr: str
    record: dict[str, Any] | None


def parse_phase_markers(prompt: str) -> tuple[str, ...]:
    """The phase tags a brief carries, in order of first appearance, de-duplicated."""
    seen: list[str] = []
    for match in _PHASE_MARKER.finditer(prompt):
        for tag in match.group(1).split(','):
            cleaned = tag.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
    return tuple(seen)


def _string(mapping: Any, key: str) -> str:
    value = mapping.get(key) if isinstance(mapping, Mapping) else None
    return value if isinstance(value, str) else ''


def _record(payload: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    tool_input = payload.get('tool_input')
    tool_response = payload.get('tool_response')
    return {
        'ts': datetime.now(UTC).isoformat(timespec='seconds'),
        'event': _string(payload, 'hook_event_name'),
        'tool_name': _string(payload, 'tool_name'),
        'tool_use_id': _string(payload, 'tool_use_id'),
        'session_id': _string(payload, 'session_id'),
        'agent_id': _string(tool_response, 'agentId'),
        'model': _string(tool_response, 'resolvedModel') or _string(tool_input, 'model'),
        'convoy_version': __version__,
        **fields,
    }


def decide(payload: Mapping[str, Any], env: Mapping[str, str]) -> HookResult:
    """The hook's whole decision, given the parsed event and the environment (no I/O on stdio).

    Runs the gate — check commands execute in the payload's ``cwd`` — and appends nothing;
    :func:`run_hook` owns the streams and the log.
    """
    tool_name = _string(payload, 'tool_name')
    if tool_name not in DISPATCH_TOOLS:
        return HookResult(HOOK_EXIT_SILENT, '', None)

    cwd = Path(_string(payload, 'cwd') or '.')
    spec_path = find_gate_spec(cwd, env)
    if spec_path is None:
        return HookResult(HOOK_EXIT_SILENT, '', None)

    tool_response = payload.get('tool_response')
    status = _string(tool_response, 'status')
    if status and status != 'completed':
        # A background dispatch returns before the subagent has done anything; a failed
        # one produced nothing to gate. Recorded, so the log shows the dispatch happened.
        return HookResult(
            HOOK_EXIT_SILENT,
            '',
            _record(payload, outcome='skipped', reason=f'dispatch status {status!r}'),
        )

    phases = parse_phase_markers(_string(payload.get('tool_input'), 'prompt'))
    started = time.monotonic()
    try:
        spec = load_gate_spec_file(spec_path, env)
        outcome = run_gate(spec, cwd, phases)
    except (OSError, UnicodeDecodeError, SpecError, GateUsageError) as exc:
        elapsed = round((time.monotonic() - started) * 1000)
        return HookResult(
            HOOK_EXIT_FEEDBACK,
            f'convoy hook: the gate could not run ({spec_path}): {exc}\n',
            _record(payload, outcome='usage', error=str(exc), phases=list(phases), gate_ms=elapsed),
        )
    elapsed = round((time.monotonic() - started) * 1000)
    return _verdict(payload, outcome, phases, elapsed)


def _verdict(
    payload: Mapping[str, Any], outcome: GateOutcome, phases: tuple[str, ...], gate_ms: int
) -> HookResult:
    verdict = outcome.verdict
    results = verdict.results
    passed = sum(1 for result in results if result.passed)
    record = _record(
        payload,
        outcome='blocked' if verdict.blocking_red else 'completed',
        phases=list(phases),
        blocking_red=verdict.blocking_red,
        independent_red=verdict.independent_red,
        counts={'selected': len(results), 'passed': passed, 'failed': len(results) - passed},
        checks=[{'name': result.check.name, 'passed': result.passed} for result in results],
        gate_ms=gate_ms,
    )
    if not verdict.blocking_red:
        return HookResult(HOOK_EXIT_SILENT, '', record)
    agent_id = _string(payload.get('tool_response'), 'agentId')
    who = f'subagent {agent_id}' if agent_id else 'the subagent'
    scope = f' (phase {", ".join(phases)})' if phases else ''
    header = (
        f'convoy gate: BLOCKED after {who}{scope} — dispatch a fix subagent with the brief '
        f'below; the gate re-runs when it returns.\n'
    )
    return HookResult(HOOK_EXIT_FEEDBACK, header + repair_brief(verdict), record)


def append_log(spec_path: Path, record: Mapping[str, Any]) -> str | None:
    """Append one JSON line to the project's hook log; return a message on failure."""
    root = project_root_of(spec_path)
    log_path = (root if root is not None else spec_path.parent) / HOOK_LOG_RELPATH
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    except OSError as exc:
        return f'convoy hook: could not append {log_path}: {exc}\n'
    return None


def run_hook(stdin_text: str, env: Mapping[str, str]) -> int:
    """Parse the event, decide, write stderr and the log, return the hook exit code."""
    try:
        payload = json.loads(stdin_text)
    except ValueError as exc:
        sys.stderr.write(f'convoy hook: stdin was not hook JSON: {exc}\n')
        return HOOK_EXIT_FEEDBACK
    if not isinstance(payload, dict):
        sys.stderr.write('convoy hook: stdin was not a hook event object\n')
        return HOOK_EXIT_FEEDBACK

    result = decide(payload, env)
    if result.record is not None:
        spec_path = find_gate_spec(Path(_string(payload, 'cwd') or '.'), env)
        if spec_path is not None:
            failure = append_log(spec_path, {**result.record, 'spec': str(spec_path)})
            if failure is not None:
                sys.stderr.write(failure)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.exit_code
