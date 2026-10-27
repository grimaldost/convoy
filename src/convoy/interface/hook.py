"""``convoy hook`` — the gate as a Claude Code hook around subagent dispatch.

Two hook events, one gate, two legs:

- ``SubagentStop`` is the judge. When a subagent tries to finish, the hook runs the
  project's gate in the tree the spec governs. Green: exit 0, nothing said (but one
  stderr line, outside the model's context, when that tree is not the one the agent
  worked in). Blocking
  red: exit 2 with the repair brief on stderr, which Claude Code hands to the SUBAGENT as
  the reason it may not stop yet — the implementer repairs its own work, the same shape
  as a governed run's fix spawn — once: on the retry (``stop_hook_active``) a residual
  red lets the subagent stop and is recorded, and so does a gate that could not run. A
  subagent whose transcript shows only read-only tool use (a reader, a reviewer) is not
  gated; any tool the hook does not know is treated as a write.
- ``PostToolUse`` on ``Agent`` (or ``Task``) is the messenger, for synchronous dispatch.
  When the dispatch returns completed, the hook reuses the judge's verdict for that
  subagent from the log — same session, same agent, within the hour — or runs the gate
  when there is none, except for an agent the orchestrator dispatched with
  ``isolation: "worktree"``: with no judge record the tree this firing finds is the
  orchestrator's checkout, not the agent's worktree, so the messenger runs no gate, says on
  stderr (exit 0) that the agent was not judged, and logs ``skipped``. On a residual red it
  exits 2 with the brief on stderr, which Claude Code shows to the ORCHESTRATOR as feedback on
  the completed tool call — its cue to dispatch a fix subagent. An asynchronous dispatch
  (the Agent tool's default when ``run_in_background`` is unset) returns before the subagent
  has done anything (``async_launched``); it is recorded and not gated here, and its
  subagent is still judged at its stop.

The vocabulary is the hook protocol's, not convoy's: exit 0 means nothing to say, exit
2 means stderr is feedback. Nothing enters a model's context on a green gate.

Which spec, which tree. The nearest ``.convoy/gate.toml`` above the event's ``cwd`` is
judged (then ``$CLAUDE_PROJECT_DIR``'s, then a linked worktree's main checkout's), and an
agent working in a linked git worktree is judged in that worktree. A worktree that
carries the spec runs on its anchor's trust (``gate_service.trust_anchor``: the session
project, else git's main checkout) while its spec matches the anchor's trusted one. A
worktree with no spec of its own, or one whose copy cannot be vouched for (an anchor
trusted without a pin), is judged by the anchor's trusted spec, run in the worktree
(``gate_service.gated_tree``): the spec is read from where it was trusted, the checks see
the agent's edits. Either way the verdict is logged in the anchor, which outlives the
worktree and is where the orchestrator's messenger looks, and the default oracles dir is
the anchor's. A worktree spec that differs is refused loudly once and let through on the
retry, recorded. A worktree spec nothing trusted vouches for, under a trusted checkout
with no spec to judge it by, is not run: the firing says so on stderr (exit 0) and
leaves an ``untrusted`` line in that checkout's log. A tree that is no checkout of the
spec's repository (a separate repository nested in the project) is judged in the spec's
tree, and the verdict says so.

Three switches, all before anything executes. The presence of a project spec is the
per-project switch: with none found the hook exits 0 silently, so shipping it in the
plugin arms nothing until a project opts in. The operator's trust is the per-machine
switch: a spec in a project this machine has not trusted (``convoy gate --trust`` records
the root and the spec's hash; a harness sets ``CONVOY_TRUSTED_ROOTS``) is recorded in
this process's log record and not executed — and never written into that project. A spec
that changed since it was trusted is refused loudly (exit 2): the implementer edits the
tree the spec lives in, and a gate it can rewrite is no gate. A workspace a ``convoy
run`` is driving (its lock exists) is refused loudly too: the run's commit step stages
the whole tree. A gate that cannot run (an unreadable or invalid spec, a refused
invocation, a dead workspace) is exit 2 with a one-line reason — the loud answer,
because a hook that swallowed its own misconfiguration would look like a green gate.

The plugin does not start this process for the first two switches. Its handler runs
``hook_guard.py`` first, a standard-library script that exits 0 by itself when no spec is
found or the spec's project is not trusted, and delegates every other firing here with the
same stdin. Invoked directly, ``convoy hook`` still decides every case as described above.

Firings that gate one tree take turns. Several subagents stopping at once each fire the
judge, and two suites running in one tree share its caches and build output. A firing
that runs a gate holds ``.convoy/judge.lock`` from just before the gate until its log line
is written; another waits up to :data:`JUDGE_WAIT_SECONDS`, then gives up loudly (exit 2,
recorded as ``busy``). The wait is also bounded by what the gate needs: a firing waits only
as long as leaves its own gate's worst case (checks x ``timeout_seconds``) inside the hook
timeout. A gate inside the budget (``gate_service.GATE_BUDGET_SECONDS``, which the scaffold
fits and ``convoy validate`` warns past) leaves at least
``gate_service.JUDGE_MIN_WAIT_SECONDS``; a spec whose worst case fills the timeout does not
wait at all. On the retry a lock still held lets the subagent stop, recorded as ``busy``
with its own reason: the one stop the judge lets through without a verdict. The lock orders
judges. It does not make concurrent writers safe:
subagents that edit one tree at the same time need a tree each (a worktree per agent),
because each gate judges whatever the others have half-written.

Attestation: one JSON line per firing is appended to ``.convoy/hook.log`` under the
project root, or a worktree's anchor (the scaffold gitignores it): the leg, the event, the
verdict, the hook's exit code, the subagent's id, type and dated model, the phases, the
retry flag, the per-check facts, the gate's wall-clock, the spec's path and hash, the
workspace, the anchor, the agent's own tree and whether it was the one judged — so an
experiment counts firings from the log rather than from transcripts, and the messenger
finds the judge's verdict there. Each append holds ``.convoy/hook.log.lock``, so no two
lines interleave. Writing the log is best-effort and never changes the verdict.
"""

