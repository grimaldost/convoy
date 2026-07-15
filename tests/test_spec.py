"""Tests for the series spec: parsing, the validation rules, and round-trip."""

import tomllib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from convoy.core.spec import (
    PERMISSION_MODES,
    PR,
    Branches,
    Budgets,
    Check,
    Governance,
    Paths,
    Review,
    Series,
    SpecError,
    Tools,
    dump_series,
    load_series,
)

# A complete, valid spec. Mirrors the worked example in docs/design/02-formats.md,
# except the independent check is non-blocking (a blocking independent check would need an
# out-of-tree ``asset``, which fail-closed isolation guards at gate time — see fs_probe).
VALID_TOML = """
[series]
id = "add-comparison-ops"
version = "1"

[branches]
base = "convoy/base"
integration = "convoy/integration"

[paths]
prompts = "/abs/assets/prompts"
outputs = "/abs/assets/outputs"

[governance]
model = "claude-sonnet-5"
effort = "medium"
permission_mode = "default"
timeout_seconds = 1800

[governance.budgets]
implementation = 2.50
review = 0.75
fix = 1.00

[governance.tools]
implementation = ["Read", "Edit", "Write", "Bash"]
review = ["Read", "Grep", "Glob"]
fix = ["Read", "Edit", "Write", "Bash"]

[review]
blocking = true
max_fix_attempts = 2

[[checks]]
name = "suite"
run = "python -m pytest -q"
blocking = true
independent = false

[[checks]]
name = "type-contract"
run = "python /abs/assets/oracles/type_probe.py"
blocking = false
independent = true

[[prs]]
id = "pr-1-lexer"
branch = "convoy/pr-1"
prompt = "01-lexer.md"
phase = "core"
depends_on = []

[[prs]]
id = "pr-2-parser"
branch = "convoy/pr-2"
prompt = "02-parser.md"
phase = "core"
depends_on = ["pr-1-lexer"]
"""


def test_valid_full_example_parses_to_expected_series() -> None:
    series = load_series(VALID_TOML)

    assert series == Series(
        id='add-comparison-ops',
        version='1',
        branches=Branches(base='convoy/base', integration='convoy/integration'),
        paths=Paths(prompts='/abs/assets/prompts', outputs='/abs/assets/outputs'),
        governance=Governance(
            effort='medium',
            permission_mode='default',
            timeout_seconds=1800,
            budgets=Budgets(implementation=2.50, review=0.75, fix=1.00),
            tools=Tools(
                implementation=('Read', 'Edit', 'Write', 'Bash'),
                review=('Read', 'Grep', 'Glob'),
                fix=('Read', 'Edit', 'Write', 'Bash'),
            ),
            model='claude-sonnet-5',
            tier=None,
        ),
        review=Review(blocking=True, max_fix_attempts=2),
        checks=(
            Check(name='suite', run='python -m pytest -q', blocking=True, independent=False),
            Check(
                name='type-contract',
                run='python /abs/assets/oracles/type_probe.py',
                blocking=False,
                independent=True,
            ),
        ),
        prs=(
            PR(
                id='pr-1-lexer',
                branch='convoy/pr-1',
                prompt='01-lexer.md',
                phase='core',
                depends_on=(),
            ),
            PR(
                id='pr-2-parser',
                branch='convoy/pr-2',
                prompt='02-parser.md',
                phase='core',
                depends_on=('pr-1-lexer',),
            ),
        ),
    )


# --- the five validation rules ----------------------------------------------


def test_rule1_missing_section_raises() -> None:
    # Drop the required [branches] section.
    text = VALID_TOML.replace('[branches]\nbase = "convoy/base"\n', '')
    with pytest.raises(SpecError):
        load_series(text)


def test_rule1_wrong_type_field_raises() -> None:
    # timeout_seconds must be an integer, not a string.
    text = VALID_TOML.replace('timeout_seconds = 1800', 'timeout_seconds = "soon"')
    with pytest.raises(SpecError):
        load_series(text)


def test_rule1_bool_is_not_int_for_timeout() -> None:
    # bool is an int subclass in Python; the spec must not accept it as timeout.
    text = VALID_TOML.replace('timeout_seconds = 1800', 'timeout_seconds = true')
    with pytest.raises(SpecError):
        load_series(text)


def test_rule2_bad_permission_mode_raises() -> None:
    text = VALID_TOML.replace('permission_mode = "default"', 'permission_mode = "yolo"')
    with pytest.raises(SpecError):
        load_series(text)


def test_per_pr_model_parses_onto_the_pr() -> None:
    # A [[prs]] table may carry its own model; it falls back to [governance] when absent.
    text = VALID_TOML.replace(
        'id = "pr-1-lexer"',
        'id = "pr-1-lexer"\nmodel = "claude-opus-4-8"',
    )
    assert load_series(text).prs[0].model == 'claude-opus-4-8'


