"""Tests for governance resolution: model resolution, per-role spawn, layering, and parity.

``resolve_model`` picks a governance's model (explicit wins over tier); ``resolve_spawn``
layers a role's budget and tools on top of that shared model without ever rewriting the
permission mode. ``effective_governance`` layers a PR's own model/tier/effort over the
series' — a static, authoring-time value; nothing escalates a model during a run. The
parity properties nail the invariants convoy must never break: the permission mode is
passed through verbatim (never silently forced to an auto-approve mode), the roles of one
governance never resolve to different models, and a PR with no override behaves exactly as
it does today.
"""

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from convoy.core.governance import (
    DEFAULT_TIER_MODELS,
    GovernanceError,
    effective_governance,
    implementation_models,
    resolve_model,
    resolve_spawn,
)
from convoy.core.spec import (
    PERMISSION_MODES,
    PR,
    Branches,
    Budgets,
    Governance,
    Paths,
    Review,
    Series,
    Tools,
)

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


def test_model_is_shared_across_the_roles_of_one_governance() -> None:
    """The roles of one governance share its model — a PR's roles never diverge."""
    governance = _governance(tier='mid')
    resolved = resolve_model(governance)
    models = {resolve_spawn(governance, role).model for role in _ROLES}
    assert models == {resolved}


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


# --- effective_governance: a PR's own governance, falling back to the series' ----


def _pr(*, model: str | None = None, tier: str | None = None, effort: str | None = None) -> PR:
    return PR(
        id='pr-1',
        branch='pr-1',
        prompt='pr-1.md',
        phase='p',
        model=model,
        tier=tier,
        effort=effort,
    )


def test_per_pr_tier_is_not_shadowed_by_a_series_model() -> None:
    """A PR that sets only ``tier`` replaces the series ``(model, tier)`` PAIR.

    The naive merge (``model=pr.model or governance.model``) gets this wrong: ``resolve_model``
    prefers model over tier, so the series model would shadow the PR's tier and the PR would
    silently run on the wrong model with plausible-looking telemetry.
    """
    governance = _governance(model='series-pinned')
    effective = effective_governance(governance, _pr(tier='weak'))
    assert resolve_model(effective) == DEFAULT_TIER_MODELS['weak']
    assert resolve_model(effective) != 'series-pinned'


def test_per_pr_model_wins_over_a_series_tier() -> None:
    """A PR that sets only ``model`` replaces the pair; the series tier is not consulted."""
    governance = _governance(tier='strong')
    effective = effective_governance(governance, _pr(model='pr-pinned'))
    assert resolve_model(effective) == 'pr-pinned'


def test_per_pr_effort_overrides_the_series_effort() -> None:
    """``effort`` layers independently of the model/tier pair."""
    effective = effective_governance(_governance(model='m'), _pr(effort='xhigh'))
    assert effective.effort == 'xhigh'
    assert resolve_model(effective) == 'm'


def test_absent_per_pr_effort_keeps_the_series_effort() -> None:
    """With no per-PR effort the series effort stands, even when the model is overridden."""
    effective = effective_governance(_governance(model='m'), _pr(model='other'))
    assert effective.effort == 'low'


def test_unknown_per_pr_tier_raises() -> None:
    """A per-PR tier that is not in the table raises ``GovernanceError`` on resolution."""
    effective = effective_governance(_governance(model='m'), _pr(tier='banana'))
    with pytest.raises(GovernanceError):
        resolve_model(effective)


# --- implementation_models: every distinct model an impl spawn can run on -----


def _series_over(governance: Governance, prs: tuple[PR, ...]) -> Series:
    return Series(
        id='s',
        version='1',
        branches=Branches(base='base', integration='integration'),
        paths=Paths(prompts='/tmp/p', outputs='/tmp/o'),
        governance=governance,
        review=Review(blocking=False, max_fix_attempts=0),
        checks=(),
        prs=prs,
    )


