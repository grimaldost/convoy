"""Folding a run's telemetry into the summary envelope (shell).

``summarize_run`` reads the append-only ``spawns.jsonl`` a run wrote and folds it into the
result envelope: economy totals plus a per-PR view. It lives here, not on a surface,
because it is **surface-bound by accident, not by coupling** — the MCP tool returns it as
a dict and the CLI emits it as JSON under ``--json``, and neither owns it. Keeping one
implementation is what stops the two surfaces reporting different totals for the same run,
and stops every external consumer re-implementing the per-spawn fold from the raw ledger.
"""

import json
from pathlib import Path
from typing import Any

from convoy.core.gate import GateUsageError
from convoy.core.governance import GovernanceError
from convoy.core.spec import Series, SpecError
from convoy.interface import detached
from convoy.interface.drivers.headless import (
    EXIT_BLOCKED,
    EXIT_BUDGET,
    EXIT_INFRASTRUCTURE,
    EXIT_OK,
    EXIT_USAGE,
    RunOutcome,
)
from convoy.interface.git import GitError
from convoy.interface.proc import process_is_alive
from convoy.interface.workspace_lock import WorkspaceBusyError, lock_owner_pid

# Cap the per-PR list projected inline; the full trace always stays on disk (§ telemetry_path).
_PR_CAP = 50

# outcome → the process exit code convoy would have returned for it. The mapping is the
# published contract (02-formats.md § Exit codes), which is what lets a terminal outcome be
# rebuilt from a ``run_complete`` line alone — no live ``RunOutcome`` needed.
#
# ``abandoned`` is the one entry no process ever actually returned: the run was killed, so
# there was no exit. It maps to the infrastructure code because that is the class it belongs
# to — the run stopped for a reason outside the work, and ``--resume`` is the recovery — and
# because a consumer branching on the exit code should treat it the same way.
_EXIT_BY_OUTCOME: dict[str, int] = {
    'completed': EXIT_OK,
    'blocked': EXIT_BLOCKED,
    'infrastructure': EXIT_INFRASTRUCTURE,
    'budget': EXIT_BUDGET,
    'abandoned': EXIT_INFRASTRUCTURE,
}

# The reason recorded on a ``run_abandoned`` line written by the recovery path.
ABANDONED_BY_CLEAN_REASON = 'workspace lock cleared by convoy clean; the run never returned'


def _run_lines(telemetry_path: Path, run_id: str | None = None) -> list[dict[str, Any]]:
    """Every parsed ledger line, optionally narrowed to one ``run_id``.

    A missing file is an empty ledger, not an error: a run that has not written its first
    line yet is a legitimate state for a poller to observe.
    """
    if not telemetry_path.exists():
        return []
    lines: list[dict[str, Any]] = []
    for raw in telemetry_path.read_text(encoding='utf-8').splitlines():
        if not raw.strip():
            continue
        entry = json.loads(raw)
        if run_id is None or entry.get('run_id') == run_id:
            lines.append(entry)
    return lines


def run_recorded(telemetry_path: Path, run_id: str) -> bool:
    """Whether ``run_id`` has written anything to the ledger yet.

    The ledger is append-only across runs, so folding two runs that share an id would
    silently sum their economies and report one of their halts. This is what lets a caller
    pinning its own id (``--run-id``) be refused before it does that.
    """
    return bool(_run_lines(telemetry_path, run_id))


def latest_run_id(telemetry_path: Path) -> str | None:
    """The most recent run's id in ``telemetry_path``, or ``None`` for an empty ledger.

    Run ids are minted as a UTC timestamp plus a random suffix precisely so they sort
    lexicographically by start time (see ``make_run_id``), which is what makes "the latest
    run" answerable from a ledger that accumulates many runs without tracking them.
    """
    ids = {entry['run_id'] for entry in _run_lines(telemetry_path) if 'run_id' in entry}
    return max(ids) if ids else None


