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

A second, cheaper check runs before even that spawn: a seat whose refresh has already
failed leaves ``~/.claude/.credentials.json`` with ``claudeAiOauth.expiresAt`` in the
past (never repaired — the file is written back by the failed refresh attempt itself).
That state fails an actual probe spawn identically, so :func:`seat_problem` reads the
two expiry fields first (never the token) and names the state for free when it already
shows a dead seat: ``expiresAt`` past and ``refreshTokenExpiresAt`` still future means
the refresh failed and re-authenticating fixes it; both past means only a fresh login
will. Anything else about the file — absent (keychain-backed auth keeps none here),
unreadable, or a shape this cannot parse — defers to the spawn unchanged.
"""

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from convoy.core.governance import implementation_model_sources
from convoy.core.preflight import Problem
from convoy.core.spec import Series
from convoy.interface.config_isolation import credential_file, host_config_dir
from convoy.interface.spawn import AgentSpawn, SpawnRequest, SpawnResult

_PROBE_BRIEF = 'Reply with exactly: ok'
_PROBE_BUDGET_USD = 0.05
_PROBE_TIMEOUT_SECONDS = 120
# Enough of the probe's output to name the failure in the Problem message without
# dragging a whole stream dump into it.
_PROBE_MESSAGE_TAIL_CHARS = 500


def _credential_problem(where: str, environ: Mapping[str, str] | None) -> Problem | None:
    """A located Problem when the on-disk credential already shows a dead seat.

    ``None`` for every case that has to defer to the probe spawn instead: no credential
    file (keychain-backed auth keeps nothing here), one this process cannot read or
    parse, a shape that carries neither expiry field, or an access token that has not
    expired yet. Only positive evidence of the dead-seat shape short-circuits — the same
    conservative posture ``unfinished_state`` takes for a workspace lock's owner pid.
    """
    path = credential_file(host_config_dir(environ))
    if path is None:
        return None
    try:
        payload: Any = json.loads(path.read_text(encoding='utf-8'))
    except OSError, ValueError:
        return None
    oauth = payload.get('claudeAiOauth') if isinstance(payload, dict) else None
    if not isinstance(oauth, dict):
        return None
    expires_at = oauth.get('expiresAt')
    refresh_expires_at = oauth.get('refreshTokenExpiresAt')
    if not isinstance(expires_at, int | float) or not isinstance(refresh_expires_at, int | float):
        return None
    now_ms = time.time() * 1000
    if expires_at > now_ms:
        return None
    if refresh_expires_at > now_ms:
        message = (
            'the on-disk credential is already expired and its refresh failed to renew '
            'it: re-authenticate'
        )
    else:
        message = 'the on-disk credential and its refresh token have both expired: log in again'
    return Problem(kind='seat', where=where, message=message)


def seat_problem(
    spawn: AgentSpawn,
    series: Series,
    workspace: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Problem | None:
    """A located Problem when the seat cannot serve the run; ``None`` when it can.

    Probes every distinct model the run can spawn on — the ``[governance]`` model plus any
    per-PR override — so a model the seat cannot access fails here, in pre-flight, not at
    that PR after branches were staged. Probes in first-PR-seen order and STOPS at the first
    dead model: once the seat is proven unable to serve a model there is nothing to gain by
    paying to probe the rest. Before each spawn, the on-disk credential's expiry is checked
    for free (see :func:`_credential_problem`): a seat already in the dead-refresh shape is
    reported at zero spawn cost, never spent on to confirm. Each remaining probe costs
    ~$0.05 (usually 1-3 distinct models). Only an ``'infrastructure'`` classification (or a
    CLI that cannot start) blocks: ``'ok'`` and even ``'budget'`` prove the seat answered. A
    returned Problem's ``where`` names the section that declared the failing model —
    ``[governance]`` or the overriding PR's ``[[prs]]`` table — so the user is pointed at the
    config location that actually chose it.
    """
    for model, where, _origin in implementation_model_sources(series):
        credential_problem = _credential_problem(where, environ)
        if credential_problem is not None:
            return credential_problem
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
            return Problem(
                kind='seat',
                where=where,
                message=f'seat probe failed for model {model!r}: {_detail(result)}',
            )
    return None


def _detail(result: SpawnResult) -> str:
    """The failure, diagnosis first and raw stream after.

    The message used to be a 500-character tail of the CLI's own output — newline-delimited
    JSON plus stderr — so an expired seat read as a wall of noise with the one actionable
    sentence buried somewhere inside it, if it survived the cut at all. The adapter already
    knows which channel decided the classification (see ``headless_spawn._classify``), so it
    leads.

    The tail is kept, not replaced: the diagnosis is a summary, and the reader who needs the
    stream should not have to re-run a paid probe to see it. When there is no diagnosis to
    lead with the tail stands alone, which is exactly the previous behaviour — this can
    inform, never take away.
    """
    tail = ' '.join(result.output[-_PROBE_MESSAGE_TAIL_CHARS:].split()) or '(no output)'
    if not result.diagnosis:
        return tail
    return f'{result.diagnosis} [raw tail: {tail}]'
