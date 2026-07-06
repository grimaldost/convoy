"""Pre-run seat viability probe (shell).

Two production runs halted at PR1 on an expired seat — after branches were staged —
with telemetry showing only ``exit_code: 1, $0``. This probe fails that run before any
git mutation instead: a minimal, tool-less, budget-capped spawn through the same
adapter (same credential-only config dir, same resolved model) the scored run will
use. An ``'infrastructure'`` classification — auth, usage limit, retry exhaustion (see
``headless_spawn``) — or a CLI that cannot start becomes a located
:class:`~convoy.core.preflight.Problem`; anything else proves the seat can serve the
run. The probe is preflight, not a scored spawn: it writes no telemetry line, and its
cost is a few cents (bounded by :data:`_PROBE_BUDGET_USD`).
"""

from pathlib import Path

from convoy.core.governance import resolve_spawn
from convoy.core.preflight import Problem
from convoy.core.spec import Governance
from convoy.interface.spawn import AgentSpawn, SpawnRequest

_PROBE_BRIEF = 'Reply with exactly: ok'
_PROBE_BUDGET_USD = 0.05
_PROBE_TIMEOUT_SECONDS = 120
# Enough of the probe's output to name the failure in the Problem message without
# dragging a whole stream dump into it.
_PROBE_MESSAGE_TAIL_CHARS = 500


def seat_problem(spawn: AgentSpawn, governance: Governance, workspace: Path) -> Problem | None:
    """A located Problem when the seat cannot serve the run; ``None`` when it can.

    Probes with the run's own resolved implementation model, so a model the seat
    cannot access fails here too — not at PR1. Only an ``'infrastructure'``
    classification (or a CLI that cannot start) blocks: ``'ok'`` and even ``'budget'``
    prove the seat answered.
    """
    governed = resolve_spawn(governance, 'implementation')
    request = SpawnRequest(
        brief=_PROBE_BRIEF,
        model=governed.model,
        effort='low',
        permission_mode='default',
        budget_usd=_PROBE_BUDGET_USD,
        tools=(),
        timeout_seconds=_PROBE_TIMEOUT_SECONDS,
    )
    try:
        result = spawn.spawn(request, workspace)
    except OSError as exc:
        return Problem(
            kind='seat',
            where='[governance]',
            message=f'agent CLI could not start for the seat probe: {exc}',
        )
    if result.classification == 'infrastructure':
        tail = result.output[-_PROBE_MESSAGE_TAIL_CHARS:].strip() or '(no output)'
        return Problem(
            kind='seat',
            where='[governance]',
            message=f'seat probe failed for model {governed.model!r}: {tail}',
        )
    return None