def reconstruct_outcome(telemetry_path: Path, run_id: str) -> RunOutcome | None:
    """Rebuild a finished run's :class:`RunOutcome` from its ledger; ``None`` if still running.

    A run writes ``run_complete`` exactly once, at the end, carrying ``outcome`` and
    ``integrated``; the exit code follows from ``outcome`` by the published mapping. So the
    absence of that line is itself the signal that the run has not finished — which is what
    lets a poller distinguish "in progress" from "done" without convoy holding any state
    between calls.

    An unknown ``outcome`` value (a newer engine wrote the ledger) maps to the usage exit
    code rather than raising: a poller reading a ledger it half-understands should degrade,
    not crash.

    A ``run_abandoned`` line is terminal in the same sense and is read the same way: the run
    is over and will record nothing further. It reports ``outcome: 'abandoned'`` and
    ``integrated: False`` — whoever wrote it was not there for the run, so the only honest
    claim is that this run did not reach a completed integration.
    """
    for entry in _run_lines(telemetry_path, run_id):
        if entry.get('event') == 'run_complete':
            outcome = entry['outcome']
            return RunOutcome(
                outcome=outcome,
                integrated=entry['integrated'],
                exit_code=_EXIT_BY_OUTCOME.get(outcome, EXIT_USAGE),
            )
        if entry.get('event') == 'run_abandoned':
            return RunOutcome(
                outcome='abandoned',
                integrated=False,
                exit_code=_EXIT_BY_OUTCOME['abandoned'],
            )
    return None


def orphaned_run_id(telemetry_path: Path) -> str | None:
    """The most recent run in ``telemetry_path`` that recorded no terminal line.

    ``None`` when the ledger is empty or its latest run finished. Only the latest run is
    considered: a run that leaves the workspace lock behind blocks every later run until
    someone clears it, so the run that left it IS the latest one to have started.
    """
    run_id = latest_run_id(telemetry_path)
    if run_id is None or reconstruct_outcome(telemetry_path, run_id) is not None:
        return None
    return run_id


def unfinished_state(workspace: Path | None) -> str:
    """``'running'`` or ``'dead'`` for a run that has written no terminal record.

    A run acquires ``workspace``'s lock before it writes its first ledger line and holds it
    until it returns, so a run with ledger lines and no ``run_complete`` is either still
    holding that lock or was killed hard enough that no ``finally`` ran. The lock has always
    named its owner; reading it back is what separates the two.

    Deliberately conservative, and in one direction: ``dead`` is claimed **only** when the
    lock exists and names a process that does not. No lock file at all stays ``running``,
    because the commonest way to see that is asking from the wrong directory — and a false
    ``dead`` sends an operator to restart a run that is still spending. The other gap it
    leaves is a run that died and whose lock has since been cleared: a pid is reusable once
    its process is gone, so no live check can answer for it — repairing that history needs a
    terminal line written when the lock is cleared, not a query afterwards.
    """
    if workspace is None:
        return 'running'
    pid = lock_owner_pid(workspace)
    if pid is None:
        return 'running'
    return 'running' if process_is_alive(pid) else 'dead'


