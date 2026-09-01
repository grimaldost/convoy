"""The series spec — convoy's public input format (pure; no I/O).

Parses, validates, and serializes ``series.toml`` (see ``docs/design/02-formats.md``).
``load_series`` takes TOML *text*, never a path: reading a file is a shell concern.
Validation is purely structural — field presence, types, ``depends_on`` resolution,
and the per-PR governance rule: ``model``/``tier``/``effort`` are optional on a
``[[prs]]`` table and layer over ``[governance]``, while ``budget``/``budgets`` are
rejected. Anything touching the filesystem (do ``[paths]`` exist, is an independent
check's asset out-of-tree) lives elsewhere.
"""

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, cast

import tomli_w

# The permission modes the agent CLI accepts. ``default`` is legacy — absent from the CLI's
# own advertised choice list but still accepted — and is kept because existing series files
# set it. The other six are the advertised set; convoy's earlier four-value list rejected
# three modes the CLI supports, which is a spec that refuses valid input.
PERMISSION_MODES = frozenset(
    {'default', 'acceptEdits', 'auto', 'bypassPermissions', 'manual', 'dontAsk', 'plan'}
)

# The effort levels the agent CLI accepts. Allow-listed for a sharper reason than
# ``permission_mode``: the CLI REJECTS an unknown permission mode, so a typo there fails
# loudly on its own. An unknown ``--effort`` value only prints a warning and runs at the
# CLI's default — so an unvalidated typo produces a run whose series file and whose ledger
# both claim a level the spawn never used. For a tool whose product is comparable
# measurement that is the worst failure shape available: silent, undetectable downstream,
# and it corrupts exactly the comparison the ledger exists to support.
EFFORT_LEVELS = frozenset({'low', 'medium', 'high', 'xhigh', 'max'})

# Budgets are PER-ROLE (``Budgets(implementation, review, fix)``, read via
# ``getattr(governance.budgets, role)``), so a per-PR scalar ``budget`` has no role to
# bind to — a different axis, not a narrower version of the same thing. The series-wide
# repair bound stays ``[review].max_fix_attempts`` (02-formats.md).
_FORBIDDEN_PR_KEYS = ('budget', 'budgets')


class SpecError(ValueError):
    """A series spec failed validation."""


@dataclass(frozen=True)
class Budgets:
    implementation: float
    review: float
    fix: float


@dataclass(frozen=True)
class Tools:
    implementation: tuple[str, ...]
    review: tuple[str, ...]
    fix: tuple[str, ...]


@dataclass(frozen=True)
class Governance:
    effort: str
    permission_mode: str
    timeout_seconds: int
    budgets: Budgets
    tools: Tools
    model: str | None = None
    tier: str | None = None


@dataclass(frozen=True)
class Review:
    blocking: bool
    max_fix_attempts: int


@dataclass(frozen=True)
class Check:
    name: str
    run: str
    blocking: bool
    independent: bool = False
    # Out-of-tree path to an independent check's oracle asset. Isolation is
    # enforced at gate time (fail-closed), not at spec-load; empty when unused.
    asset: str = ''
    # Repo-declared repair recipe for THIS check — a command or one-line instruction
    # appended verbatim to the fix brief when the check fails. The repo knows its
    # regeneration recipes; without a declared one, whether a fix spawn infers the
    # right command from the failure text is luck. Empty when unused.
    repair_hint: str = ''
    # The ``[[prs]].phase`` tags this check gates. EMPTY MEANS EVERY PR — the
    # series-global default, so a series that never sets it behaves exactly as before
    # this field existed. Naming phases narrows the check to PRs carrying one of them,
    # which is what makes an incremental series runnable: an early PR is not gated on
    # a later phase's tests. Selection is ``core.gate.checks_for``; an entry no PR
    # declares is a pre-flight problem, since a typo would silently disable the check.
    phases: tuple[str, ...] = ()


