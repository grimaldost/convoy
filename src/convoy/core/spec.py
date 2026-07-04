"""The series spec — convoy's public input format (pure; no I/O).

Parses, validates, and serializes ``series.toml`` (see ``docs/design/02-formats.md``).
``load_series`` takes TOML *text*, never a path: reading a file is a shell concern.
Validation is purely structural — field presence, types, ``depends_on`` resolution,
and the phase-level-only governance parity guard. Anything touching the filesystem
(do ``[paths]`` exist, is an independent check's asset out-of-tree) lives elsewhere.
"""

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import tomli_w

PERMISSION_MODES = frozenset({'default', 'acceptEdits', 'plan', 'bypassPermissions'})

# Per-PR keys that would let authoring-time and runtime disagree about how a PR
# runs; model/effort/budget are phase-level only (02-formats.md).
_FORBIDDEN_PR_KEYS = ('model', 'tier', 'effort', 'budget', 'budgets')


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
    telemetry contract); an empty ``tier`` is unresolvable. Reject both at load so the
    mistake surfaces as a clear ``SpecError`` — caught by ``convoy validate`` and the run
    pre-flight — rather than as a blank field or a runtime error.
    """
    value = _optional_str(data, key, where)
    if value is not None and not value.strip():
        raise SpecError(f'{where}: {key!r} must be non-empty when set')
    return value


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
    permission_mode = _require_str(data, 'permission_mode', where)
    if permission_mode not in PERMISSION_MODES:
        allowed = ', '.join(sorted(PERMISSION_MODES))
        raise SpecError(f'{where}: permission_mode {permission_mode!r} not in {{{allowed}}}')
    return Governance(
        effort=_require_str(data, 'effort', where),
        permission_mode=permission_mode,
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
    return Check(
        name=_require_str(data, 'name', where),
        run=_require_str(data, 'run', where),
        blocking=blocking,
        independent=independent,
        asset='' if asset is None else asset,
    )


def _parse_pr(data: Mapping[str, Any], index: int) -> PR:
    where = f'[[prs]][{index}]'
    # Parity guard (rule 3): model/effort/budget are phase-level only.
    for forbidden in _FORBIDDEN_PR_KEYS:
        if forbidden in data:
            raise SpecError(
                f'{where}: per-PR {forbidden!r} is not allowed; '
                'model/effort/budget are phase-level only'
            )
    return PR(
        id=_require_str(data, 'id', where),
        branch=_require_str(data, 'branch', where),
        prompt=_require_str(data, 'prompt', where),
        phase=_require_str(data, 'phase', where),
        depends_on=_optional_str_tuple(data, 'depends_on', where),
    )


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

    return Series(
        id=_require_str(series_table, 'id', '[series]'),
        version=_require_str(series_table, 'version', '[series]'),
        branches=branches,
        paths=paths,
        governance=governance,
        review=review,
        checks=checks,
        prs=prs,
    )


def _check_table(check: Check) -> dict[str, Any]:
    """One ``[[checks]]`` table for ``dump_series``.

    ``asset`` is omitted when empty (it re-parses as its ``''`` default), so a
    check that never used it round-trips to the same minimal table.
    """
    table: dict[str, Any] = {
        'name': check.name,
        'run': check.run,
        'blocking': check.blocking,
        'independent': check.independent,
    }
    if check.asset:
        table['asset'] = check.asset
    return table


def dump_series(series: Series) -> str:
    """Serialize a ``Series`` back to TOML text.

    Round-trips: ``load_series(dump_series(s)) == s`` for every valid ``s``.
    Optional ``None`` governance fields are omitted (``tomli_w`` cannot encode
    ``None``) and re-parse as their ``None`` default.
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

    document: dict[str, Any] = {
        'series': {'id': series.id, 'version': series.version},
        'branches': {'base': series.branches.base, 'integration': series.branches.integration},
        'paths': {'prompts': series.paths.prompts, 'outputs': series.paths.outputs},
        'governance': governance,
        'review': {
            'blocking': series.review.blocking,
            'max_fix_attempts': series.review.max_fix_attempts,
        },
        'checks': [_check_table(check) for check in series.checks],
        'prs': [
            {
                'id': pr.id,
                'branch': pr.branch,
                'prompt': pr.prompt,
                'phase': pr.phase,
                'depends_on': list(pr.depends_on),
            }
            for pr in series.prs
        ],
    }

    return tomli_w.dumps(document)