import hashlib
import json
import re
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from convoy import __version__
from convoy.core.gate import GateUsageError, repair_brief
from convoy.core.spec import SpecError
from convoy.interface.gate_service import (
    HOOK_MARGIN_SECONDS,
    HOOK_TIMEOUT_SECONDS,
    GateOutcome,
    find_gate_spec,
    gate_root,
    gated_tree,
    git_layout,
    has_own_entry,
    judged_target,
    load_gate_spec_file,
    oracles_root_for,
    refusal_reason,
    run_gate,
    trust_hint,
    working_tree_of,
)
from convoy.interface.proc import TEXT_ENCODING, TEXT_ERRORS
from convoy.interface.workspace_lock import JudgeBusyError, judge_lock, lock_path

# The hook protocol's exit codes — not convoy's. 0: nothing to say; 2: stderr is feedback
# (to the subagent on SubagentStop, to the orchestrator on PostToolUse).
HOOK_EXIT_SILENT = 0
HOOK_EXIT_FEEDBACK = 2

# The dispatch tools the messenger leg gates: ``Agent``, and its pre-2.1.63 name ``Task``.
DISPATCH_TOOLS = frozenset({'Agent', 'Task'})

# Tools that leave the tree as they found it. Anything else — a built-in editor, Bash,
# an MCP tool the hook has never heard of, a nested dispatch — counts as a write: the
# judge gates what it cannot see, rather than waving it through.
READ_ONLY_TOOLS = frozenset(
    {
        'Read',
        'Grep',
        'Glob',
        'LS',
        'WebFetch',
        'WebSearch',
        'TodoWrite',
        'TodoRead',
        'AskUserQuestion',
        'ListMcpResourcesTool',
        'ReadMcpResourceTool',
    }
)

HOOK_LOG_RELPATH = Path('.convoy') / 'hook.log'

# The lock a firing holds, next to the log, while it gates the tree and writes its line.
JUDGE_LOCK_NAME = 'judge.lock'

# The longest a firing waits for another firing's gate in the same tree before it gives up
# loudly, and how often it looks. Read when a firing starts waiting, so a test can shorten
# them. What a given firing actually waits is :func:`judge_wait_seconds`.
JUDGE_WAIT_SECONDS = HOOK_TIMEOUT_SECONDS / 3
JUDGE_POLL_SECONDS = 1.0

# Every append holds ``hook.log.lock`` for the milliseconds it takes, so the line of a
# firing that gave up waiting is written whole beside the holder's.
_APPEND_WAIT_SECONDS = 10.0
_APPEND_POLL_SECONDS = 0.01

# How far back the messenger looks for the judge's verdict on the same subagent.
_REUSE_WINDOW_SECONDS = 3600

# ``[convoy-phase: core]`` in the subagent's brief scopes the gate to that PR's checks —
# the same selection ``convoy gate --phase core`` makes. Repeatable; tags union.
_PHASE_MARKER = re.compile(r'\[convoy-phase:\s*([^\]]+)\]')