def summarize_run(
    telemetry_path: Path,
    *,
    run_id: str,
    series_id: str,
    outcome: RunOutcome | None,
    workspace: Path | None = None,
    pr_cap: int = _PR_CAP,
) -> dict[str, Any]:
    """Fold this run's telemetry lines into an agent-facing summary.

    Reads ``telemetry_path`` (convoy's append-only ``spawns.jsonl``), keeps only the lines
    tagged with ``run_id``, and aggregates them into economy totals and a per-PR view
    (spawn count, the implementation spawn's effective model, the latest gate verdict, any
    skip reason). The complete per-line trace stays on disk at ``telemetry_path`` —
    referenced here, never inlined. The per-PR list is capped at ``pr_cap`` with a
    ``truncated`` report.

    A PR can have several spawns (one implementation, then a fix spawn per repair attempt).
    ``effective_model`` is the implementation spawn's model — the spawn the tier decision
    governed and the one whose output the gate judged; a fix spawn is repair, not the
    measured attempt. It is selected by ``role``, not append order, so it does not depend
    on the implementation line being written before any fix line. It is ``None`` for a PR
    that never ran an implementation spawn (e.g. a skip). The per-spawn breakdown is in the
    trace.
    """
    economy = {
        'total_cost_usd': 0.0,
        'cost_estimated': False,
        'input_tokens': 0,
        'output_tokens': 0,
        'num_turns': 0,
        'spawn_count': 0,
    }
    prs: dict[str, dict[str, Any]] = {}
    halt: dict[str, Any] | None = None
    advisories: list[dict[str, Any]] = []

    def _pr(pr_id: str) -> dict[str, Any]:
        return prs.setdefault(
            pr_id,
            {
                'pr_id': pr_id,
                'spawns': 0,
                'effective_model': None,
                'gate': None,
                'skipped': False,
                'skip_reason': None,
                # The role of a spawn that started and has not completed, else ``None``.
                # On a live run this is "what convoy is doing right now"; on a run whose
                # driver was killed it is the PR the money was being spent on.
                'in_flight': None,
            },
        )

    if telemetry_path.exists():
        for line in telemetry_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get('run_id') != run_id:
                continue
            event = entry.get('event')
            if event == 'spawn_start':
                # Set on start and cleared on the matching completion, in append order —
                # the ledger is written in that order by construction, so what survives the
                # walk is exactly the spawn that never finished.
                _pr(entry['pr_id'])['in_flight'] = entry['role']
            elif event == 'spawn_complete':
                economy['total_cost_usd'] += entry['cost_usd']
                economy['input_tokens'] += entry['input_tokens']
                economy['output_tokens'] += entry['output_tokens']
                economy['num_turns'] += entry['num_turns']
                economy['spawn_count'] += 1
                economy['cost_estimated'] = economy['cost_estimated'] or entry.get(
                    'cost_estimated', False
                )
                pr = _pr(entry['pr_id'])
                pr['spawns'] += 1
                pr['in_flight'] = None
                # effective_model is the implementation spawn's model: the spawn the tier
                # decision governed and the one the gate judged. Keyed on role, not append
                # order — a fix spawn's model never overwrites it, whatever the line order.
                if entry['role'] == 'implementation' and pr['effective_model'] is None:
                    pr['effective_model'] = entry['effective_model']
            elif event == 'gate_complete':
                _pr(entry['pr_id'])['gate'] = {
                    'attempt': entry['attempt'],
                    'blocking_red': entry['blocking_red'],
                    'independent_red': entry['independent_red'],
                    'failing_checks': [
                        c['name'] for c in entry['checks'] if not c['passed'] and c['blocking']
                    ],
                }
            elif event == 'pr_skipped':
                pr = _pr(entry['pr_id'])
                pr['skipped'] = True
                pr['skip_reason'] = entry['reason']
            elif event == 'run_start':
                # Read from the ledger for the same reason ``halt`` is: it keeps the
                # envelope reconstructible from disk alone, so ``convoy_status`` reports
                # a run's advisories without having been the process that pre-flighted it.
                advisories = list(entry.get('advisories') or [])
            elif event == 'run_complete':
                # Read from the ledger rather than threaded through ``RunOutcome``: the
                # outcome is a control-flow value the driver returns, while this is
                # descriptive detail the run already wrote down. Reading it here also keeps
                # the envelope reconstructible from disk alone.
                halt = entry.get('halt')

    pr_list = list(prs.values())
    state = 'finished' if outcome is not None else unfinished_state(workspace)
    envelope: dict[str, Any] = {
        # ``state`` is the field to branch on first. ``finished`` means the terminal fields
        # below are meaningful; ``running`` means the run has not written ``run_complete``
        # yet, so they are ``null`` and the economy is a partial running total — genuinely
        # useful (what has it spent so far) but not a result. ``dead`` is ``running`` with
        # the additional fact that the process which would have finished it is gone: the
        # terminal fields are null and will stay that way, and the economy is final rather
        # than partial.
        'state': state,
        'ok': outcome is not None and outcome.outcome == 'completed',
        'outcome': None if outcome is None else outcome.outcome,
        'integrated': None if outcome is None else outcome.integrated,
        'exit_code': None if outcome is None else outcome.exit_code,
        'run_id': run_id,
        'series_id': series_id,
        'economy': economy,
        'prs': pr_list[:pr_cap],
        # ``None`` on a clean run; on a halt, the located reason: which PR, in which phase,
        # what hit it (a spawn role, or ``gate`` when the bounded fix loop was exhausted),
        # and for a budget halt the spend against the ceiling it hit.
        'halt': halt,
        # Always present, empty when there is nothing to say, so a consumer reads the key
        # unconditionally — the same shape and the same guarantee as the dry-run envelope.
        'advisories': advisories,
        'telemetry_path': str(telemetry_path),
        'truncated': {'any': len(pr_list) > pr_cap, 'prs': max(0, len(pr_list) - pr_cap)},
    }
    if state == 'dead':
        # Same shape as the ``unknown`` envelope's message: the state is the thing to branch
        # on, and the prose says what to do about it. Named here rather than left to the
        # reader because "dead" is the one state whose recovery is not obvious.
        envelope['message'] = (
            f'the process that was running {run_id} is gone and it recorded no outcome; '
            'run `convoy clean` to release the workspace, then re-run with --resume to '
            'continue from the PRs that already integrated'
        )
    return envelope