def test_per_pr_tier_parses_onto_the_pr() -> None:
    text = VALID_TOML.replace(
        'id = "pr-1-lexer"',
        'id = "pr-1-lexer"\ntier = "weak"',
    )
    assert load_series(text).prs[0].tier == 'weak'


def test_per_pr_effort_parses_onto_the_pr() -> None:
    text = VALID_TOML.replace(
        'id = "pr-1-lexer"',
        'id = "pr-1-lexer"\neffort = "low"',
    )
    assert load_series(text).prs[0].effort == 'low'


def test_absent_per_pr_governance_defaults_to_none() -> None:
    # Absent per-PR governance is today's behaviour: the PR inherits [governance].
    for pr in load_series(VALID_TOML).prs:
        assert pr.model is None
        assert pr.tier is None
        assert pr.effort is None


@pytest.mark.parametrize('key', ['model', 'tier', 'effort'])
def test_empty_per_pr_governance_is_rejected(key: str) -> None:
    # An empty model resolves to a blank effective_model (never-blank is a telemetry
    # contract); an empty tier is unresolvable; an empty effort blanks a value
    # [governance] requires. All three are rejected at load.
    text = VALID_TOML.replace(
        'id = "pr-1-lexer"',
        f'id = "pr-1-lexer"\n{key} = ""',
    )
    with pytest.raises(SpecError, match='non-empty'):
        load_series(text)


@pytest.mark.parametrize('key', ['budget', 'budgets'])
def test_per_pr_budget_keys_are_rejected(key: str) -> None:
    """Budgets are per-role (implementation/review/fix), so a per-PR scalar has no role
    to bind to — a different axis, not a narrower version of the same thing.
    """
    text = VALID_TOML.replace(
        'id = "pr-1-lexer"',
        f'id = "pr-1-lexer"\n{key} = "x"',
    )
    with pytest.raises(SpecError):
        load_series(text)


def test_rule4_unresolved_depends_on_raises() -> None:
    text = VALID_TOML.replace('depends_on = ["pr-1-lexer"]', 'depends_on = ["pr-does-not-exist"]')
    with pytest.raises(SpecError):
        load_series(text)


def test_blocking_independent_check_now_parses_with_asset() -> None:
    # B4: a blocking + independent check is no longer rejected at spec-load; its
    # independence is enforced fail-closed at gate time by asset isolation. It
    # parses, and the optional out-of-tree ``asset`` round-trips onto the Check.
    text = VALID_TOML.replace(
        'run = "python /abs/assets/oracles/type_probe.py"\nblocking = false\nindependent = true',
        'run = "python /abs/assets/oracles/type_probe.py"\n'
        'blocking = true\nindependent = true\nasset = "/abs/assets/oracles/type_probe.py"',
    )
    series = load_series(text)
    independent_check = series.checks[1]
    assert independent_check.blocking is True
    assert independent_check.independent is True
    assert independent_check.asset == '/abs/assets/oracles/type_probe.py'


def test_check_asset_defaults_to_empty_when_omitted() -> None:
    # The worked example declares no asset on either check; the field defaults to ''.
    series = load_series(VALID_TOML)
    assert all(check.asset == '' for check in series.checks)


def test_check_repair_hint_parses_verbatim() -> None:
    # An optional repo-declared repair recipe for THIS check, handed verbatim to the
    # fix spawn when the check fails — without it, whether a fix spawn infers the
    # regeneration command is luck.
    text = VALID_TOML.replace(
        'name = "suite"',
        'name = "suite"\nrepair_hint = "run scripts/generate_references.py and commit the diff"',
    )
    series = load_series(text)
    assert series.checks[0].repair_hint == (
        'run scripts/generate_references.py and commit the diff'
    )


def test_check_repair_hint_defaults_to_empty_when_omitted() -> None:
    series = load_series(VALID_TOML)
    assert all(check.repair_hint == '' for check in series.checks)


def test_review_blocking_defaults_to_false_when_omitted() -> None:
    # `[review].blocking` is reserved for an optional blocking LLM self-review the v1 driver
    # does not run, so it is optional (default False) — authors are not forced to set a no-op.
    text = VALID_TOML.replace('blocking = true\nmax_fix_attempts = 2', 'max_fix_attempts = 2')
    series = load_series(text)
    assert series.review.blocking is False
    assert series.review.max_fix_attempts == 2


def test_review_blocking_is_honored_when_present() -> None:
    assert load_series(VALID_TOML).review.blocking is True


# --- malformed TOML is wrapped ----------------------------------------------


def test_malformed_toml_raises_spec_error() -> None:
    with pytest.raises(SpecError):
        load_series('this is [not valid toml')


# --- round-trip property -----------------------------------------------------
#
# The strategy generates only valid Series: permission_mode from the allowed set,
# and depends_on referencing only earlier PR ids. A check may be blocking +
# independent (B4 allows it) and may carry an out-of-tree ``asset`` or not, so the
# round-trip exercises the optional-asset omit path. A PR draws its optional
# ``model``/``tier``/``effort`` as a value or None: the None branch is what exercises
# the omit-on-dump path (``tomli_w`` cannot encode ``None``). Text is drawn from a
# TOML-safe printable alphabet and floats exclude NaN/inf so the property isolates
# structural round-trip, not tomli_w's encoding edge cases.