# What a gate-only invocation waits on a check for when the file names no timeout.
# ``SubprocessGateRunner``'s own default, restated as data so the subset loader and the
# runner cannot drift apart silently (test-pinned against the runner's signature).
DEFAULT_GATE_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class GateSpec:
    """The subset of a series a gate-only invocation needs: identity, checks, timeout.

    Loaded by :func:`load_gate_spec`, which accepts either a full series.toml (the same
    file that drives ``run``) or a minimal checks-only file — the framework's gate is
    usable without the orchestration around it.
    """

    id: str
    checks: tuple[Check, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class Branches:
    base: str
    integration: str


@dataclass(frozen=True)
class Paths:
    prompts: str
    outputs: str


@dataclass(frozen=True)
class PR:
    id: str
    branch: str
    prompt: str
    phase: str
    depends_on: tuple[str, ...] = ()
    # This PR's own governance, layered over [governance] by
    # ``core.governance.effective_governance``; absent means inherit the series value.
    model: str | None = None
    tier: str | None = None
    effort: str | None = None


@dataclass(frozen=True)
class Series:
    id: str
    version: str
    branches: Branches
    paths: Paths
    governance: Governance
    review: Review
    checks: tuple[Check, ...]
    prs: tuple[PR, ...]
    # The spec this series was decomposed from: its repo-relative path in the scored
    # workspace, and the SHA-256 of its contents at decomposition time. Optional and set
    # together — a path without a hash pins nothing, a hash without a path cannot be
    # resolved. Empty for a series that carries no pin, which is every series written
    # before the key existed. Repo-relative by construction: an absolute path is rejected
    # at load, because a series directory travels by copy and a machine-absolute path in
    # it is wrong on arrival.
    spec_path: str = ''
    spec_sha256: str = ''


# --- validation helpers ------------------------------------------------------
#
# Each raises SpecError with a located message. bool is excluded from the int
# check because ``bool`` is an ``int`` subclass in Python and the two are never
# interchangeable in this format.


def _require_table(data: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    if key not in data:
        raise SpecError(f'{where}: missing required section [{key}]')
    value = data[key]
    if not isinstance(value, Mapping):
        raise SpecError(f'{where}: [{key}] must be a table, got {type(value).__name__}')
    return value


def _require_str(data: Mapping[str, Any], key: str, where: str) -> str:
    if key not in data:
        raise SpecError(f'{where}: missing required field {key!r}')
    value = data[key]
    if not isinstance(value, str):
        raise SpecError(f'{where}: {key!r} must be a string, got {type(value).__name__}')
    return value


def _require_int(data: Mapping[str, Any], key: str, where: str) -> int:
    if key not in data:
        raise SpecError(f'{where}: missing required field {key!r}')
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f'{where}: {key!r} must be an integer, got {type(value).__name__}')
    return value


def _require_float(data: Mapping[str, Any], key: str, where: str) -> float:
    if key not in data:
        raise SpecError(f'{where}: missing required field {key!r}')
    value = data[key]
    # Accept int too; TOML numbers like ``budget = 1`` are valid USD ceilings.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f'{where}: {key!r} must be a number, got {type(value).__name__}')
    return float(value)


def _require_positive_float(data: Mapping[str, Any], key: str, where: str) -> float:
    """A required float that must be strictly positive.

    A budget is a spend ceiling; a zero or negative ceiling is meaningless — and a ``0.0``
    budget silently disables the spawn's ``--max-budget-usd`` cap (unlimited spend), a
    footgun. Reject it at load so a mistake surfaces as a clear ``SpecError``.
    """
    value = _require_float(data, key, where)
    if value <= 0:
        raise SpecError(f'{where}: {key!r} must be > 0, got {value:g}')
    return value


def _require_bool(data: Mapping[str, Any], key: str, where: str) -> bool:
    if key not in data:
        raise SpecError(f'{where}: missing required field {key!r}')
    value = data[key]
    if not isinstance(value, bool):
        raise SpecError(f'{where}: {key!r} must be a boolean, got {type(value).__name__}')
    return value


def _optional_bool(data: Mapping[str, Any], key: str, where: str, *, default: bool) -> bool:
    """An optional boolean; ``default`` when absent, type-checked when present."""
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise SpecError(f'{where}: {key!r} must be a boolean, got {type(value).__name__}')
    return value


def _optional_str(data: Mapping[str, Any], key: str, where: str) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str):
        raise SpecError(f'{where}: {key!r} must be a string, got {type(value).__name__}')
    return value