@dataclass(frozen=True)
class HookResult:
    """What the hook decided: the exit code, what to say on stderr, the log record and its log.

    *log_path* is where :func:`run_hook` appends the record; ``None`` when no tree was found
    to write it in.
    """

    exit_code: int
    stderr: str
    record: dict[str, Any] | None
    log_path: Path | None = None


@dataclass(frozen=True)
class JudgedTree:
    """What a firing judges by and where: the spec, the tree its checks run in, and the rest.

    *workspace* is the tree the checks run in: the spec's own tree, or the agent's worktree
    when a trusted spec from another checkout of the repository judges it
    (``gate_service.gated_tree``). *anchor* is the tree a linked worktree's trust came from
    (``gate_service.trust_anchor``), or the spec's tree when the checks run elsewhere: the
    verdict is logged there, because the worktree is deleted when its agent is done and
    the orchestrator's messenger looks there. *oracles_root* keys the default oracles dir.
    *lock* is the judge lock of *workspace*. *agent_tree* is the working tree the event's
    ``cwd`` lies in; *mismatch* says it is not the one judged. *fallback_from* is the
    nearest spec, when it was untrusted and an older discovery's spec was judged instead
    (``gate_service.fallback_gate``).
    """

    spec: Path
    workspace: Path
    oracles_root: Path
    log: Path
    lock: Path
    anchor: Path | None
    agent_tree: Path
    mismatch: bool
    fallback_from: Path | None = None


@dataclass(frozen=True)
class TranscriptFacts:
    """What the judge reads from a subagent transcript: its brief, its model, whether it wrote."""

    brief: str
    mutated: bool
    readable: bool
    model: str = ''


def parse_event(raw: bytes) -> dict[str, Any] | str:
    """The hook event object from stdin bytes, or the reason it is not one.

    Decoded as UTF-8 regardless of the locale: Claude Code writes the event as UTF-8, and
    a locale codec on a path with an accent would silently break discovery — the one
    failure a gate must not have, a green that never looked.
    """
    try:
        payload = json.loads(raw.decode(TEXT_ENCODING, errors=TEXT_ERRORS))
    except ValueError as exc:
        return f'stdin was not hook JSON: {exc}'
    if not isinstance(payload, dict):
        return 'stdin was not a hook event object'
    return payload


def parse_phase_markers(prompt: str) -> tuple[str, ...]:
    """The phase tags a brief carries, in order of first appearance, de-duplicated."""
    seen: list[str] = []
    for match in _PHASE_MARKER.finditer(prompt):
        for tag in match.group(1).split(','):
            cleaned = tag.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
    return tuple(seen)


def _text_of(content: Any) -> str:
    """A user turn's text, whether the transcript stores it as a string or as blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(block.get('text', ''))
            for block in content
            if isinstance(block, dict) and block.get('type') == 'text'
        ]
        return '\n'.join(part for part in parts if part)
    return ''


def read_transcript(path: Path) -> TranscriptFacts:
    """The brief (first user turn), the model, and whether the subagent used a writing tool.

    An unreadable transcript reads as ``mutated=True``: the judge gates what it cannot
    see, rather than waving it through.
    """
    brief = ''
    model = ''
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
                if not isinstance(message, dict):
                    continue
                content = message.get('content')
                if entry.get('type') == 'user' and not brief:
                    brief = _text_of(content)
                elif entry.get('type') == 'assistant':
                    model = str(message.get('model') or model)
                    if isinstance(content, list):
                        for block in content:
                            if (
                                isinstance(block, dict)
                                and block.get('type') == 'tool_use'
                                and block.get('name') not in READ_ONLY_TOOLS
                            ):
                                mutated = True
    except OSError:
        return TranscriptFacts(brief='', mutated=True, readable=False)
    return TranscriptFacts(brief=brief, mutated=mutated, readable=True, model=model)


def _string(mapping: Any, key: str) -> str:
    value = mapping.get(key) if isinstance(mapping, Mapping) else None
    return value if isinstance(value, str) else ''


def _record(payload: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    tool_input = payload.get('tool_input')
    tool_response = payload.get('tool_response')
    event = _string(payload, 'hook_event_name')
    return {
        'ts': datetime.now(UTC).isoformat(timespec='milliseconds'),
        'event': event,
        'leg': 'judge' if event == 'SubagentStop' else 'messenger',
        'tool_name': _string(payload, 'tool_name'),
        'tool_use_id': _string(payload, 'tool_use_id'),
        'session_id': _string(payload, 'session_id'),
        'agent_id': _string(tool_response, 'agentId') or _string(payload, 'agent_id'),
        'agent_type': _string(payload, 'agent_type') or _string(tool_response, 'agentType'),
        'model': _string(tool_response, 'resolvedModel') or _string(tool_input, 'model'),
        'stop_hook_active': bool(payload.get('stop_hook_active', False)),
        'cwd': _string(payload, 'cwd'),
        'convoy_version': __version__,
        **fields,
    }


def _finish(result: HookResult) -> HookResult:
    """Stamp the hook's own exit code onto the record, so the log says what was said."""
    if result.record is not None:
        result.record['exit_code'] = result.exit_code
    return result