_TEXT = st.text(
    alphabet=st.characters(
        min_codepoint=0x21,
        max_codepoint=0x7E,
        blacklist_characters='"\\',
    ),
    min_size=1,
    max_size=12,
)
_TOOL_LIST = st.lists(_TEXT, max_size=4).map(tuple)
# Budgets must be strictly positive (load_series rejects <= 0), so keep the strategy above 0.
_MONEY = st.floats(min_value=0.001, max_value=1000, allow_nan=False, allow_infinity=False)


@st.composite
def _series(draw: st.DrawFn) -> Series:
    governance = Governance(
        effort=draw(_TEXT),
        permission_mode=draw(st.sampled_from(sorted(PERMISSION_MODES))),
        timeout_seconds=draw(st.integers(min_value=0, max_value=86_400)),
        budgets=Budgets(implementation=draw(_MONEY), review=draw(_MONEY), fix=draw(_MONEY)),
        tools=Tools(
            implementation=draw(_TOOL_LIST),
            review=draw(_TOOL_LIST),
            fix=draw(_TOOL_LIST),
        ),
        model=draw(st.none() | _TEXT),
        tier=draw(st.none() | _TEXT),
    )

    checks = tuple(
        Check(
            name=draw(_TEXT),
            run=draw(_TEXT),
            blocking=draw(st.booleans()),
            independent=draw(st.booleans()),
            # asset and repair_hint are optional; '' exercises the omit-on-dump
            # path, a value the round-trip-through-TOML path. Spec data only here —
            # no filesystem is touched by load/dump.
            asset=draw(st.just('') | _TEXT),
            repair_hint=draw(st.just('') | _TEXT),
        )
        for _ in draw(st.lists(st.booleans(), max_size=4))
    )

    # Generate unique PR ids, then let each depend only on earlier ids.
    pr_ids = draw(
        st.lists(_TEXT, min_size=1, max_size=5, unique=True),
    )
    prs: list[PR] = []
    for index, pr_id in enumerate(pr_ids):
        earlier = pr_ids[:index]
        depends_on = (
            draw(st.lists(st.sampled_from(earlier), max_size=len(earlier), unique=True))
            if earlier
            else []
        )
        prs.append(
            PR(
                id=pr_id,
                branch=draw(_TEXT),
                prompt=draw(_TEXT),
                phase=draw(_TEXT),
                depends_on=tuple(depends_on),
                model=draw(st.none() | _TEXT),
                tier=draw(st.none() | _TEXT),
                effort=draw(st.none() | _TEXT),
            )
        )

    return Series(
        id=draw(_TEXT),
        version=draw(_TEXT),
        branches=Branches(base=draw(_TEXT), integration=draw(_TEXT)),
        paths=Paths(prompts=draw(_TEXT), outputs=draw(_TEXT)),
        governance=governance,
        review=Review(blocking=draw(st.booleans()), max_fix_attempts=draw(st.integers(0, 10))),
        checks=checks,
        prs=tuple(prs),
    )


@given(_series())
def test_round_trip(series: Series) -> None:
    assert load_series(dump_series(series)) == series


@given(_series())
def test_dump_is_valid_toml(series: Series) -> None:
    # dump_series output must itself be parseable TOML.
    tomllib.loads(dump_series(series))


# --- budgets must be strictly positive (a zero budget silently disables the spend cap) ----

_BUDGET_LINES = {
    'implementation': 'implementation = 2.50',
    'review': 'review = 0.75',
    'fix': 'fix = 1.00',
}


@pytest.mark.parametrize('role', ['implementation', 'review', 'fix'])
@pytest.mark.parametrize('bad', ['0', '0.0', '-1'])
def test_nonpositive_budget_is_rejected(role: str, bad: str) -> None:
    toml = VALID_TOML.replace(_BUDGET_LINES[role], f'{role} = {bad}')
    with pytest.raises(SpecError, match='must be > 0'):
        load_series(toml)


def test_small_positive_budget_parses() -> None:
    toml = VALID_TOML.replace('implementation = 2.50', 'implementation = 0.001')
    series = load_series(toml)
    assert series.governance.budgets.implementation == 0.001


# --- an empty model / tier is rejected (it would resolve to a blank effective_model) -------


def test_empty_model_is_rejected() -> None:
    toml = VALID_TOML.replace('model = "claude-sonnet-5"', 'model = ""')
    with pytest.raises(SpecError, match='non-empty'):
        load_series(toml)


def test_empty_tier_is_rejected() -> None:
    toml = VALID_TOML.replace('model = "claude-sonnet-5"', 'model = "claude-sonnet-5"\ntier = ""')
    with pytest.raises(SpecError, match='non-empty'):
        load_series(toml)
