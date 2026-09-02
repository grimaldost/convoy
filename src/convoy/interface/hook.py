"""``convoy hook`` — the gate as a Claude Code hook around subagent dispatch.

Two hook events, one gate, two legs:

- ``SubagentStop`` is the judge. When a subagent tries to finish, the hook runs the
  project's gate in the session's working tree. Green: exit 0, nothing said. Blocking
  red: exit 2 with the repair brief on stderr, which Claude Code hands to the SUBAGENT as
  the reason it may not stop yet — the implementer repairs its own work, the same shape
  as a governed run's fix spawn — once: on the retry (``stop_hook_active``) a residual
  red lets the subagent stop and is recorded. A subagent whose transcript shows no
  mutating tool use (a reader, a reviewer) is not gated.
- ``PostToolUse`` on ``Agent`` (or ``Task``) is the messenger, for synchronous dispatch.
  When the dispatch returns completed, the hook reuses the judge's verdict for that
  subagent from the log (or runs the gate when there is none) and, on a residual red,
  exits 2 with the brief on stderr, which Claude Code shows to the ORCHESTRATOR as
  feedback on the completed tool call — its cue to dispatch a fix subagent, whose stop
  and return re-fire both legs. An asynchronous dispatch returns before the subagent has
  done anything (``async_launched``); it is recorded and not gated here, and its
  subagent is still judged at its stop.

The vocabulary is the hook protocol's, not convoy's: exit 0 means nothing to say, exit
2 means stderr is feedback. Nothing enters a model's context on a green gate.

The presence of a project spec is the per-project switch: with none found the hook exits
0 silently, so shipping it in the plugin arms nothing until a project opts in — and the
operator's trust is the per-machine switch: a spec in a project this machine has not
trusted (``convoy gate --init`` or ``convoy gate --trust`` records it) is logged and not
executed, because a cloned repository's checks must not run commands on dispatch until
the operator says so. A gate that cannot run (an unreadable or invalid spec, a refused
invocation, a dead workspace) is exit 2 with a one-line reason — the loud answer,
because a hook that swallowed its own misconfiguration would look like a green gate.

Attestation: one JSON line per firing is appended to ``.convoy/hook.log`` under the
project root (the scaffold gitignores it) — the event, the verdict, the subagent's id and
dated model, the phases, the counts, the gate's wall-clock, the brief when red — so an
experiment counts firings from the log rather than from transcripts, and the messenger
finds the judge's verdict there. Writing the log is best-effort and never changes the
verdict.
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
    gate_root,
    is_trusted,
    load_gate_spec_file,
    run_gate,
)
from convoy.interface.proc import TEXT_ENCODING, TEXT_ERRORS

# The hook protocol's exit codes — not convoy's. 0: nothing to say; 2: stderr is feedback
# (to the subagent on SubagentStop, to the orchestrator on PostToolUse).
HOOK_EXIT_SILENT = 0
HOOK_EXIT_FEEDBACK = 2

# The dispatch tools the messenger leg gates: ``Agent``, and its pre-2.1.63 name ``Task``.
DISPATCH_TOOLS = frozenset({'Agent', 'Task'})

# A subagent that used none of these left the tree as it found it; the judge lets it go.
MUTATING_TOOLS = frozenset({'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Bash'})

HOOK_LOG_RELPATH = Path('.convoy') / 'hook.log'

# How far back the messenger looks for the judge's verdict on the same subagent.
_REUSE_WINDOW_SECONDS = 3600

# ``[convoy-phase: core]`` in the subagent's brief scopes the gate to that PR's checks —
# the same selection ``convoy gate --phase core`` makes. Repeatable; tags union.
_PHASE_MARKER = re.compile(r'\[convoy-phase:\s*([^\]]+)\]')


@dataclass(frozen=True)
class HookResult:
    """What the hook decided: the exit code, what to say on stderr, and the log record."""

    exit_code: int
    stderr: str
    record: dict[str, Any] | None


@dataclass(frozen=True)
class TranscriptFacts:
    """What the judge reads from a subagent transcript: its brief and whether it wrote."""

    brief: str
    mutated: bool
    readable: bool


def parse_phase_markers(prompt: str) -> tuple[str, ...]:
    """The phase tags a brief carries, in order of first appearance, de-duplicated."""
    seen: list[str] = []
    for match in _PHASE_MARKER.finditer(prompt):
        for tag in match.group(1).split(','):
            cleaned = tag.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
    return tuple(seen)


def read_transcript(path: Path) -> TranscriptFacts:
    """The first user turn (the brief) and the mutating tool uses of a subagent transcript.

    An unreadable transcript reads as ``mutated=True``: the judge gates what it cannot
    see, rather than waving it through.
    """
    brief = ''
    mutated = False
    try:
        with path.open(encoding=TEXT_ENCODING, errors=TEXT_ERRORS) as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                message = entry.get('message')
                content = message.get('content') if isinstance(message, dict) else None
                if entry.get('type') == 'user' and not brief and isinstance(content, str):
                    brief = content
                elif entry.get('type') == 'assistant' and isinstance(content, list):
                    for block in content:
                        if (
                            isinstance(block, dict)
                            and block.get('type') == 'tool_use'
                            and block.get('name') in MUTATING_TOOLS
                        ):
                            mutated = True
    except OSError:
        return TranscriptFacts(brief='', mutated=True, readable=False)
    return TranscriptFacts(brief=brief, mutated=mutated, readable=True)


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
        'agent_id': _string(tool_response, 'agentId') or _string(payload, 'agent_id'),
        'agent_type': _string(payload, 'agent_type'),
        'model': _string(tool_response, 'resolvedModel') or _string(tool_input, 'model'),
        'convoy_version': __version__,
        **fields,
    }


def log_path_for(spec_path: Path, cwd: Path) -> Path:
    """The hook log of the tree *spec_path* governs — the workspace, never the spec's own dir."""
    return gate_root(spec_path, cwd) / HOOK_LOG_RELPATH


