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

from dataclasses import dataclass, replace

from convoy.core.spec import PR, Governance

DEFAULT_TIER_MODELS: dict[str, str] = {
    'weak': 'claude-haiku-4-5',
    'mid': 'claude-sonnet-5',
    'strong': 'claude-opus-4-8',
    'frontier': 'claude-fable-5',
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

    ``governance.model`` wins if set; otherwise ``governance.tier`` is mapped through
    ``tier_models`` (defaulting to :data:`DEFAULT_TIER_MODELS`); if neither yields a
    model, raise :class:`GovernanceError`. Resolves whatever governance it is handed —
    the series' own, or a PR's effective governance from :func:`effective_governance`.
    """
    if governance.model is not None:
        return governance.model
    table = tier_models if tier_models is not None else DEFAULT_TIER_MODELS
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