def _optional_nonempty_str(data: Mapping[str, Any], key: str, where: str) -> str | None:
    """An optional string that, when present, must be non-blank.

    An empty ``model`` would resolve to an empty ``effective_model`` (never-blank is a
    telemetry contract); an empty ``tier`` is unresolvable; an empty per-PR ``effort``
    would blank a value ``[governance]`` requires. Reject all of them at load so the
    mistake surfaces as a clear ``SpecError`` — caught by ``convoy validate`` and the run
    pre-flight — rather than as a blank field or a runtime error.
    """
    value = _optional_str(data, key, where)
    if value is not None and not value.strip():
        raise SpecError(f'{where}: {key!r} must be non-empty when set')
    return value


def _in_choices(value: str, key: str, where: str, allowed: frozenset[str]) -> str:
    """``value`` if it is in ``allowed``, else a located :class:`SpecError` naming the set."""
    if value not in allowed:
        choices = ', '.join(sorted(allowed))
        raise SpecError(f'{where}: {key} {value!r} not in {{{choices}}}')
    return value


def _require_choice(data: Mapping[str, Any], key: str, where: str, allowed: frozenset[str]) -> str:
    """A required string field constrained to ``allowed``."""
    return _in_choices(_require_str(data, key, where), key, where, allowed)


def _optional_choice(
    data: Mapping[str, Any], key: str, where: str, allowed: frozenset[str]
) -> str | None:
    """An optional string field constrained to ``allowed`` when present."""
    value = _optional_nonempty_str(data, key, where)
    return None if value is None else _in_choices(value, key, where, allowed)


