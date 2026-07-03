"""Tests for governance resolution: model resolution, per-role spawn, and parity.

``resolve_model`` picks the phase model (explicit wins over tier); ``resolve_spawn``
layers a role's budget and tools on top of that shared model without ever rewriting the
permission mode. The two parity properties nail the invariants convoy must never break:
the permission mode is passed through verbatim (never silently forced to an auto-approve
mode) and the per-spawn model is always the phase model (never a per-PR upgrade).
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from convoy.core.governance import (
    DEFAULT_TIER_MODELS,
    GovernanceError,
    resolve_model,
    resolve_spawn,
)
from convoy.core.spec import PERMISSION_MODES, Budgets, Governance, Tools

_ROLES = ('implementation', 'review', 'fix')


def _governance(
    *,
    model: str | None = None,
    tier: str | None = None,
    permission_mode: str = 'default',
) -> Governance:
    """A ``Governance`` with distinct per-role budgets and tools so a role mix-up shows.

    Each role's budget and tool set is unique, letting ``resolve_spawn`` assertions prove
    a role reads its OWN section rather than another's.
    """
    return Governance(
        effort='low',
        permission_mode=permission_mode,
        timeout_seconds=60,
        budgets=Budgets(implementation=1.0, review=2.0, fix=3.0),
        tools=Tools(
            implementation=('Read', 'Edit'),
            review=('Read', 'Grep'),
            fix=('Read', 'Edit', 'Write'),
        ),
        model=model,
        tier=tier,
    )


# --- resolve_model -----------------------------------------------------------


def test_explicit_model_wins() -> None:
    """An explicit ``governance.model`` is returned verbatim."""
    assert resolve_model(_governance(model='claude-opus-4-8')) == 'claude-opus-4-8'


def test_explicit_model_wins_over_tier() -> None:
    """When both are set the explicit model wins; the tier is not consulted."""
    governance = _governance(model='pinned-model', tier='mid')
    assert resolve_model(governance) == 'pinned-model'


def test_tier_maps_to_its_default_model() -> None:
    """With no model, the tier maps through the default tier→model table."""
    assert resolve_model(_governance(tier='mid')) == DEFAULT_TIER_MODELS['mid']
    assert resolve_model(_governance(tier='strong')) == 'claude-opus-4-8'


def test_custom_tier_table_is_honored() -> None:
    """A caller-supplied tier table overrides the default mapping."""
    got = resolve_model(_governance(tier='mid'), tier_models={'mid': 'custom-mid'})
    assert got == 'custom-mid'


def test_unknown_tier_raises() -> None:
    """A tier that is not in the table raises ``GovernanceError``."""
    with pytest.raises(GovernanceError):
        resolve_model(_governance(tier='nonexistent'))


def test_neither_model_nor_tier_raises() -> None:
    """With neither a model nor a tier set, resolution raises ``GovernanceError``."""
    with pytest.raises(GovernanceError):
        resolve_model(_governance())


# --- resolve_spawn -----------------------------------------------------------


@pytest.mark.parametrize(
    ('role', 'budget', 'tools'),
    [
        ('implementation', 1.0, ('Read', 'Edit')),
        ('review', 2.0, ('Read', 'Grep')),
        ('fix', 3.0, ('Read', 'Edit', 'Write')),
    ],
)
def test_role_selects_its_own_budget_and_tools(
    role: str, budget: float, tools: tuple[str, ...]
) -> None:
    """Each role's budget and tools come from THAT role's section."""
    resolved = resolve_spawn(_governance(model='m'), role)
    assert resolved.budget_usd == budget
    assert resolved.tools == tools


def test_model_is_the_phase_model_across_all_roles() -> None:
    """The resolved model is identical for every role — it is the phase model."""
    governance = _governance(tier='mid')
    phase_model = resolve_model(governance)
    models = {resolve_spawn(governance, role).model for role in _ROLES}
    assert models == {phase_model}


def test_permission_mode_passed_through_unchanged() -> None:
    """``permission_mode`` is carried through verbatim, never rewritten."""
    for mode in sorted(PERMISSION_MODES):
        governance = _governance(model='m', permission_mode=mode)
        for role in _ROLES:
            assert resolve_spawn(governance, role).permission_mode == mode


def test_effort_and_timeout_passed_through() -> None:
    """Effort and timeout are carried through from the governance unchanged."""
    resolved = resolve_spawn(_governance(model='m'), 'implementation')
    assert resolved.effort == 'low'
    assert resolved.timeout_seconds == 60


def test_unknown_role_raises() -> None:
    """An unknown role raises ``GovernanceError``."""
    with pytest.raises(GovernanceError):
        resolve_spawn(_governance(model='m'), 'deployment')


# --- parity properties -------------------------------------------------------
#
# For any Governance with a resolvable model (explicit or a known tier) and any
# valid role: the permission mode is passed through unchanged (convoy never
# rewrites it to bypassPermissions) and the per-spawn model is always the phase
# model (never a silent per-PR upgrade).

_TEXT = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E, blacklist_characters='"\\'),
    min_size=1,
    max_size=12,
)
_TOOL_LIST = st.lists(_TEXT, max_size=4).map(tuple)
_MONEY = st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False)


@st.composite
def _resolvable_governance(draw: st.DrawFn) -> Governance:
    """A ``Governance`` guaranteed to resolve a model: an explicit model or a known tier."""
    # Either pin a model, or leave it None and pick a tier that IS in the default table.
    if draw(st.booleans()):
        model: str | None = draw(_TEXT)
        tier: str | None = draw(st.none() | _TEXT)
    else:
        model = None
        tier = draw(st.sampled_from(sorted(DEFAULT_TIER_MODELS)))
    return Governance(
        effort=draw(_TEXT),
        permission_mode=draw(st.sampled_from(sorted(PERMISSION_MODES))),
        timeout_seconds=draw(st.integers(min_value=0, max_value=86_400)),
        budgets=Budgets(implementation=draw(_MONEY), review=draw(_MONEY), fix=draw(_MONEY)),
        tools=Tools(
            implementation=draw(_TOOL_LIST),
            review=draw(_TOOL_LIST),
            fix=draw(_TOOL_LIST),
        ),
        model=model,
        tier=tier,
    )


@given(_resolvable_governance(), st.sampled_from(_ROLES))
def test_parity_permission_mode_never_rewritten(governance: Governance, role: str) -> None:
    """resolve_spawn passes permission_mode through unchanged for any governance and role."""
    assert resolve_spawn(governance, role).permission_mode == governance.permission_mode


@given(_resolvable_governance(), st.sampled_from(_ROLES))
def test_parity_spawn_model_is_the_phase_model(governance: Governance, role: str) -> None:
    """The per-spawn model always equals the phase model — never a per-PR upgrade."""
    assert resolve_spawn(governance, role).model == resolve_model(governance)
