"""Pre-flight validation of a loaded series (pure core; no I/O).

Structural checks that need no filesystem: that the governance resolves to a model, and
that the PR graph can be ordered (acyclic, no unknown or duplicate ids). Each failure is a
:class:`Problem` — located, human-readable, collected rather than raised — so ``convoy
validate`` and the ``convoy run`` pre-flight can report every issue at once and abort
before mutating anything. The filesystem checks (prompt files, paths, independent-check
asset isolation) live in the shell counterpart ``interface/preflight_probe.py`` and append
more Problems of the same shape.
"""

from dataclasses import dataclass

from convoy.core.dag import DagError, order
from convoy.core.governance import GovernanceError, effective_governance, resolve_model
from convoy.core.spec import Series


@dataclass(frozen=True)
class Problem:
    """One reason a series is not runnable, located for a human to fix.

    ``kind`` is a coarse category (``governance`` | ``dag`` | ``prompt`` | ``paths`` |
    ``isolation``); ``where`` names the offending section; ``message`` explains it.
    """

    kind: str
    where: str
    message: str


def check_governance(series: Series) -> list[Problem]:
    """A Problem per governance that resolves to no model (unknown tier, or neither set).

    ``[governance]`` is checked first: it must resolve even when every PR overrides it,
    since it is the fallback and the audit baseline. Then each PR that sets its OWN
    ``model`` or ``tier`` is resolved — only those, so a broken series value yields one
    problem rather than 1+N. Without the per-PR pass an unknown per-PR tier would survive
    ``convoy validate`` and the run pre-flight, then raise mid-run in the driver, after
    earlier PRs already spent real money.
    """
    problems: list[Problem] = []
    try:
        resolve_model(series.governance)
    except GovernanceError as exc:
        problems.append(Problem(kind='governance', where='[governance]', message=str(exc)))
    for pr in series.prs:
        if pr.model is None and pr.tier is None:
            continue
        try:
            resolve_model(effective_governance(series.governance, pr))
        except GovernanceError as exc:
            problems.append(
                Problem(kind='governance', where=f'[[prs]] {pr.id!r}', message=str(exc))
            )
    return problems


def check_dag(series: Series) -> list[Problem]:
    """A Problem when the PR graph cannot be ordered (a cycle, unknown, or duplicate id)."""
    try:
        order(series.prs)
    except DagError as exc:
        return [Problem(kind='dag', where='[[prs]]', message=str(exc))]
    return []


def structural_problems(series: Series) -> list[Problem]:
    """All pure structural Problems (governance then DAG), in a stable order."""
    return [*check_governance(series), *check_dag(series)]