def spec_sha256(spec_path: Path) -> str:
    try:
        return hashlib.sha256(spec_path.read_bytes()).hexdigest()
    except OSError:
        return ''


def log_path_for(spec_path: Path, cwd: Path) -> Path:
    """The hook log of the tree *spec_path* governs — the workspace, never the spec's own dir."""
    return gate_root(spec_path, cwd) / HOOK_LOG_RELPATH


def _mismatch(cwd: Path, workspace: Path) -> bool:
    """Whether the gate runs in another working tree than the one the event's ``cwd`` is in.

    A subdirectory of the judged tree is the same tree; a worktree nested under it is not.
    Outside git, a ``cwd`` outside the workspace is a mismatch.
    """
    own, judged = working_tree_of(cwd), working_tree_of(workspace)
    if own is None or judged is None:
        return not Path(cwd).resolve().is_relative_to(Path(workspace).resolve())
    return own != judged


def _judged_line(spec: Any, workspace: Any) -> str:
    """The line that names the tree a verdict is about and the spec it was judged by."""
    return f'convoy gate: judged {workspace} against {spec}\n'


def _notice(tree: JudgedTree) -> str:
    """What a verdict says about the tree it judged, when that is not the agent's own ('' else).

    Said on a green too: a red that exists only in the agent's tree passes unseen when the
    gate ran in another one, and this line is the trace of that.
    """
    lines = ''
    if tree.fallback_from is not None:
        lines += (
            f'convoy gate: the nearest gate spec {tree.fallback_from} is not vouched for by a '
            f'trusted spec, so the gate ran in {tree.workspace} with {tree.spec} instead\n'
        )
    if tree.mismatch:
        lines += (
            _judged_line(tree.spec, tree.workspace).rstrip('\n')
            + f' — not {tree.agent_tree}, the tree this agent worked in; a red only there '
            f'was not judged\n'
        )
    return lines


def judge_lock_path(spec_path: Path, cwd: Path) -> Path:
    """The judge lock of the tree *spec_path* governs: beside its hook log, in ``.convoy/``.

    Not under ``.git``: a tree the hook gates need not be a repository, and in a git
    worktree ``.git`` is a file. A scaffolded ``.convoy/.gitignore`` ignores the lock; in
    a project scaffolded before it did, the file shows as untracked while a gate runs.
    """
    return log_path_for(spec_path, cwd).parent / JUDGE_LOCK_NAME


def visiting_lock_path(log: Path, workspace: Path) -> Path:
    """The judge lock of *workspace* when its checks come from another tree's spec.

    Kept beside that tree's log, where the scaffold's ``judge.lock*`` ignore covers it, and
    named after *workspace*: the agent's worktree gets no file, and two worktrees, or a
    worktree and the project, never wait for each other's gate.
    """
    key = hashlib.sha256(str(Path(workspace).resolve()).encode('utf-8')).hexdigest()[:16]
    return log.parent / f'{JUDGE_LOCK_NAME}.{key}'


def judge_wait_seconds(worst_case: float) -> float:
    """How long a firing may wait for the judge lock, given its own gate's worst case.

    The wait and the gate run one after the other under one hook timeout, and Claude Code
    kills a hook that outlasts it without a word. So the wait is the lesser of
    :data:`JUDGE_WAIT_SECONDS` and what the timeout leaves after the gate's worst case and
    ``HOOK_MARGIN_SECONDS``: at least ``JUDGE_MIN_WAIT_SECONDS`` for a gate inside
    ``GATE_BUDGET_SECONDS``, zero when the gate alone fills the timeout.
    """
    room = HOOK_TIMEOUT_SECONDS - HOOK_MARGIN_SECONDS - worst_case
    return max(0.0, min(JUDGE_WAIT_SECONDS, room))


# Called with the judge lock's path and the gate's worst-case seconds just before a gate
# runs. :func:`decide` alone takes no lock; :func:`run_hook` passes one that takes it and
# keeps it until the log line is written.
type Hold = Callable[[Path, float], None]