def latest_stop_record(log_path: Path, agent_id: str) -> dict[str, Any] | None:
    """The judge's most recent verdict for *agent_id*, if the log has a fresh one."""
    if not agent_id or not log_path.is_file():
        return None
    try:
        lines = log_path.read_text(encoding=TEXT_ENCODING, errors=TEXT_ERRORS).splitlines()
    except OSError:
        return None
    latest: dict[str, Any] | None = None
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(entry, dict)
            and entry.get('event') == 'SubagentStop'
            and entry.get('agent_id') == agent_id
            and entry.get('outcome') in ('completed', 'blocked')
        ):
            latest = entry
    if latest is None:
        return None
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(str(latest.get('ts')))
    except ValueError:
        return None
    return latest if age.total_seconds() <= _REUSE_WINDOW_SECONDS else None


def _gate(
    payload: Mapping[str, Any],
    spec_path: Path,
    cwd: Path,
    phases: tuple[str, ...],
    env: Mapping[str, str],
) -> tuple[GateOutcome, int] | HookResult:
    """Run the gate: the outcome and its wall-clock, or the loud result of a usage failure."""
    started = time.monotonic()
    try:
        spec = load_gate_spec_file(spec_path, env, root=gate_root(spec_path, cwd))
        outcome = run_gate(spec, cwd, phases)
    except (OSError, UnicodeDecodeError, SpecError, GateUsageError) as exc:
        elapsed = round((time.monotonic() - started) * 1000)
        return HookResult(
            HOOK_EXIT_FEEDBACK,
            f'convoy hook: the gate could not run ({spec_path}): {exc}\n',
            _record(payload, outcome='usage', error=str(exc), phases=list(phases), gate_ms=elapsed),
        )
    return outcome, round((time.monotonic() - started) * 1000)


def _verdict_record(
    payload: Mapping[str, Any], outcome: GateOutcome, phases: tuple[str, ...], gate_ms: int
) -> dict[str, Any]:
    verdict = outcome.verdict
    results = verdict.results
    passed = sum(1 for result in results if result.passed)
    return _record(
        payload,
        outcome='blocked' if verdict.blocking_red else 'completed',
        phases=list(phases),
        blocking_red=verdict.blocking_red,
        independent_red=verdict.independent_red,
        counts={'selected': len(results), 'passed': passed, 'failed': len(results) - passed},
        checks=[{'name': result.check.name, 'passed': result.passed} for result in results],
        repair_brief=repair_brief(verdict),
        gate_ms=gate_ms,
    )


def _decide_stop(
    payload: Mapping[str, Any], spec_path: Path, cwd: Path, env: Mapping[str, str]
) -> HookResult:
    """The judge: gate the subagent's work as it tries to stop."""
    transcript = _string(payload, 'agent_transcript_path')
    facts = (
        read_transcript(Path(transcript))
        if transcript
        else TranscriptFacts(brief='', mutated=True, readable=False)
    )
    if facts.readable and not facts.mutated:
        return HookResult(
            HOOK_EXIT_SILENT,
            '',
            _record(payload, outcome='skipped', reason='read-only subagent: no mutating tool use'),
        )
    phases = parse_phase_markers(facts.brief)
    gated = _gate(payload, spec_path, cwd, phases, env)
    if isinstance(gated, HookResult):
        return gated
    outcome, gate_ms = gated
    record = _verdict_record(payload, outcome, phases, gate_ms)
    if not outcome.verdict.blocking_red:
        return HookResult(HOOK_EXIT_SILENT, '', record)
    if payload.get('stop_hook_active'):
        # One repair round is the bound: on the retry a residual red is recorded and the
        # subagent may stop, so a red it cannot fix never holds it forever.
        record['blocked_stop'] = False
        record['reason'] = 'residual red after the repair round; the subagent may stop'
        return HookResult(HOOK_EXIT_SILENT, '', record)
    record['blocked_stop'] = True
    scope = f' (phase {", ".join(phases)})' if phases else ''
    header = (
        f"convoy gate: BLOCKED{scope} — your work fails the project's gate. Repair it before "
        f'finishing; the gate re-runs when you stop again.\n'
    )
    return HookResult(HOOK_EXIT_FEEDBACK, header + repair_brief(outcome.verdict), record)