def test_implementation_models_dedupes_and_preserves_first_seen_order() -> None:
    """Distinct models only, in first-PR-seen order — a repeat adds nothing."""
    prs = (
        _pr(model='m-a'),
        _pr(model='m-b'),
        _pr(model='m-a'),  # a repeat of the first
    )
    got = implementation_models(_series_over(_governance(model='series'), prs))
    assert got == ('m-a', 'm-b')


def test_implementation_models_mixes_overriding_and_inheriting_prs() -> None:
    """An inheriting PR contributes the series model; an overriding PR its own."""
    prs = (
        _pr(),  # inherits the series model
        _pr(tier='weak'),  # overrides to a tier-resolved model
    )
    got = implementation_models(_series_over(_governance(model='series-model'), prs))
    assert got == ('series-model', DEFAULT_TIER_MODELS['weak'])


def test_implementation_models_falls_back_to_the_series_model_on_empty_prs() -> None:
    """A series naming no PRs still yields the [governance] model as the one to cover."""
    got = implementation_models(_series_over(_governance(tier='mid'), ()))
    assert got == (DEFAULT_TIER_MODELS['mid'],)


# --- parity properties -------------------------------------------------------
#
# For any Governance with a resolvable model (explicit or a known tier) and any
# valid role: the permission mode is passed through unchanged (convoy never
# rewrites it to bypassPermissions), the roles of one governance never resolve to
# different models, a PR with no override behaves exactly as it does today, and a
# PR that overrides wins over the series value.

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


@st.composite
def _pr_override(draw: st.DrawFn) -> PR:
    """A ``PR`` across all six override branches, each of which stays resolvable.

    Drawing the per-PR value is what keeps the properties below from passing vacuously on
    the absent branch forever.
    """
    branch = draw(
        st.sampled_from(('none', 'model', 'tier', 'effort', 'model+effort', 'tier+effort'))
    )
    model = draw(_TEXT) if 'model' in branch else None
    tier = draw(st.sampled_from(sorted(DEFAULT_TIER_MODELS))) if 'tier' in branch else None
    effort = draw(_TEXT) if 'effort' in branch else None
    return PR(
        id='pr-1',
        branch='pr-1',
        prompt='pr-1.md',
        phase='p',
        model=model,
        tier=tier,
        effort=effort,
    )


@given(_resolvable_governance(), st.sampled_from(_ROLES))
def test_parity_permission_mode_never_rewritten(governance: Governance, role: str) -> None:
    """resolve_spawn passes permission_mode through unchanged for any governance and role."""
    assert resolve_spawn(governance, role).permission_mode == governance.permission_mode


@given(_resolvable_governance(), st.sampled_from(_ROLES))
def test_parity_spawn_model_is_the_resolved_model(governance: Governance, role: str) -> None:
    """The per-spawn model always equals its governance's resolved model.

    The roles of one governance never diverge — a PR's implementation and fix spawns run
    on the same model.
    """
    assert resolve_spawn(governance, role).model == resolve_model(governance)


@given(_resolvable_governance(), st.sampled_from(_ROLES))
def test_parity_absent_per_pr_override_is_todays_behaviour(
    governance: Governance, role: str
) -> None:
    """A PR that sets nothing resolves bit-for-bit to what it resolves to today."""
    pr = PR(id='pr-1', branch='pr-1', prompt='pr-1.md', phase='p')
    assert effective_governance(governance, pr) == governance
    assert resolve_spawn(effective_governance(governance, pr), role) == resolve_spawn(
        governance, role
    )


@given(_resolvable_governance(), _pr_override(), st.sampled_from(_ROLES))
def test_parity_per_pr_value_wins_over_the_series_value(
    governance: Governance, pr: PR, role: str
) -> None:
    """A PR that sets model or tier replaces the series pair; the series pair is not consulted."""
    if pr.model is None and pr.tier is None:
        return
    expected = resolve_model(replace(governance, model=pr.model, tier=pr.tier))
    assert resolve_spawn(effective_governance(governance, pr), role).model == expected