def _unheld(_lock: Path, _worst_case: float) -> None:
    return None


def latest_stop_record(
    log_path: Path, agent_id: str, session_id: str = ''
) -> dict[str, Any] | None:
    """The judge's most recent verdict for *agent_id* in *session_id*, if the log has a fresh one.

    Keyed on the session as well as the agent: a ``hook.log`` is in-tree state, and a
    committed one cannot know the session id Claude Code assigned this run.
    """
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
            and entry.get('session_id') == session_id
            and entry.get('outcome') in ('completed', 'blocked', 'skipped', 'spec_changed')
        ):
            latest = entry
    if latest is None:
        return None
    try:
        stamped = datetime.fromisoformat(str(latest.get('ts')))
        if stamped.tzinfo is None:
            return None
        age = datetime.now(UTC) - stamped
    except TypeError, ValueError:
        return None
    return latest if age.total_seconds() <= _REUSE_WINDOW_SECONDS else None


def _gate(
    payload: Mapping[str, Any],
    tree: JudgedTree,
    phases: tuple[str, ...],
    env: Mapping[str, str],
    hold: Hold,
) -> tuple[GateOutcome, int, str] | HookResult:
    """Run the gate: the outcome, its wall-clock and the spec id, or the loud result.

    A judge lock another firing still holds when the wait runs out is answered like a gate
    that could not run, but recorded as ``busy``, not ``usage``: nothing is wrong with the
    spec or the tree, another firing was gating it.
    """
    spec_path, workspace = tree.spec, tree.workspace
    started = time.monotonic()
    try:
        # Loaded before the lock is taken: how long a firing may wait depends on its gate.
        spec = load_gate_spec_file(spec_path, env, root=tree.oracles_root)
        hold(tree.lock, len(spec.checks) * spec.timeout_seconds)
        started = time.monotonic()
        outcome = run_gate(spec, workspace, phases)
    except (OSError, UnicodeDecodeError, SpecError, GateUsageError, JudgeBusyError) as exc:
        elapsed = round((time.monotonic() - started) * 1000)
        return HookResult(
            HOOK_EXIT_FEEDBACK,
            f'convoy hook: the gate could not run ({spec_path}): {exc}\n',
            _record(
                payload,
                outcome='busy' if isinstance(exc, JudgeBusyError) else 'usage',
                error=str(exc),
                phases=list(phases),
                gate_ms=elapsed,
            ),
        )
    return outcome, round((time.monotonic() - started) * 1000), spec.id


def _verdict_record(
    payload: Mapping[str, Any],
    outcome: GateOutcome,
    phases: tuple[str, ...],
    gate_ms: int,
    series_id: str,
) -> dict[str, Any]:
    verdict = outcome.verdict
    results = verdict.results
    passed = sum(1 for result in results if result.passed)
    return _record(
        payload,
        outcome='blocked' if verdict.blocking_red else 'completed',
        series_id=series_id,
        phases=list(phases),
        blocking_red=verdict.blocking_red,
        independent_red=verdict.independent_red,
        counts={'selected': len(results), 'passed': passed, 'failed': len(results) - passed},
        checks=[
            {
                'name': result.check.name,
                'passed': result.passed,
                'blocking': result.check.blocking,
                'independent': result.check.independent,
                'exit_code': result.exit_code,
                'timed_out': result.timed_out,
                'detail': result.detail,
            }
            for result in results
        ],
        repair_brief=repair_brief(verdict),
        gate_ms=gate_ms,
    )


