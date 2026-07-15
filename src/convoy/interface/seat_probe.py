"""Pre-run seat viability probe (shell).

Two production runs halted at PR1 on an expired seat — after branches were staged —
with telemetry showing only ``exit_code: 1, $0``. This probe fails that run before any
git mutation instead: a minimal, tool-less, budget-capped spawn through the same
adapter (same credential-only config dir) the scored run will use, once per each
distinct resolved model the run can spawn on. An ``'infrastructure'`` classification —
auth, usage limit, retry exhaustion (see ``headless_spawn``) — or a CLI that cannot
start becomes a located :class:`~convoy.core.preflight.Problem`; anything else proves
the seat can serve that model. The probe is preflight, not a scored spawn: it writes no
telemetry line, and its cost is a few cents per model (bounded by
:data:`_PROBE_BUDGET_USD`).
"""

from pathlib import Path

from convoy.core.governance import implementation_model_sources
from convoy.core.preflight import Problem
from convoy.core.spec import Series
from convoy.interface.spawn import AgentSpawn, SpawnRequest

_PROBE_BRIEF = 'Reply with exactly: ok'
_PROBE_BUDGET_USD = 0.05
_PROBE_TIMEOUT_SECONDS = 120
# Enough of the probe's output to name the failure in the Problem message without
# dragging a whole stream dump into it.
_PROBE_MESSAGE_TAIL_CHARS = 500


def seat_problem(spawn: AgentSpawn, series: Series, workspace: Path) -> Problem | None:
    """A located Problem when the seat cannot serve the run; ``None`` when it can.

    Probes every distinct model the run can spawn on — the ``[governance]`` model plus any
    per-PR override — so a model the seat cannot access fails here, in pre-flight, not at
    that PR after branches were staged. Probes in first-PR-seen order and STOPS at the first
    dead model: once the seat is proven unable to serve a model there is nothing to gain by
    paying to probe the rest. Each probe costs ~$0.05 (usually 1-3 distinct models). Only an
    ``'infrastructure'`` classification (or a CLI that cannot start) blocks: ``'ok'`` and even
    ``'budget'`` prove the seat answered. A returned Problem's ``where`` names the section that
    declared the failing model — ``[governance]`` or the overriding PR's ``[[prs]]`` table — so
    the user is pointed at the config location that actually chose it.
    """
    for model, where in implementation_model_sources(series):
        request = SpawnRequest(
            brief=_PROBE_BRIEF,
            model=model,
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
                where=where,
                message=f'agent CLI could not start for the seat probe: {exc}',
            )
        if result.classification == 'infrastructure':
            tail = result.output[-_PROBE_MESSAGE_TAIL_CHARS:].strip() or '(no output)'
            return Problem(
                kind='seat',
                where=where,
                message=f'seat probe failed for model {model!r}: {tail}',
            )
    return None
