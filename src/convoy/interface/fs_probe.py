"""Fail-closed isolation guard for blocking independent checks (shell).

A check marked ``independent`` claims the implementer could not reach it. For a
*blocking* independent check that claim is load-bearing: if isolation does not
hold, the gate would silently degrade to self-grading — the exact thing the
marker was meant to prevent. So before such a check runs, its oracle ``asset``
must be shown to live out-of-tree and to exist. When it cannot, this probe
returns a synthetic FAILING ``CheckResult`` and the check is not run — the gate
fails closed rather than trusting an independence it cannot back.

The filesystem work (resolving paths, containment, existence) lives here; the
pure verdict in ``convoy.core.gate`` only ever sees pass/fail as data.
"""

from pathlib import Path

from convoy.core.gate import CheckResult
from convoy.core.spec import Check


def _fail(check: Check, reason: str) -> CheckResult:
    """A synthetic failing result for a check that cannot back its independence."""
    return CheckResult(check=check, passed=False, detail=f'isolation failed: {reason}')


def isolation_result(workspace: Path, check: Check) -> CheckResult | None:
    """Guard a blocking independent check, fail-closed.

    Returns a FAILING ``CheckResult`` when ``check`` is blocking and independent
    but cannot back that independence; returns ``None`` when the check is fine to
    run normally — either it is not a blocking independent check, or its ``asset``
    is genuinely out-of-tree and present.

    For a check where ``check.independent`` and ``check.blocking``:

    - no ``asset`` declared -> fail closed
    - ``asset`` resolves INSIDE ``workspace`` (asset == ws, or ws is an ancestor)
      -> fail closed
    - ``asset`` does not exist -> fail closed
    - otherwise -> ``None`` (isolated; run it)

    Non-blocking or non-independent checks always return ``None``.
    """
    if not (check.independent and check.blocking):
        return None

    if not check.asset:
        return _fail(check, 'blocking independent check declares no out-of-tree asset')

    # Resolve both sides so containment survives symlinks, ``..`` and relative
    # assets. ``strict=False``: a nonexistent asset must still resolve so we can
    # test containment, then report the missing path.
    ws = Path(workspace).resolve()
    asset = Path(check.asset).resolve()

    if asset == ws or ws in asset.parents:
        return _fail(check, f'asset {check.asset!r} is inside the scored workspace')

    if not asset.exists():
        return _fail(check, f'asset {check.asset!r} does not exist')

    return None