def _decide_stop(
    payload: Mapping[str, Any],
    tree: JudgedTree,
    env: Mapping[str, str],
    hold: Hold,
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
            _record(
                payload,
                outcome='skipped',
                reason='read-only subagent: no writing tool use',
                model=facts.model,
            ),
        )
    retry = bool(payload.get('stop_hook_active'))
    phases = parse_phase_markers(facts.brief)
    gated = _gate(payload, tree, phases, env, hold)
    if isinstance(gated, HookResult):
        if retry:
            # The gate could not run on the retry either; the subagent cannot act on
            # that (it cannot edit its brief or the spec, or free another firing's lock),
            # so it may stop. Recorded, and a busy tree under its own reason: that stop
            # carries no verdict, and the log is where it can be counted.
            record = dict(gated.record or {})
            record['reason'] = (
                'judge lock still held on the retry; the subagent stops ungated'
                if record.get('outcome') == 'busy'
                else 'gate could not run on the retry; the subagent may stop'
            )
            return HookResult(HOOK_EXIT_SILENT, '', record)
        if (gated.record or {}).get('outcome') == 'busy':
            # Waiting is all the subagent can do about another firing's lock, and its next
            # stop is the retry: it gates again, or stops ungated if the lock is still held.
            return replace(gated, stderr=gated.stderr.rstrip('\n') + '; stopping again retries\n')
        return gated
    outcome, gate_ms, series_id = gated
    record = _verdict_record(payload, outcome, phases, gate_ms, series_id)
    record['model'] = record['model'] or facts.model
    if not outcome.verdict.blocking_red:
        return HookResult(HOOK_EXIT_SILENT, _notice(tree), record)
    if retry:
        # One repair round is the bound: on the retry a residual red is recorded and the
        # subagent may stop, so a red it cannot fix never holds it forever.
        record['blocked_stop'] = False
        record['reason'] = 'residual red after the repair round; the subagent may stop'
        return HookResult(HOOK_EXIT_SILENT, _notice(tree), record)
    record['blocked_stop'] = True
    scope = f' (phase {", ".join(phases)})' if phases else ''
    header = (
        f"convoy gate: BLOCKED{scope} — your work fails the project's gate. Repair it before "
        f'finishing; the gate re-runs when you stop again.\n'
    )
    return HookResult(
        HOOK_EXIT_FEEDBACK,
        header
        + _judged_line(tree.spec, tree.workspace)
        + (_notice(replace(tree, mismatch=False)))
        + repair_brief(outcome.verdict),
        record,
    )


def _orchestrator_header(agent_id: str, phases: tuple[str, ...]) -> str:
    who = f'subagent {agent_id}' if agent_id else 'the subagent'
    scope = f' (phase {", ".join(phases)})' if phases else ''
    return (
        f'convoy gate: BLOCKED after {who}{scope} — dispatch a fix subagent with the brief '
        f'below; the gate re-runs when it returns.\n'
    )


def _decide_dispatch(
    payload: Mapping[str, Any],
    tree: JudgedTree,
    env: Mapping[str, str],
    hold: Hold,
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
    # A worktree agent's judge logs in the worktree's anchor, the tree this firing found:
    # its verdict is reused here rather than a second gate run in this tree.
    judged = latest_stop_record(tree.log, agent_id, _string(payload, 'session_id'))
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
            judged_workspace=judged.get('workspace'),
            judged_spec=judged.get('spec'),
            judged_tree_mismatch=judged.get('tree_mismatch'),
        )
        line = _judged_line(judged.get('spec'), judged.get('workspace'))
        if judged['outcome'] == 'spec_changed':
            record['reason'] = judged.get('reason')
            who = f'subagent {agent_id}' if agent_id else 'the subagent'
            return HookResult(
                HOOK_EXIT_FEEDBACK,
                f'convoy gate: REFUSED for {who} — its work was not judged.\n'
                f'{judged.get("reason") or ""}\n',
                record,
            )
        if judged['outcome'] != 'blocked':
            notice = line if judged.get('tree_mismatch') else ''
            return HookResult(HOOK_EXIT_SILENT, notice, record)
        return HookResult(
            HOOK_EXIT_FEEDBACK, _orchestrator_header(agent_id, phases) + line + brief, record
        )
    if _string(payload.get('tool_input'), 'isolation') == 'worktree':
        # The agent worked in a worktree of its own and the judge left no record of it, so the
        # only tree this firing can run the gate in is the orchestrator's checkout: a green
        # there says nothing about the agent's work. Said once, not gated.
        who = f'subagent {agent_id}' if agent_id else 'the subagent'
        return HookResult(
            HOOK_EXIT_SILENT,
            f'convoy gate: {who} was not judged — it was worktree-isolated and the judge '
            f'left no record, and this tree is not its worktree.\n',
            _record(
                payload,
                outcome='skipped',
                reason='worktree-isolated dispatch with no judge record: not gated in this tree',
            ),
        )
    phases = parse_phase_markers(_string(payload.get('tool_input'), 'prompt'))
    gated = _gate(payload, tree, phases, env, hold)
    if isinstance(gated, HookResult):
        return gated
    outcome, gate_ms, series_id = gated
    record = _verdict_record(payload, outcome, phases, gate_ms, series_id)
    if not outcome.verdict.blocking_red:
        return HookResult(HOOK_EXIT_SILENT, _notice(tree), record)
    return HookResult(
        HOOK_EXIT_FEEDBACK,
        _orchestrator_header(agent_id, phases)
        + _judged_line(tree.spec, tree.workspace)
        + _notice(replace(tree, mismatch=False))
        + repair_brief(outcome.verdict),
        record,
    )


