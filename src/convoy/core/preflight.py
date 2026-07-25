"""Pre-flight validation of a loaded series (pure core; no I/O).

Structural checks that need no filesystem: that the governance resolves to a model, that
the PR graph can be ordered (acyclic, no unknown or duplicate ids), and that every
``[[checks]].phases`` tag resolves to a declared PR phase. Each failure is a
:class:`Problem` — located, human-readable, collected rather than raised — so ``convoy
validate`` and the ``convoy run`` pre-flight can report every issue at once and abort
before mutating anything. The filesystem checks (prompt files, paths, independent-check
asset isolation) live in the shell counterpart ``interface/preflight_probe.py`` and append
more Problems of the same shape.

Alongside the blocking problems, pre-flight also collects :class:`Advisory` items — things
worth saying that do not make the series unrunnable, such as a PR that phase scoping leaves
with no blocking check. :class:`PreflightReport` carries both, and only ``problems`` gates
the run.
"""

from dataclasses import dataclass

from convoy.core.dag import DagError, order
from convoy.core.gate import checks_for
from convoy.core.governance import GovernanceError, effective_governance, resolve_model
from convoy.core.spec import Series


@dataclass(frozen=True)
class Problem:
    """One reason a series is not runnable, located for a human to fix.

    ``kind`` is a coarse category (``governance`` | ``dag`` | ``prompt`` | ``paths`` |
    ``isolation`` | ``phases``); ``where`` names the offending section; ``message``
    explains it.
    """

    kind: str
    where: str
    message: str


@dataclass(frozen=True)
class Advisory:
    """Something worth telling the operator that does **not** stop the run.

    Same located shape as :class:`Problem` and deliberately a distinct type: an advisory
    can never reach the list that decides runnability, so no surface can turn advice into
    a failure (or lose a failure among advice) by accident. ``kind`` is a coarse category
    (``gate`` today); ``where`` names the section it concerns; ``message`` explains it.
    """

    kind: str
    where: str
    message: str


@dataclass(frozen=True)
class PreflightReport:
    """The whole pre-flight verdict: blocking ``problems`` plus non-blocking ``advisories``.

    Only ``problems`` decide whether the series runs — advisories exist so a series can be
    *unusual* (a PR no check gates) without being *invalid*. They are reported on every
    path, the run included: an advisory the run does not carry is one the operator meets
    only if they happened to validate first, which is not the operator with the problem.
    On a run they ride the ``run_start`` telemetry line.
    """

    problems: tuple[Problem, ...] = ()
    advisories: tuple[Advisory, ...] = ()

    @property
    def clean(self) -> bool:
        """No blocking problem. Advisories never make a series unrunnable."""
        return not self.problems


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


def check_phases(series: Series) -> list[Problem]:
    """A Problem per ``[[checks]].phases`` entry that no PR declares.

    A phase tag is free-form, so a typo (``phases = ["cores"]``) resolves to a check that
    gates nothing — it would silently stop running, and a check that never runs is worse
    than a missing one because the series still looks gated. Unknown tags are therefore a
    load-bearing pre-flight failure, not an advisory: the author meant the check to run
    somewhere.
    """
    declared = {pr.phase for pr in series.prs}
    problems: list[Problem] = []
    for check in series.checks:
        unknown = [phase for phase in check.phases if phase not in declared]
        if not unknown:
            continue
        known = ', '.join(sorted(declared)) or '(none)'
        problems.append(
            Problem(
                kind='phases',
                where=f'[[checks]] {check.name!r}',
                message=(
                    f'phases {unknown} match no [[prs]].phase, so this check would gate '
                    f'nothing; declared phases: {known}'
                ),
            )
        )
    return problems


def ungated_prs(series: Series) -> list[Advisory]:
    """An Advisory per PR that no BLOCKING check gates, once phase scoping is applied.

    Phase-scoped checks make it possible for a PR to end up with no blocking check at all,
    which means it integrates unverified. That is a legitimate authoring choice (a
    docs-only PR), so it does not block the run — but it is silent and expensive to
    discover afterwards, so pre-flight names it. Non-blocking checks are ignored here:
    they cannot stop a merge, so they do not make a PR gated.
    """
    advisories: list[Advisory] = []
    for pr in series.prs:
        if any(check.blocking for check in checks_for(series.checks, pr)):
            continue
        advisories.append(
            Advisory(
                kind='gate',
                where=f'[[prs]] {pr.id!r}',
                message=(
                    f'no blocking check gates phase {pr.phase!r}, so this PR integrates unverified'
                ),
            )
        )
    return advisories


def structural_problems(series: Series) -> list[Problem]:
    """All pure structural Problems (governance, DAG, then phase resolution), in a stable order."""
    return [*check_governance(series), *check_dag(series), *check_phases(series)]
