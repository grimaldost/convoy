"""Governance resolution: series governance into a per-role spawn plan (pure; no I/O).

``resolve_model`` fixes the model for the whole phase — an explicit ``governance.model``
wins, else the ``governance.tier`` maps through a tier→model table. There is no per-PR
model override anywhere in convoy, so the model a spawn runs on is always this phase model.
``resolve_spawn`` then layers the per-role budget and tools (implementation / review / fix)
on top of that shared model, passing ``permission_mode`` through unchanged — convoy never
forces an auto-approve mode. An unresolvable model or an unknown role is a ``GovernanceError``.
"""

from dataclasses import dataclass

from convoy.core.spec import Governance

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
    """A fully-resolved per-role spawn plan: the phase model plus this role's knobs."""

    model: str
    effort: str
    permission_mode: str
    budget_usd: float
    tools: tuple[str, ...]
    timeout_seconds: int


def resolve_model(governance: Governance, tier_models: dict[str, str] | None = None) -> str:
    """Return the phase-level model for ``governance``.

    ``governance.model`` wins if set; otherwise ``governance.tier`` is mapped through
    ``tier_models`` (defaulting to :data:`DEFAULT_TIER_MODELS`); if neither yields a
    model, raise :class:`GovernanceError`. The model is PHASE-LEVEL — there is no per-PR
    override anywhere in convoy, so every role resolves to this same model.
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
    comes from :func:`resolve_model` and is identical across roles (phase-level).
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
