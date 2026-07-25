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

from convoy.core.governance import GovernanceError
from convoy.core.spec import SpecError
from convoy.interface.drivers.headless import RunOutcome
from convoy.interface.git import GitError
from convoy.interface.workspace_lock import WorkspaceBusyError

# Cap the per-PR list projected inline; the full trace always stays on disk (§ telemetry_path).
_PR_CAP = 50


def summarize_run(
    telemetry_path: Path,
    *,
    run_id: str,
    series_id: str,
    outcome: RunOutcome,
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
            if event == 'spawn_complete':
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

    pr_list = list(prs.values())
    return {
        'ok': outcome.outcome == 'completed',
        'outcome': outcome.outcome,
        'integrated': outcome.integrated,
        'exit_code': outcome.exit_code,
        'run_id': run_id,
        'series_id': series_id,
        'economy': economy,
        'prs': pr_list[:pr_cap],
        'telemetry_path': str(telemetry_path),
        'truncated': {'any': len(pr_list) > pr_cap, 'prs': max(0, len(pr_list) - pr_cap)},
    }


def error_kind(exc: Exception) -> str:
    """Classify a could-not-start failure so an agent can branch on it, not parse a string.

    One of ``spec`` (invalid, malformed, or undecodable series), ``governance``
    (unresolvable model/tier at runtime), ``git`` (a git operation failed), ``busy``
    (another run holds the workspace lock), or ``filesystem`` (any other ``OSError``).
    """
    if isinstance(exc, SpecError | UnicodeDecodeError):
        return 'spec'
    if isinstance(exc, GovernanceError):
        return 'governance'
    if isinstance(exc, GitError):
        return 'git'
    if isinstance(exc, WorkspaceBusyError):
        return 'busy'
    return 'filesystem'