def _require_str_tuple(data: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    if key not in data:
        raise SpecError(f'{where}: missing required field {key!r}')
    return _as_str_tuple(data[key], key, where)


def _optional_str_tuple(data: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    if key not in data:
        return ()
    return _as_str_tuple(data[key], key, where)


def _as_str_tuple(value: Any, key: str, where: str) -> tuple[str, ...]:
    # str is a Sequence; reject it so a bare string is never read as a char array.
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SpecError(f'{where}: {key!r} must be an array of strings, got {type(value).__name__}')
    items: list[str] = []
    for element in value:
        if not isinstance(element, str):
            raise SpecError(
                f'{where}: {key!r} must contain only strings, got {type(element).__name__}'
            )
        items.append(element)
    return tuple(items)


def _require_table_array(data: Mapping[str, Any], key: str, where: str) -> list[Mapping[str, Any]]:
    if key not in data:
        raise SpecError(f'{where}: missing required section [[{key}]]')
    value = data[key]
    if isinstance(value, Mapping) or not isinstance(value, Sequence):
        raise SpecError(f'{where}: [[{key}]] must be an array of tables')
    tables: list[Mapping[str, Any]] = []
    for index, element in enumerate(value):
        if not isinstance(element, Mapping):
            raise SpecError(f'{where}: [[{key}]][{index}] must be a table')
        # TOML table keys are always strings; the isinstance narrowing loses that
        # (Mapping is invariant in its key), so restate it for the checker.
        tables.append(cast('Mapping[str, Any]', element))
    return tables


# --- section parsers ---------------------------------------------------------


def _parse_budgets(data: Mapping[str, Any]) -> Budgets:
    where = '[governance.budgets]'
    return Budgets(
        implementation=_require_positive_float(data, 'implementation', where),
        review=_require_positive_float(data, 'review', where),
        fix=_require_positive_float(data, 'fix', where),
    )


def _parse_tools(data: Mapping[str, Any]) -> Tools:
    where = '[governance.tools]'
    return Tools(
        implementation=_require_str_tuple(data, 'implementation', where),
        review=_require_str_tuple(data, 'review', where),
        fix=_require_str_tuple(data, 'fix', where),
    )


def _parse_governance(data: Mapping[str, Any]) -> Governance:
    where = '[governance]'
    return Governance(
        effort=_require_choice(data, 'effort', where, EFFORT_LEVELS),
        permission_mode=_require_choice(data, 'permission_mode', where, PERMISSION_MODES),
        timeout_seconds=_require_int(data, 'timeout_seconds', where),
        budgets=_parse_budgets(_require_table(data, 'budgets', where)),
        tools=_parse_tools(_require_table(data, 'tools', where)),
        model=_optional_nonempty_str(data, 'model', where),
        tier=_optional_nonempty_str(data, 'tier', where),
    )


def _parse_review(data: Mapping[str, Any]) -> Review:
    where = '[review]'
    # ``blocking`` is reserved for an optional blocking LLM self-review that the v1 headless
    # driver does not run; it is optional (default False) so authors are not forced to set a
    # field with no v1 effect. The merge-blocking gate is ``[[checks]]``, not this flag.
    return Review(
        blocking=_optional_bool(data, 'blocking', where, default=False),
        max_fix_attempts=_require_int(data, 'max_fix_attempts', where),
    )


def _parse_branches(data: Mapping[str, Any]) -> Branches:
    where = '[branches]'
    return Branches(
        base=_require_str(data, 'base', where),
        integration=_require_str(data, 'integration', where),
    )


def _parse_paths(data: Mapping[str, Any]) -> Paths:
    where = '[paths]'
    return Paths(
        prompts=_require_str(data, 'prompts', where),
        outputs=_require_str(data, 'outputs', where),
    )


def _parse_check(data: Mapping[str, Any], index: int) -> Check:
    where = f'[[checks]][{index}]'
    blocking = _require_bool(data, 'blocking', where)
    independent = _require_bool(data, 'independent', where) if 'independent' in data else False
    # A blocking independent check is allowed: its independence is enforced
    # fail-closed at gate time by asset isolation, not forbidden here.
    asset = _optional_str(data, 'asset', where)
    repair_hint = _optional_str(data, 'repair_hint', where)
    phases = _optional_str_tuple(data, 'phases', where)
    for phase in phases:
        # A blank phase tag matches no PR, so it would silently narrow the check to
        # nothing. Reject at load, like the other never-blank spec values.
        if not phase.strip():
            raise SpecError(f'{where}: {"phases"!r} entries must be non-empty')
    return Check(
        name=_require_str(data, 'name', where),
        run=_require_str(data, 'run', where),
        blocking=blocking,
        independent=independent,
        asset='' if asset is None else asset,
        repair_hint='' if repair_hint is None else repair_hint,
        phases=phases,
    )


def _parse_pr(data: Mapping[str, Any], index: int) -> PR:
    where = f'[[prs]][{index}]'
    for forbidden in _FORBIDDEN_PR_KEYS:
        if forbidden in data:
            raise SpecError(
                f'{where}: per-PR {forbidden!r} is not allowed; '
                'budgets are per-role, set [governance.budgets]'
            )
    return PR(
        id=_require_str(data, 'id', where),
        branch=_require_str(data, 'branch', where),
        prompt=_require_str(data, 'prompt', where),
        phase=_require_str(data, 'phase', where),
        depends_on=_optional_str_tuple(data, 'depends_on', where),
        model=_optional_nonempty_str(data, 'model', where),
        tier=_optional_nonempty_str(data, 'tier', where),
        effort=_optional_choice(data, 'effort', where, EFFORT_LEVELS),
    )


_SHA256_HEX_LENGTH = 64


def _parse_spec_pin(data: Mapping[str, Any]) -> tuple[str, str]:
    """``(spec_path, spec_sha256)`` from ``[series]`` — both set, or both empty.

    Validated here rather than left to the pre-flight so a malformed pin is a located
    ``SpecError`` at load, on every surface, before anything reads the filesystem:

    - **Set together.** A path with no hash pins nothing; a hash with no path cannot be
      resolved. One without the other is an author mid-edit, not a pin.
    - **Relative, never absolute.** A series directory travels by copy — it is untracked by
      the consuming project — so a machine-absolute path is wrong the moment it arrives on
      another machine. Repo-relative is what makes the pin portable.
    - **A real SHA-256 digest.** 64 hex characters. A truncated or half-pasted hash would
      otherwise fail the pre-flight comparison for a reason that looks like spec drift,
      which is the wrong diagnosis to hand someone.
    """
    where = '[series]'
    spec_path = _optional_nonempty_str(data, 'spec_path', where)
    spec_sha256 = _optional_nonempty_str(data, 'spec_sha256', where)
    if (spec_path is None) != (spec_sha256 is None):
        raise SpecError(
            f'{where}: spec_path and spec_sha256 must be set together '
            '(a path with no hash pins nothing; a hash with no path cannot be resolved)'
        )
    if spec_path is None or spec_sha256 is None:
        return '', ''
    if PurePosixPath(spec_path).is_absolute() or PureWindowsPath(spec_path).is_absolute():
        raise SpecError(
            f'{where}: spec_path {spec_path!r} must be repo-relative, not absolute — '
            'a series directory travels by copy, so an absolute path is wrong on arrival'
        )
    digest = spec_sha256.lower()
    if len(digest) != _SHA256_HEX_LENGTH or any(c not in '0123456789abcdef' for c in digest):
        raise SpecError(
            f'{where}: spec_sha256 must be a {_SHA256_HEX_LENGTH}-character SHA-256 hex '
            f'digest, got {spec_sha256!r}'
        )
    return spec_path, digest


# --- public API --------------------------------------------------------------


def load_series(text: str) -> Series:
    """Parse and validate TOML *text* into a ``Series``.

    Raises ``SpecError`` on any invalid input, including malformed TOML.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f'invalid TOML: {exc}') from exc

    series_table = _require_table(data, 'series', 'series.toml')
    branches = _parse_branches(_require_table(data, 'branches', 'series.toml'))
    paths = _parse_paths(_require_table(data, 'paths', 'series.toml'))
    governance = _parse_governance(_require_table(data, 'governance', 'series.toml'))
    review = _parse_review(_require_table(data, 'review', 'series.toml'))

    check_tables = _require_table_array(data, 'checks', 'series.toml')
    checks = tuple(_parse_check(table, i) for i, table in enumerate(check_tables))

    pr_tables = _require_table_array(data, 'prs', 'series.toml')
    prs = tuple(_parse_pr(table, i) for i, table in enumerate(pr_tables))

    # Rule 4: every depends_on id must resolve to a defined PR id.
    defined_ids = {pr.id for pr in prs}
    for pr in prs:
        for dependency in pr.depends_on:
            if dependency not in defined_ids:
                raise SpecError(
                    f'[[prs]] {pr.id!r}: depends_on {dependency!r} is not a defined PR id'
                )

    spec_path, spec_sha256 = _parse_spec_pin(series_table)
    return Series(
        id=_require_str(series_table, 'id', '[series]'),
        version=_require_str(series_table, 'version', '[series]'),
        spec_path=spec_path,
        spec_sha256=spec_sha256,
        branches=branches,
        paths=paths,
        governance=governance,
        review=review,
        checks=checks,
        prs=prs,
    )


def load_gate_spec(text: str) -> GateSpec:
    """Parse TOML *text* into the subset a gate-only invocation needs.

    Accepts a full series.toml unchanged — ``[[checks]]`` and ``[governance]
    timeout_seconds`` are read, everything else is ignored — and equally a minimal file
    carrying only ``[series] id`` and ``[[checks]]``. The check tables go through the
    same parser as :func:`load_series`, so a check means exactly the same thing to
    ``gate`` as to ``run``. Raises ``SpecError`` on any invalid input, including
    malformed TOML, a missing id, and an empty or absent ``[[checks]]``.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f'invalid TOML: {exc}') from exc

    series_table = _require_table(data, 'series', 'series.toml')
    check_tables = _require_table_array(data, 'checks', 'series.toml')
    checks = tuple(_parse_check(table, i) for i, table in enumerate(check_tables))

    timeout = DEFAULT_GATE_TIMEOUT_SECONDS
    governance = data.get('governance')
    if isinstance(governance, Mapping) and 'timeout_seconds' in governance:
        timeout = _require_int(governance, 'timeout_seconds', '[governance]')

    return GateSpec(
        id=_require_str(series_table, 'id', '[series]'),
        checks=checks,
        timeout_seconds=timeout,
    )


def _check_table(check: Check) -> dict[str, Any]:
    """One ``[[checks]]`` table for ``dump_series``.

    ``asset``, ``repair_hint`` and ``phases`` are omitted when empty (each re-parses as
    its own empty default), so a check that never used them round-trips to the same
    minimal table.
    """
    table: dict[str, Any] = {
        'name': check.name,
        'run': check.run,
        'blocking': check.blocking,
        'independent': check.independent,
    }
    if check.asset:
        table['asset'] = check.asset
    if check.repair_hint:
        table['repair_hint'] = check.repair_hint
    if check.phases:
        table['phases'] = list(check.phases)
    return table


def _pr_table(pr: PR) -> dict[str, Any]:
    """One ``[[prs]]`` table for ``dump_series``.

    ``model``, ``tier`` and ``effort`` are omitted when unset (each re-parses as its
    ``None`` default), so a PR that inherits ``[governance]`` round-trips to the same
    minimal table.
    """
    table: dict[str, Any] = {
        'id': pr.id,
        'branch': pr.branch,
        'prompt': pr.prompt,
        'phase': pr.phase,
        'depends_on': list(pr.depends_on),
    }
    if pr.model is not None:
        table['model'] = pr.model
    if pr.tier is not None:
        table['tier'] = pr.tier
    if pr.effort is not None:
        table['effort'] = pr.effort
    return table


def dump_series(series: Series) -> str:
    """Serialize a ``Series`` back to TOML text.

    Round-trips: ``load_series(dump_series(s)) == s`` for every valid ``s``.
    Optional ``None`` fields — on ``[governance]`` and on each ``[[prs]]`` table — are
    omitted (``tomli_w`` cannot encode ``None``) and re-parse as their ``None`` default.
    """
    governance: dict[str, Any] = {
        'effort': series.governance.effort,
        'permission_mode': series.governance.permission_mode,
        'timeout_seconds': series.governance.timeout_seconds,
    }
    if series.governance.model is not None:
        governance['model'] = series.governance.model
    if series.governance.tier is not None:
        governance['tier'] = series.governance.tier
    governance['budgets'] = {
        'implementation': series.governance.budgets.implementation,
        'review': series.governance.budgets.review,
        'fix': series.governance.budgets.fix,
    }
    governance['tools'] = {
        'implementation': list(series.governance.tools.implementation),
        'review': list(series.governance.tools.review),
        'fix': list(series.governance.tools.fix),
    }

    # ``spec_path`` / ``spec_sha256`` are omitted when unset (each re-parses as its empty
    # default), so a series that carries no pin round-trips to the same minimal table.
    series_table: dict[str, Any] = {'id': series.id, 'version': series.version}
    if series.spec_path:
        series_table['spec_path'] = series.spec_path
        series_table['spec_sha256'] = series.spec_sha256

    document: dict[str, Any] = {
        'series': series_table,
        'branches': {'base': series.branches.base, 'integration': series.branches.integration},
        'paths': {'prompts': series.paths.prompts, 'outputs': series.paths.outputs},
        'governance': governance,
        'review': {
            'blocking': series.review.blocking,
            'max_fix_attempts': series.review.max_fix_attempts,
        },
        'checks': [_check_table(check) for check in series.checks],
        'prs': [_pr_table(pr) for pr in series.prs],
    }

    return tomli_w.dumps(document)
