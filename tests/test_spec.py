"""Tests for the series spec: parsing, the validation rules, and round-trip."""

import tomllib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from convoy.core.spec import (
    DEFAULT_GATE_TIMEOUT_SECONDS,
    EFFORT_LEVELS,
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
    load_gate_spec,
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


def test_an_unknown_key_under_governance_is_rejected() -> None:
    """A key the engine does not read must fail loudly, not be dropped.

    ``tier_models`` is the worked example of why. Authored against a convoy that
    reads it, a series carrying one would have loaded on an older build, had the key
    silently ignored, and resolved every PR through the built-in floor instead -- a
    run that looks correct and whose telemetry agrees with it. That key is read now,
    so the guard is exercised here with a shape convoy does not have yet, which is
    exactly the point: the failure is always the key nobody thought to forbid.
    ADR-0005 refuses an unknown per-PR governance key for the same reason.
    """
    text = VALID_TOML.replace(
        'effort = "medium"',
        'effort = "medium"\nretry_policy = "aggressive"',
    )
    with pytest.raises(SpecError) as exc:
        load_series(text)
    assert 'retry_policy' in str(exc.value)
    assert '[governance]' in str(exc.value)


def test_a_typo_under_governance_names_the_keys_it_could_have_been() -> None:
    """The rejection has to be actionable: a bare 'unknown key' sends the author
    hunting through a schema doc for a name they already almost typed."""
    text = VALID_TOML.replace('permission_mode = "default"', 'permision_mode = "default"')
    with pytest.raises(SpecError) as exc:
        load_series(text)
    assert 'permision_mode' in str(exc.value)
    assert 'permission_mode' in str(exc.value)


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


@pytest.mark.parametrize('mode', sorted(PERMISSION_MODES))
def test_every_mode_the_agent_cli_accepts_is_accepted_here(mode: str) -> None:
    """The allow-list rejected three modes the CLI supports; a spec must not refuse valid input."""
    text = VALID_TOML.replace('permission_mode = "default"', f'permission_mode = "{mode}"')
    assert load_series(text).governance.permission_mode == mode


@pytest.mark.parametrize('level', sorted(EFFORT_LEVELS))
def test_every_effort_level_the_agent_cli_accepts_is_accepted_here(level: str) -> None:
    text = VALID_TOML.replace('effort = "medium"', f'effort = "{level}"')
    assert load_series(text).governance.effort == level


def test_an_unknown_effort_is_rejected_at_load() -> None:
    """The CLI only WARNS on an unknown effort and runs at its default.

    So an unvalidated typo produces a run whose series file and whose ledger both claim a
    level the spawn never ran at — silent, and undetectable downstream. Caught here instead,
    the same treatment permission_mode already got.
    """
    text = VALID_TOML.replace('effort = "medium"', 'effort = "lo"')
    with pytest.raises(SpecError, match='effort'):
        load_series(text)


def test_an_unknown_effort_names_the_levels_that_would_work() -> None:
    text = VALID_TOML.replace('effort = "medium"', 'effort = "lo"')
    with pytest.raises(SpecError, match='xhigh'):
        load_series(text)


def test_an_unknown_per_pr_effort_is_rejected_too() -> None:
    """A per-PR typo is the same silent failure, one table further down."""
    text = VALID_TOML.replace('id = "pr-1-lexer"', 'id = "pr-1-lexer"\neffort = "hgih"')
    with pytest.raises(SpecError, match='effort'):
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


def test_check_phases_parse_as_a_tuple() -> None:
    text = VALID_TOML.replace('name = "suite"', 'name = "suite"\nphases = ["core", "extras"]')
    series = load_series(text)
    assert series.checks[0].phases == ('core', 'extras')


def test_check_phases_default_to_empty_meaning_every_pr() -> None:
    # Empty is the series-global default: a series that never sets phases is unchanged.
    series = load_series(VALID_TOML)
    assert all(check.phases == () for check in series.checks)


def test_check_phases_must_be_an_array_of_strings() -> None:
    text = VALID_TOML.replace('name = "suite"', 'name = "suite"\nphases = "core"')
    with pytest.raises(SpecError, match='phases'):
        load_series(text)


def test_blank_phase_entry_is_rejected() -> None:
    # A blank tag matches no PR, so it would silently narrow the check to gating nothing.
    text = VALID_TOML.replace('name = "suite"', 'name = "suite"\nphases = ["core", "  "]')
    with pytest.raises(SpecError, match='non-empty'):
        load_series(text)


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
_CHECK_TEXT = _TEXT.filter(lambda text: '${' not in text)
_TOOL_LIST = st.lists(_TEXT, max_size=4).map(tuple)
# Budgets must be strictly positive (load_series rejects <= 0), so keep the strategy above 0.
_MONEY = st.floats(min_value=0.001, max_value=1000, allow_nan=False, allow_infinity=False)


@st.composite
def _series(draw: st.DrawFn) -> Series:
    governance = Governance(
        effort=draw(st.sampled_from(sorted(EFFORT_LEVELS))),
        permission_mode=draw(st.sampled_from(sorted(PERMISSION_MODES))),
        timeout_seconds=draw(st.integers(min_value=1, max_value=86_400)),
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
            # ``run``/``asset`` expand ``${NAME}`` at load (a load-time transform, not a
            # round-trip property), so the property draws literal text for them.
            run=draw(_CHECK_TEXT),
            blocking=draw(st.booleans()),
            independent=draw(st.booleans()),
            # asset, repair_hint and phases are optional; the empty value exercises the
            # omit-on-dump path, a non-empty one the round-trip-through-TOML path. Spec
            # data only here — no filesystem is touched by load/dump.
            asset=draw(st.just('') | _CHECK_TEXT),
            repair_hint=draw(st.just('') | _TEXT),
            phases=draw(st.just(()) | st.lists(_TEXT, max_size=3).map(tuple)),
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
                effort=draw(st.none() | st.sampled_from(sorted(EFFORT_LEVELS))),
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


# --- the spec pin: which spec this series was decomposed from -------------------------------

_PIN_HASH = 'a' * 64


def _with_pin(path: str = 'docs/specs/comparison-ops.md', digest: str = _PIN_HASH) -> str:
    return VALID_TOML.replace(
        'version = "1"',
        f'version = "1"\nspec_path = "{path}"\nspec_sha256 = "{digest}"',
        1,
    )


def test_a_series_carries_the_spec_it_was_decomposed_from() -> None:
    series = load_series(_with_pin())
    assert series.spec_path == 'docs/specs/comparison-ops.md'
    assert series.spec_sha256 == _PIN_HASH


def test_a_series_without_a_pin_parses_exactly_as_before() -> None:
    series = load_series(VALID_TOML)
    assert series.spec_path == ''
    assert series.spec_sha256 == ''


@pytest.mark.parametrize('key', ['spec_path', 'spec_sha256'])
def test_half_a_pin_is_rejected(key: str) -> None:
    """A path with no hash pins nothing; a hash with no path cannot be resolved."""
    value = 'docs/spec.md' if key == 'spec_path' else _PIN_HASH
    text = VALID_TOML.replace('version = "1"', f'version = "1"\n{key} = "{value}"', 1)
    with pytest.raises(SpecError, match='together'):
        load_series(text)


@pytest.mark.parametrize('path', ['/abs/docs/spec.md', 'C:/abs/docs/spec.md'])
def test_an_absolute_spec_path_is_rejected(path: str) -> None:
    """A series directory travels by copy, so an absolute path is wrong on arrival.

    A drive-letter path is rejected on every platform, not only on Windows: the series file
    is what travels, so the machine that reads it is not the one that wrote it.
    """
    with pytest.raises(SpecError, match='repo-relative'):
        load_series(_with_pin(path=path))


@pytest.mark.parametrize('digest', ['abc', 'a' * 63, 'z' * 64, ''])
def test_a_hash_that_is_not_a_sha256_digest_is_rejected(digest: str) -> None:
    """A truncated hash would fail the pre-flight for a reason that looks like spec drift."""
    with pytest.raises(SpecError):
        load_series(_with_pin(digest=digest))


def test_an_uppercase_digest_is_normalised() -> None:
    """A hex digest is the same value in either case; the comparison must not care."""
    assert load_series(_with_pin(digest='A' * 64)).spec_sha256 == 'a' * 64


def test_a_pinned_series_round_trips() -> None:
    original = load_series(_with_pin())
    assert load_series(dump_series(original)) == original


def test_an_unpinned_series_dumps_no_pin_keys() -> None:
    dumped = tomllib.loads(dump_series(load_series(VALID_TOML)))
    assert 'spec_path' not in dumped['series']
    assert 'spec_sha256' not in dumped['series']


# --- load_gate_spec: the checks-only subset loader ---------------------------------------


GATE_ONLY_TOML = """
[series]
id = "gate-only"

[[checks]]
name = "suite"
run = "pytest -q"
blocking = true
independent = false

[[checks]]
name = "later-only"
run = "pytest tests/later -q"
blocking = true
independent = false
phases = ["later"]
"""


def test_a_checks_only_file_loads() -> None:
    spec = load_gate_spec(GATE_ONLY_TOML)
    assert spec.id == 'gate-only'
    assert [check.name for check in spec.checks] == ['suite', 'later-only']
    assert spec.checks[1].phases == ('later',)
    assert spec.timeout_seconds == DEFAULT_GATE_TIMEOUT_SECONDS


def test_a_full_series_file_loads_as_a_gate_spec() -> None:
    """The same file drives `run` and `gate`; the subset loader ignores what it doesn't need."""
    series = load_series(VALID_TOML)
    spec = load_gate_spec(VALID_TOML)
    assert spec.id == series.id
    assert spec.checks == series.checks
    assert spec.timeout_seconds == series.governance.timeout_seconds


def test_gate_spec_requires_an_id() -> None:
    with pytest.raises(SpecError, match=r'\[series\]'):
        load_gate_spec('[[checks]]\nname = "a"\nrun = "x"\nblocking = true\n')


def test_gate_spec_requires_at_least_one_check() -> None:
    with pytest.raises(SpecError, match='checks'):
        load_gate_spec('[series]\nid = "empty"\n')


def test_gate_spec_rejects_a_malformed_check_with_its_location() -> None:
    text = '[series]\nid = "bad"\n\n[[checks]]\nname = "a"\nblocking = true\n'  # no run
    with pytest.raises(SpecError, match=r'\[\[checks\]\]\[0\]'):
        load_gate_spec(text)


def test_gate_spec_rejects_bad_toml() -> None:
    with pytest.raises(SpecError, match='invalid TOML'):
        load_gate_spec('not = [toml')


def test_gate_spec_reads_a_governance_timeout_when_present() -> None:
    text = GATE_ONLY_TOML + '\n[governance]\ntimeout_seconds = 7\n'
    assert load_gate_spec(text).timeout_seconds == 7


def test_gate_spec_rejects_an_empty_checks_array() -> None:
    """`checks = []` is present-but-empty — the docstring's claim, made true."""
    with pytest.raises(SpecError, match='at least one check'):
        load_gate_spec('checks = []\n\n[series]\nid = "empty"\n')


def test_gate_spec_requires_id_even_when_series_table_is_present() -> None:
    with pytest.raises(SpecError, match="missing required field 'id'"):
        load_gate_spec('[series]\n\n[[checks]]\nname = "a"\nrun = "x"\nblocking = true\n')


def test_gate_spec_rejects_duplicate_check_names() -> None:
    text = (
        '[series]\nid = "dup"\n\n'
        '[[checks]]\nname = "t"\nrun = "x"\nblocking = true\n\n'
        '[[checks]]\nname = "t"\nrun = "y"\nblocking = true\n'
    )
    with pytest.raises(SpecError, match='duplicate check name'):
        load_gate_spec(text)


def test_gate_spec_rejects_a_malformed_governance_section() -> None:
    """Ignoring orchestration fields is deliberate; accepting a malformed section is not."""
    with pytest.raises(SpecError, match=r'\[governance\] must be a table'):
        load_gate_spec('governance = "nope"\n' + GATE_ONLY_TOML)


def test_gate_spec_rejects_a_non_positive_timeout() -> None:
    for value in (0, -5):
        with pytest.raises(SpecError, match='must be positive'):
            load_gate_spec(GATE_ONLY_TOML + f'\n[governance]\ntimeout_seconds = {value}\n')


def test_load_series_rejects_a_non_positive_timeout() -> None:
    """The full loader shares the guard: a 0s timeout reads as a full red gate."""
    with pytest.raises(SpecError, match='must be positive'):
        load_series(VALID_TOML.replace('timeout_seconds = 1800', 'timeout_seconds = 0'))


# --- ``${NAME}`` expansion in ``[[checks]]`` ``run`` and ``asset`` (both loaders) ---


def _gate_only(run: str, asset: str = '', repair_hint: str = '') -> str:
    extra = ''
    if asset:
        extra += f'asset = "{asset}"\n'
    if repair_hint:
        extra += f'repair_hint = "{repair_hint}"\n'
    return (
        '[series]\nid = "x"\n\n[[checks]]\nname = "probe"\n'
        f'run = "{run}"\nblocking = true\nindependent = false\n{extra}'
    )


def test_checks_expand_braced_env_references_in_run_and_asset() -> None:
    env = {'CONVOY_ORACLES': '/oracles/proj'}
    spec = load_gate_spec(
        _gate_only('python ${CONVOY_ORACLES}/probe.py', asset='${CONVOY_ORACLES}/probe.py'),
        env=env,
    )
    assert spec.checks[0].run == 'python /oracles/proj/probe.py'
    assert spec.checks[0].asset == '/oracles/proj/probe.py'


def test_checks_leave_unbraced_and_percent_forms_alone() -> None:
    spec = load_gate_spec(
        _gate_only('echo $CONVOY_X %CONVOY_X% ${CONVOY_X}'), env={'CONVOY_X': 'expanded'}
    )
    assert spec.checks[0].run == 'echo $CONVOY_X %CONVOY_X% expanded'


def test_checks_refuse_a_reference_outside_the_convoy_namespace() -> None:
    with pytest.raises(SpecError) as excinfo:
        load_gate_spec(_gate_only('echo ${HOME}'), env={'HOME': '/h'})
    assert 'only CONVOY_* variables expand' in str(excinfo.value)


def test_checks_refuse_an_expanded_value_carrying_shell_syntax() -> None:
    bad = {'CONVOY_ORACLES': '/tmp/x"; echo PWNED; #'}
    with pytest.raises(SpecError) as excinfo:
        load_gate_spec(_gate_only('python ${CONVOY_ORACLES}/o.py'), env=bad)
    assert 'shell syntax' in str(excinfo.value)
    windows = {'CONVOY_ORACLES': 'C:\\Users\\me\\oracles'}
    spec = load_gate_spec(_gate_only('python ${CONVOY_ORACLES}/o.py'), env=windows)
    assert spec.checks[0].run == 'python C:\\Users\\me\\oracles/o.py'


def test_checks_refuse_an_unset_env_reference_naming_field_and_variable() -> None:
    with pytest.raises(SpecError) as excinfo:
        load_gate_spec(_gate_only('python probe.py', asset='${CONVOY_ORACLES}/probe.py'), env={})
    message = str(excinfo.value)
    assert '[[checks]][0]' in message
    assert "'asset'" in message
    assert '${CONVOY_ORACLES}' in message
    assert 'not set' in message


def test_a_repair_hint_is_prose_and_is_not_expanded() -> None:
    spec = load_gate_spec(
        _gate_only('python probe.py', repair_hint='set ${CONVOY_X} before running'),
        env={'CONVOY_X': 'v'},
    )
    assert spec.checks[0].repair_hint == 'set ${CONVOY_X} before running'


def test_load_series_expands_check_references_the_same_way() -> None:
    text = VALID_TOML.replace(
        'python /abs/assets/oracles/type_probe.py', 'python ${CONVOY_ORACLES}/type_probe.py'
    )
    series = load_series(text, env={'CONVOY_ORACLES': '/oracles/proj'})
    assert any(check.run == 'python /oracles/proj/type_probe.py' for check in series.checks)


def test_loaders_read_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('CONVOY_ORACLES', '/from/process')
    spec = load_gate_spec(_gate_only('python ${CONVOY_ORACLES}/probe.py'))
    assert spec.checks[0].run == 'python /from/process/probe.py'


# --- [governance.tier_models]: the artefact carries the lineup ------------------


def _with_tier_models(table: str = '{ weak = "w-model", strong = "s-model" }') -> str:
    return VALID_TOML.replace('effort = "medium"', f'effort = "medium"\ntier_models = {table}')


def test_a_series_can_carry_its_own_tier_table() -> None:
    """The point of the whole design: the run's artefact carries the resolved lineup,
    so the engine's built-in table stops being what decides a run."""
    series = load_series(_with_tier_models())
    assert series.governance.tier_models == {'weak': 'w-model', 'strong': 's-model'}


def test_a_series_without_the_table_keeps_it_empty_not_absent() -> None:
    """An empty mapping, not None: every reader asks the same question of every
    series, and 'inherited the floor' is a value rather than a missing case."""
    assert load_series(VALID_TOML).governance.tier_models == {}


def test_the_tier_table_round_trips_through_the_dumper() -> None:
    """``dump_series`` builds the governance table key by key, so a field it is not
    taught is silently dropped -- and any read-modify-write of a series file would
    then erase the lineup it carried, with nothing to show for it."""
    series = load_series(_with_tier_models())
    assert load_series(dump_series(series)) == series
    assert 'tier_models' in dump_series(series)


def test_an_empty_tier_table_is_omitted_by_the_dumper() -> None:
    """So a series that carries no table round-trips to the same minimal file it
    came from, exactly as the other optional governance fields do."""
    assert 'tier_models' not in dump_series(load_series(VALID_TOML))


def test_a_tier_table_value_must_be_a_non_empty_string() -> None:
    text = _with_tier_models('{ weak = "" }')
    with pytest.raises(SpecError):
        load_series(text)


def test_a_tier_table_value_must_not_be_a_number() -> None:
    text = _with_tier_models('{ weak = 5 }')
    with pytest.raises(SpecError):
        load_series(text)