def status_of(
    series: Series,
    *,
    run_id: str = '',
    workspace: Path | None = None,
    pr_cap: int = _PR_CAP,
) -> dict[str, Any]:
    """The envelope for a run recorded in ``series``' outputs — finished or still going.

    The request-level status operation both surfaces share. It reads the ledger, so it works
    for a run this process never started: the supported long-run pattern is ``convoy run``
    in a background shell, and until now nothing could ask that run how it was doing. It
    holds no state between calls.

    ``run_id`` defaults to the most recent run in the ledger, which is the question a
    poller usually means. An empty ledger — no file yet, or a run that has not written its
    first line — returns ``state: "unknown"`` rather than an error: "no run has recorded
    anything here" is information, not a failure.

    ``workspace``, when given, is read for one thing and one thing only: the run lock's
    owner pid, which distinguishes a run still going from a run whose driver is gone (see
    :func:`unfinished_state`). Nothing is written and no git command runs. Omitted, the
    answer is exactly what it was before — a run with no terminal record reads ``running``
    — so a caller that cannot name the workspace is no worse off.

    A **detached** run can fail before it writes its first ledger line — an expired seat, a
    busy workspace, a git failure — and reporting that as ``running`` forever would be the
    worst answer available. So when the ledger holds nothing under the id, its own result
    file is consulted (see :func:`detached_result`) before falling back.
    """
    outputs = Path(series.paths.outputs)
    telemetry_path = outputs / 'spawns.jsonl'
    target = run_id or latest_run_id(telemetry_path) or ''
    if target and not run_recorded(telemetry_path, target):
        detached = detached_result(outputs, target)
        if detached is not None:
            return detached
    if not target:
        return {
            'state': 'unknown',
            'ok': False,
            'run_id': run_id,
            'series_id': series.id,
            'telemetry_path': str(telemetry_path),
            'message': f'no run recorded in {telemetry_path}',
        }
    return summarize_run(
        telemetry_path,
        run_id=target,
        series_id=series.id,
        outcome=reconstruct_outcome(telemetry_path, target),
        workspace=workspace,
        pr_cap=pr_cap,
    )


def detached_result(outputs: Path, run_id: str) -> dict[str, Any] | None:
    """The envelope a detached run wrote on exit, or ``None`` if there is not one yet.

    A detached child runs under ``--json``, so it writes exactly one envelope to
    ``<outputs>/<run_id>.json`` whatever happened — including the could-not-start shape.
    That file is the only record of a run that died before the engine wrote its first
    ledger line, which is why status consults it.

    The ledger is preferred whenever it has anything, so this is read only in that gap. A
    half-written file (caught mid-flush) does not parse and is treated as absent, which
    lands the caller back on ``running`` — correct, since the child is evidently still
    going. ``state`` is filled in when the envelope lacks it: the could-not-start shape
    predates ``state`` and is ``finished`` by construction, a run that will not advance.
    """
    path = detached.result_path(outputs, run_id)
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text(encoding='utf-8'))
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None
    return {'state': 'finished', **envelope}


def error_kind(exc: Exception) -> str:
    """Classify a could-not-start failure so an agent can branch on it, not parse a string.

    One of ``spec`` (invalid, malformed, or undecodable series — including a gate-only
    invocation the spec cannot answer, a ``GateUsageError``), ``governance``
    (unresolvable model/tier at runtime), ``git`` (a git operation failed), ``busy``
    (another run holds the workspace lock), or ``filesystem`` (any other ``OSError``).
    """
    if isinstance(exc, SpecError | UnicodeDecodeError | GateUsageError):
        return 'spec'
    if isinstance(exc, GovernanceError):
        return 'governance'
    if isinstance(exc, GitError):
        return 'git'
    if isinstance(exc, WorkspaceBusyError):
        return 'busy'
    return 'filesystem'