def decide(payload: Mapping[str, Any], env: Mapping[str, str], hold: Hold = _unheld) -> HookResult:
    """The hook's whole decision, given the parsed event and the environment (no I/O on stdio).

    Runs the gate — check commands execute in the tree the spec governs — and appends
    nothing; :func:`run_hook` owns the streams, the log and the judge lock. *hold* is
    called with the lock's path just before a gate runs, so nothing that answers without
    running one (a read-only subagent, a reused verdict, a refusal) waits for it.
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
        return _finish(
            HookResult(
                HOOK_EXIT_FEEDBACK,
                f'convoy hook: {exc}\n',
                _record(payload, outcome='usage', error=str(exc)),
            )
        )
    if spec_path is None:
        return HookResult(HOOK_EXIT_SILENT, '', None)

    try:
        # When the nearest spec is not vouched for and the tree discovery judged before
        # CONV-B75 is trusted, that tree is judged, and the verdict says so, rather than a
        # tree that was gated going silent (gate_service.fallback_gate).
        target = judged_target(spec_path, cwd, env)
        trust_advice = refusal_reason(target, env)
    except SpecError as exc:
        workspace = gate_root(spec_path, cwd)
        return _finish(
            HookResult(
                HOOK_EXIT_SILENT,
                '',
                _record(
                    payload, outcome='untrusted', reason=str(exc), **_stamp(spec_path, workspace)
                ),
            )
        )
    spec_path, home, decision = target.spec, target.workspace, target.decision
    agent_tree = working_tree_of(cwd) or cwd.resolve()
    # A trusted spec from another checkout of the repository runs in the agent's worktree,
    # the tree that holds its edits; the spec's own tree keeps the log and the oracles.
    moved = gated_tree(target, agent_tree)
    visiting = moved != Path(home).resolve()
    workspace = moved if visiting else home
    log = (decision.anchor or home) / HOOK_LOG_RELPATH
    tree = JudgedTree(
        spec=spec_path,
        workspace=workspace,
        oracles_root=oracles_root_for(home, env),
        log=log,
        lock=visiting_lock_path(log, workspace) if visiting else judge_lock_path(spec_path, home),
        anchor=decision.anchor or (Path(home).resolve() if visiting else None),
        agent_tree=agent_tree,
        mismatch=_mismatch(cwd, workspace),
        fallback_from=target.fallback_from,
    )
    stamp = {
        **_stamp(spec_path, workspace),
        'anchor': str(tree.anchor) if tree.anchor is not None else None,
        'agent_tree': str(tree.agent_tree),
        'tree_mismatch': tree.mismatch,
    }
    if tree.fallback_from is not None:
        stamp['fallback_from'] = str(tree.fallback_from)

    def finish(result: HookResult) -> HookResult:
        return _finish(replace(result, log_path=tree.log))

    if decision.status == 'untrusted':
        record = _record(payload, outcome='untrusted', reason=trust_advice, **stamp)
        if decision.anchor is not None and has_own_entry(decision.anchor, env):
            # The checkout the worktree is made from is trusted, but nothing it holds vouches
            # for the worktree's spec, and it has no spec to judge the worktree by instead.
            # The operator opted that checkout in, so the unjudged agent leaves a trace there.
            message = (
                f'convoy gate: {tree.agent_tree} was not judged — its gate spec {spec_path} is '
                f'not vouched for, and {decision.anchor}, the trusted checkout it is made from, '
                f'has no gate spec to judge it by; {trust_hint(home, env)}'
            )
            record['reason'] = message
            return finish(HookResult(HOOK_EXIT_SILENT, message + '\n', record))
        return _finish(HookResult(HOOK_EXIT_SILENT, '', record))
    agent_in_worktree = tree.mismatch and _is_linked_worktree(tree.agent_tree)
    if decision.status == 'changed' and agent_in_worktree:
        # Reached through the fallback: the agent works in a worktree, and the tree judged
        # for it has a spec edited since it was trusted. The operator's to settle.
        return finish(
            _refuse_for_operator(
                payload,
                event,
                f'convoy hook: for the operator — {trust_advice}. The agent working in '
                f'{tree.agent_tree} was not judged. Nothing here is for the subagent to repair.',
                stamp,
            )
        )
    if decision.status == 'changed':
        message = f'convoy hook: {trust_advice}'
        return finish(
            HookResult(
                HOOK_EXIT_FEEDBACK,
                message + '\n',
                _record(payload, outcome='spec_changed', reason=message, **stamp),
            )
        )
    if decision.status == 'differs':
        return finish(
            _refuse_for_operator(
                payload,
                event,
                f'convoy hook: for the operator — {trust_advice}, so the gate was not run. '
                f'Nothing here is for the subagent to repair.',
                stamp,
            )
        )
    if lock_path(workspace).exists():
        message = (
            f'convoy hook: a convoy run holds {workspace} (lock present); the hook does not '
            f'gate a driven workspace'
        )
        return finish(
            HookResult(
                HOOK_EXIT_FEEDBACK,
                message + '\n',
                _record(payload, outcome='usage', error=message, **stamp),
            )
        )

    if event == 'SubagentStop':
        result = _decide_stop(payload, tree, env, hold)
    else:
        result = _decide_dispatch(payload, tree, env, hold)
    if result.record is not None:
        result.record.update(stamp)
    return finish(result)


def _stamp(spec_path: Path, workspace: Path) -> dict[str, Any]:
    return {
        'spec': str(spec_path),
        'spec_sha256': spec_sha256(spec_path),
        'workspace': str(workspace),
    }


def _is_linked_worktree(path: Path) -> bool:
    layout = git_layout(path)
    return layout is not None and layout.linked


def _refuse_for_operator(
    payload: Mapping[str, Any], event: str, message: str, stamp: Mapping[str, Any]
) -> HookResult:
    """A refusal the subagent cannot act on: loud once, then let through on the retry.

    The difference is the operator's to settle (a worktree made from a commit whose spec is
    not the trusted one, or a spec edited since it was trusted), not the subagent's: the
    message is addressed to the operator and never tells anyone to trust a worktree, which
    would pin the worktree's own spec. On the judge's retry the subagent stops unjudged and
    the refusal is recorded, where the messenger reports it to the orchestrator — a
    refusal the subagent cannot act on must not hold it forever.
    """
    retry = event == 'SubagentStop' and bool(payload.get('stop_hook_active'))
    if retry:
        record = _record(
            payload,
            outcome='spec_changed',
            reason=message + ' Refused again on the retry; the subagent stopped unjudged.',
            blocked_stop=False,
            **stamp,
        )
        return HookResult(HOOK_EXIT_SILENT, '', record)
    tail = (
        ' Stopping again lets the subagent finish; the refusal is recorded for the orchestrator.'
        if event == 'SubagentStop'
        else ''
    )
    record = _record(payload, outcome='spec_changed', reason=message, **stamp)
    return HookResult(HOOK_EXIT_FEEDBACK, message + tail + '\n', record)


def append_log(log_path: Path, record: Mapping[str, Any]) -> str | None:
    """Append one JSON line to the hook log at *log_path*; return a message on failure.

    Under ``hook.log.lock``: ``open('a')`` is not atomic across processes on Windows, and
    a firing that gave up on the judge lock writes its line while the holder may be
    writing one.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with (
            judge_lock(
                log_path.with_name(log_path.name + '.lock'),
                wait_seconds=_APPEND_WAIT_SECONDS,
                poll_seconds=_APPEND_POLL_SECONDS,
            ),
            log_path.open('a', encoding='utf-8') as handle,
        ):
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    except (OSError, JudgeBusyError) as exc:
        return f'convoy hook: could not append {log_path}: {exc}\n'
    return None