def _orchestrator_header(agent_id: str, phases: tuple[str, ...]) -> str:
    who = f'subagent {agent_id}' if agent_id else 'the subagent'
    scope = f' (phase {", ".join(phases)})' if phases else ''
    return (
        f'convoy gate: BLOCKED after {who}{scope} — dispatch a fix subagent with the brief '
        f'below; the gate re-runs when it returns.\n'
    )


def _decide_dispatch(
    payload: Mapping[str, Any], spec_path: Path, cwd: Path, env: Mapping[str, str]
) -> HookResult:
    """The messenger: after a synchronous dispatch returns, tell the orchestrator of a red."""
    tool_response = payload.get('tool_response')
    status = _string(tool_response, 'status')
    if status and status != 'completed':
        # An asynchronous dispatch returns before the subagent has done anything; a failed
        # one produced nothing to gate. Recorded, so the log shows the dispatch happened.
        return HookResult(
            HOOK_EXIT_SILENT,
            '',
            _record(payload, outcome='skipped', reason=f'dispatch status {status!r}'),
        )
    agent_id = _string(tool_response, 'agentId')
    judged = latest_stop_record(log_path_for(spec_path, cwd), agent_id)
    if judged is not None:
        phases = tuple(str(tag) for tag in judged.get('phases') or ())
        brief = str(judged.get('repair_brief') or '')
        record = _record(
            payload,
            outcome=str(judged['outcome']),
            phases=list(phases),
            reused_from=judged.get('ts'),
            counts=judged.get('counts'),
            repair_brief=brief,
        )
        if judged['outcome'] == 'completed':
            return HookResult(HOOK_EXIT_SILENT, '', record)
        return HookResult(
            HOOK_EXIT_FEEDBACK, _orchestrator_header(agent_id, phases) + brief, record
        )
    phases = parse_phase_markers(_string(payload.get('tool_input'), 'prompt'))
    gated = _gate(payload, spec_path, cwd, phases, env)
    if isinstance(gated, HookResult):
        return gated
    outcome, gate_ms = gated
    record = _verdict_record(payload, outcome, phases, gate_ms)
    if not outcome.verdict.blocking_red:
        return HookResult(HOOK_EXIT_SILENT, '', record)
    return HookResult(
        HOOK_EXIT_FEEDBACK,
        _orchestrator_header(agent_id, phases) + repair_brief(outcome.verdict),
        record,
    )


def decide(payload: Mapping[str, Any], env: Mapping[str, str]) -> HookResult:
    """The hook's whole decision, given the parsed event and the environment (no I/O on stdio).

    Runs the gate — check commands execute in the payload's ``cwd`` — and appends
    nothing; :func:`run_hook` owns the streams and the log.
    """
    event = _string(payload, 'hook_event_name')
    if event == 'PostToolUse':
        if _string(payload, 'tool_name') not in DISPATCH_TOOLS:
            return HookResult(HOOK_EXIT_SILENT, '', None)
    elif event != 'SubagentStop':
        return HookResult(HOOK_EXIT_SILENT, '', None)

    cwd = Path(_string(payload, 'cwd') or '.')
    try:
        spec_path = find_gate_spec(cwd, env)
    except SpecError as exc:
        # $CONVOY_GATE_SPEC names a file that is not there: the launcher asked for a
        # gate it cannot get, which must not read as a green one.
        return HookResult(
            HOOK_EXIT_FEEDBACK,
            f'convoy hook: {exc}\n',
            _record(payload, outcome='usage', error=str(exc)),
        )
    if spec_path is None:
        return HookResult(HOOK_EXIT_SILENT, '', None)

    root = gate_root(spec_path, cwd)
    try:
        trusted = is_trusted(root, env)
    except SpecError as exc:
        return HookResult(
            HOOK_EXIT_SILENT, '', _record(payload, outcome='untrusted', reason=str(exc))
        )
    if not trusted:
        return HookResult(
            HOOK_EXIT_SILENT,
            '',
            _record(
                payload,
                outcome='untrusted',
                reason=f'{root} is not on the hook trust list; run `convoy gate --trust` there',
            ),
        )

    if event == 'SubagentStop':
        return _decide_stop(payload, spec_path, cwd, env)
    return _decide_dispatch(payload, spec_path, cwd, env)


def append_log(spec_path: Path, cwd: Path, record: Mapping[str, Any]) -> str | None:
    """Append one JSON line to the project's hook log; return a message on failure."""
    log_path = log_path_for(spec_path, cwd)
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
        cwd = Path(_string(payload, 'cwd') or '.')
        try:
            spec_path = find_gate_spec(cwd, env)
        except SpecError:
            spec_path = None
        if spec_path is not None:
            failure = append_log(spec_path, cwd, {**result.record, 'spec': str(spec_path)})
            if failure is not None:
                sys.stderr.write(failure)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.exit_code
