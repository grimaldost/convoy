"""Governance resolution: series governance into a per-role spawn plan (pure; no I/O).

``resolve_model`` fixes the model for a governance — an explicit ``governance.model`` wins,
else the ``governance.tier`` maps through a tier→model table. ``effective_governance``
layers a PR's own ``model``/``tier``/``effort`` over the series' ``[governance]``, which
stays the fallback; a PR that sets none of them resolves exactly as the series does.
``resolve_spawn`` then layers the per-role budget and tools (implementation / review / fix)
on top of that shared model, passing ``permission_mode`` through unchanged — convoy never
forces an auto-approve mode. Every value here is authoring-time and static: it comes from
the spec, is visible before the run, and nothing escalates a model during a run. An
unresolvable model or an unknown role is a ``GovernanceError``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

from convoy.core.spec import PR, Governance, Series

# The date the UPSTREAM tier data was last reconciled against the platform's model
# list -- not the date this file was edited. Stamping the edit would date the wrong
# thing: a table copied from an already-stale source would certify itself fresh, and
# an age check would then be measuring the stamp rather than the lineup.
# lineup synced 2026-09-05
LINEUP_RECONCILED = '2026-09-05'

# A FLOOR, not the answer. A series file that resolves its own tier -- an explicit
# ``model``, or a tier the authoring side already resolved -- never reaches this table.
# It exists so convoy installs and runs for someone who has no access to whatever
# resolved that lineup, which is the charter, and it goes stale between releases by
# design. Correct it locally rather than waiting for one: set ``model`` on the series
# or on the PR.
DEFAULT_TIER_MODELS: dict[str, str] = {
    'weak': 'claude-haiku-4-5',
    'mid': 'claude-sonnet-5',
    'strong': 'claude-opus-5',
    'frontier': 'claude-fable-5-1',
}

_ROLES = ('implementation', 'review', 'fix')


class GovernanceError(ValueError):
    """Governance could not be resolved (e.g. neither model nor a known tier)."""


@dataclass(frozen=True)
class ResolvedSpawn:
    """A fully-resolved per-role spawn plan: the resolved model plus this role's knobs.

    The model is whatever the governance handed to :func:`resolve_spawn` resolves to — a
    PR's own value where it sets one, else the series ``[governance]`` value. It is a
    static, authoring-time choice; nothing changes it during a run.
    """

    model: str
    effort: str
    permission_mode: str
    budget_usd: float
    tools: tuple[str, ...]
    timeout_seconds: int


def effective_governance(governance: Governance, pr: PR) -> Governance:
    """Layer ``pr``'s own governance over the series ``governance``.

    A PR that sets ``model`` OR ``tier`` supplies BOTH: its ``(model, tier)`` pair replaces
    the series pair wholesale, and the series pair is not consulted. Merging the two keys
    independently (``model=pr.model or governance.model``) would be silently wrong —
    :func:`resolve_model` prefers model over tier, so a series ``model`` would shadow a
    per-PR ``tier`` and the PR would run on the wrong model with plausible telemetry.
    ``effort`` has no such interaction and layers independently. A PR that sets none of the
    three returns ``governance`` unchanged.
    """
    if pr.model is not None or pr.tier is not None:
        governance = replace(governance, model=pr.model, tier=pr.tier)
    if pr.effort is not None:
        governance = replace(governance, effort=pr.effort)
    return governance


def resolve_model(governance: Governance, tier_models: dict[str, str] | None = None) -> str:
    """Return the model for ``governance``.

    Order, strongest first: an explicit ``governance.model``; the ``tier_models`` table
    the caller injects (the operator/test seam); the table the SERIES itself carries in
    ``[governance.tier_models]``; and last :data:`DEFAULT_TIER_MODELS`, the built-in
    floor. If none yields a model, raise :class:`GovernanceError`.

    The series' own table sits above the floor because it is part of the artefact: it
    was resolved when the run was authored, it travels with the file, and it makes the
    run reproducible without convoy having to reach anything it does not own. The floor
    is what a stranger gets, and it goes stale between releases by design. Resolves
    whatever governance it is handed — the series' own, or a PR's effective governance
    from :func:`effective_governance`.
    """
    if governance.model is not None:
        return governance.model
    if tier_models is not None:
        table: Mapping[str, str] = tier_models
    elif governance.tier is not None and governance.tier in governance.tier_models:
        table = governance.tier_models
    else:
        table = DEFAULT_TIER_MODELS
    if governance.tier is not None:
        model = table.get(governance.tier)
        if model is not None:
            return model
        known = ', '.join(sorted(table))
        raise GovernanceError(f'unknown tier {governance.tier!r}; known tiers: {known}')
    raise GovernanceError('governance resolves no model: set governance.model or governance.tier')


def resolve_spawn(
    governance: Governance, role: str, tier_models: dict[str, str] | None = None
) -> ResolvedSpawn:
    """Build the per-role spawn governance for ``role``.

    ``role`` in ``{'implementation', 'review', 'fix'}`` selects the budget
    (``governance.budgets.<role>``) and tools (``governance.tools.<role>``). The model
    comes from :func:`resolve_model` and is identical across the roles of the governance
    it is handed — layering a PR's own value is :func:`effective_governance`'s job, done
    by the caller.
    ``permission_mode`` is passed through UNCHANGED — convoy never forces an auto-approve
    mode. Raise :class:`GovernanceError` on an unknown role.
    """
    if role not in _ROLES:
        known = ', '.join(_ROLES)
        raise GovernanceError(f'unknown role {role!r}; known roles: {known}')
    model = resolve_model(governance, tier_models)
    budget_usd: float = getattr(governance.budgets, role)
    tools: tuple[str, ...] = getattr(governance.tools, role)
    return ResolvedSpawn(
        model=model,
        effort=governance.effort,
        permission_mode=governance.permission_mode,
        budget_usd=budget_usd,
        tools=tools,
        timeout_seconds=governance.timeout_seconds,
    )


def model_origin(governance: Governance) -> str:
    """How :func:`resolve_model` would resolve this governance: the WHERE, not the what.

    ``explicit`` (the artefact names the model), ``series-table`` (the artefact carries
    a tier table that covers this tier), or ``floor`` (neither, so the built-in table
    decides). A run resolved from the artefact and a run resolved from whatever this
    build happens to ship are not the same run, and before this they looked identical
    everywhere convoy reports.
    """
    if governance.model is not None:
        return 'explicit'
    if governance.tier is not None and governance.tier in governance.tier_models:
        return 'series-table'
    return 'floor'


def implementation_model_sources(series: Series) -> tuple[tuple[str, str, str], ...]:
    """Every distinct implementation model, paired with the section that declares it.

    Same set and order as :func:`implementation_models` — first-PR-seen, deduped — but
    each model carries a ``where`` string locating it for a :class:`~convoy.core.preflight.Problem`:
    ``'[governance]'`` when the first PR to introduce the model inherited it (set neither
    ``model`` nor ``tier``), or ``"[[prs]] '<id>'"`` when that PR set its own. First source
    wins per model, so a later duplicate never relabels it.

    The third element is the ORIGIN from :func:`model_origin` — whether the value came
    from the artefact or from the built-in floor. ``where`` says which section of the
    file chose it; ``origin`` says whether the file chose it at all. Both are needed:
    a series can name ``[governance]`` as the location and still be running on whatever
    lineup this build happens to ship.

    A series naming no PRs yields the one ``[governance]`` model. Raises
    :class:`GovernanceError` if any resolved governance names no model.
    """
    where_of: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    for pr in series.prs:
        effective = effective_governance(series.governance, pr)
        model = resolve_model(effective)
        if model in where_of:
            continue
        overrides = pr.model is not None or pr.tier is not None
        where = f'[[prs]] {pr.id!r}' if overrides else '[governance]'
        where_of[model] = (where, model_origin(effective))
        order.append(model)
    if not order:
        governance = series.governance
        return ((resolve_model(governance), '[governance]', model_origin(governance)),)
    return tuple((model, *where_of[model]) for model in order)


def implementation_models(series: Series) -> tuple[str, ...]:
    """Every distinct model an implementation spawn of ``series`` can run on.

    In first-PR-seen order, deduped: each PR's implementation model is its effective
    governance's (its own ``model``/``tier`` where set, else the series value). A series
    that names no PRs falls back to ``(resolve_model(series.governance),)`` — today's
    single probe still covers the series model in that case. The model column of
    :func:`implementation_model_sources`. Raises :class:`GovernanceError` if any resolved
    governance names no model.
    """
    return tuple(model for model, _where, _origin in implementation_model_sources(series))