def run_hook(raw: bytes, env: Mapping[str, str]) -> int:
    """Parse the event, decide, write stderr and the log, return the hook exit code.

    A firing that runs a gate holds the tree's judge lock from just before the gate until
    its log line is written, so two firings never gate one tree at once. One that waits
    out :func:`judge_wait_seconds` is answered as a gate that could not run, recorded as
    ``busy``.
    """
    payload = parse_event(raw)
    if isinstance(payload, str):
        sys.stderr.write(f'convoy hook: {payload}\n')
        return HOOK_EXIT_FEEDBACK

    with ExitStack() as held:

        def hold(lock: Path, worst_case: float) -> None:
            held.enter_context(
                judge_lock(
                    lock,
                    wait_seconds=judge_wait_seconds(worst_case),
                    poll_seconds=JUDGE_POLL_SECONDS,
                )
            )

        result = decide(payload, env, hold)
        # An untrusted project gets no file written into it: the machine refused it, and a
        # log line in a clone's tree would be the first trace the refusal left. ``decide``
        # names no log for one; an ``untrusted`` line it does name goes to a trusted checkout.
        if result.record is not None and result.log_path is not None:
            failure = append_log(result.log_path, result.record)
            if failure is not None:
                sys.stderr.write(failure)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.exit_code
