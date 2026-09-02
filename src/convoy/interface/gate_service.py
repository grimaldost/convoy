"""The gate-only service: run a spec's checks against a workspace, once, no run loop.

This is the fold both gate-only surfaces consume — the CLI's ``convoy gate`` and the MCP
``convoy_gate`` tool — so the two can never disagree about a verdict, an envelope, or an
exit code. It reuses the run's own machinery end to end: selection is
:func:`convoy.core.gate.checks_for_phases`, execution is
:class:`~convoy.interface.gate_runner.SubprocessGateRunner`, and the verdict is
:func:`convoy.core.gate.decide`. Nothing here spawns an agent, moves a branch, writes
telemetry, or takes the workspace lock. Convoy itself writes nothing to the workspace —
but the CHECK COMMANDS run in it and routinely do (``__pycache__``, coverage files,
build output), so gating a tree a ``convoy run`` is actively driving risks more than a
stale read: the run's commit step stages the whole tree, and a concurrent gate's
artifacts can be committed into a scored branch. Don't gate a driven workspace.

Four invocations are refused before anything executes, all mapped to a ``usage``
outcome rather than a verdict (:class:`~convoy.core.gate.GateUsageError` and its
subclasses carry the reasons): an empty selection, a phase tag no check declares, a
selection with no blocking check, and a blocking independent check whose isolation
cannot be backed. The common thread: a gate-only caller asked a question, and each of
these is an invocation that cannot produce a meaningful answer — the run path handles
the same conditions with pre-flight problems and author-declared advisories, which a
standalone invocation does not have.
"""

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w

from convoy import __version__
from convoy.core.gate import (
    AdvisoryOnlySelectionError,
    EmptySelectionError,
    GateVerdict,
    IsolationRefusedError,
    UnknownPhaseError,
    checks_for_phases,
    decide,
    repair_brief,
)
from convoy.core.spec import Check, GateSpec, SpecError, load_gate_spec
from convoy.interface.drivers.headless import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE
from convoy.interface.fs_probe import isolation_result
from convoy.interface.gate_runner import GateRunner, SubprocessGateRunner

# Cap the per-check list projected inline, the same bound and report shape as the run
# envelope's per-PR list (`run_summary._PR_CAP`). Unlike a run there is no on-disk
# trace to point at — the envelope IS the record — so what is dropped is counted,
# never silent.
_CHECK_CAP = 50

# The per-project gate spec: the gate-only file shape, at a fixed place under the project
# root, so ``convoy gate`` and ``convoy hook`` need no argument to find it — and its
# presence is the per-project switch that arms the hook.
GATE_SPEC_RELPATH = Path('.convoy') / 'gate.toml'
# Claude Code exports the project root to hooks and MCP servers under this name.
PROJECT_DIR_ENV = 'CLAUDE_PROJECT_DIR'
# The out-of-tree home for a project's held-out oracles (see ``core.spec.expand_env``).
ORACLES_ENV = 'CONVOY_ORACLES'
# Convoy's per-user directory: the default oracles home and the hook trust list live
# here. ``~/.convoy`` unless overridden (tests, CI, a shared machine).
HOME_ENV = 'CONVOY_HOME'
# The projects whose ``.convoy/gate.toml`` the hook may execute on this machine.
TRUST_FILE = 'hook-trust.toml'


class GateSpecNotFoundError(SpecError):
    """No series file was given and no project gate spec could be found."""


def find_gate_spec(start: Path, env: Mapping[str, str]) -> Path | None:
    """Locate the project gate spec, or ``None``.

    ``$CLAUDE_PROJECT_DIR/.convoy/gate.toml`` first — the root Claude Code hands a hook
    or an MCP server, which may differ from the process cwd — then ``.convoy/gate.toml``
    in *start* and each of its parents, so a gate invoked from a subdirectory finds the
    project's spec the way git finds ``.git``. An env root without a spec falls through
    to the walk rather than ending it.
    """
    candidates: list[Path] = []
    project_dir = env.get(PROJECT_DIR_ENV)
    if project_dir:
        candidates.append(Path(project_dir) / GATE_SPEC_RELPATH)
    resolved = Path(start).resolve()
    candidates.extend(directory / GATE_SPEC_RELPATH for directory in (resolved, *resolved.parents))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def resolve_gate_spec(series_file: Path | None, start: Path, env: Mapping[str, str]) -> Path:
    """An explicit *series_file* as given; otherwise the discovered project spec.

    Raises :class:`GateSpecNotFoundError` (a ``SpecError``, so both surfaces classify it
    as ``spec``) naming everywhere it looked, when there is nothing to run.
    """
    if series_file is not None:
        return series_file
    found = find_gate_spec(start, env)
    if found is None:
        project_dir = env.get(PROJECT_DIR_ENV) or 'unset'
        raise GateSpecNotFoundError(
            f'no series file given and no {GATE_SPEC_RELPATH.as_posix()} found — searched '
            f'${PROJECT_DIR_ENV} ({project_dir}), then {Path(start).resolve()} and its '
            f'parents; pass a series file, or create the project spec'
        )
    return found


def project_root_of(spec_path: Path) -> Path | None:
    """The project a ``.convoy/gate.toml`` belongs to; ``None`` for any other file."""
    if spec_path.parent.name == GATE_SPEC_RELPATH.parent.name:
        return spec_path.parent.parent
    return None


def convoy_home(env: Mapping[str, str]) -> Path:
    """Convoy's per-user directory: ``$CONVOY_HOME``, else ``~/.convoy``."""
    explicit = env.get(HOME_ENV)
    return Path(explicit) if explicit else Path.home() / '.convoy'


def oracles_dir_for(root: Path, env: Mapping[str, str]) -> Path:
    """Where a project's held-out oracles live: ``CONVOY_ORACLES`` when set, else the default.

    The default is ``<convoy home>/oracles/<project dir name>`` — outside every checkout the
    implementer can reach, keyed by the project directory's name so two clones of one
    project share their oracles.
    """
    explicit = env.get(ORACLES_ENV)
    if explicit:
        return Path(explicit)
    return convoy_home(env) / 'oracles' / Path(root).resolve().name


def trusted_projects(env: Mapping[str, str]) -> tuple[Path, ...]:
    """The project roots the hook may execute checks in, from the trust list; ``()`` when absent.

    A malformed trust list is a ``SpecError`` — the hook treats it as trusting nothing,
    and ``convoy gate --trust`` refuses to append to a file it cannot read.
    """
    path = convoy_home(env) / TRUST_FILE
    if not path.is_file():
        return ()
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f'{path}: invalid TOML: {exc}') from exc
    table = data.get('trust')
    projects = table.get('projects') if isinstance(table, dict) else None
    if not isinstance(projects, list) or not all(isinstance(item, str) for item in projects):
        raise SpecError(f'{path}: [trust] projects must be a list of strings')
    return tuple(Path(item) for item in projects)


def is_trusted(root: Path, env: Mapping[str, str]) -> bool:
    """Whether *root* (resolved) is on this machine's hook trust list."""
    resolved = Path(root).resolve()
    return any(item.resolve() == resolved for item in trusted_projects(env))


def trust_project(root: Path, env: Mapping[str, str]) -> Path:
    """Add *root* to the trust list (idempotent) and return the list's path."""
    path = convoy_home(env) / TRUST_FILE
    current = list(trusted_projects(env))
    resolved = Path(root).resolve()
    if all(item.resolve() != resolved for item in current):
        current.append(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    listed = [item.as_posix() for item in current]
    path.write_text(tomli_w.dumps({'trust': {'projects': listed}}), encoding='utf-8')
    return path


def gate_spec_env(spec_path: Path, env: Mapping[str, str]) -> dict[str, str]:
    """The environment a spec at *spec_path* is loaded with.

    A project spec (one living at ``.convoy/gate.toml``) gets ``CONVOY_ORACLES``
    defaulted through :func:`oracles_dir_for` when the caller has not set it, so the
    scaffolded ``${CONVOY_ORACLES}/...`` references resolve on a machine that never
    exported the variable. An explicit series file gets no default: its author wrote its
    paths, and an unset reference is refused at load, as documented.
    """
    resolved = dict(env)
    root = project_root_of(spec_path)
    if root is not None and ORACLES_ENV not in resolved:
        resolved[ORACLES_ENV] = str(oracles_dir_for(root, env))
    return resolved


def load_gate_spec_file(spec_path: Path, env: Mapping[str, str]) -> GateSpec:
    """Read and parse *spec_path* under :func:`gate_spec_env`; the loader's errors pass through."""
    return load_gate_spec(spec_path.read_text(encoding='utf-8'), env=gate_spec_env(spec_path, env))


def advisory_only_detail(selected: Sequence[Check]) -> str:
    """Why a selection carrying no blocking check is refused.

    Its own function because two surfaces reach the same conclusion from the spec alone:
    :func:`run_gate` raises it, and ``convoy validate`` reports it on a gate-only file
    before any check runs. One spelling keeps the two from drifting into different words
    for the same defect.
    """
    return (
        f'the selection ({len(selected)} check(s)) contains no blocking check — '
        f'nothing in it can fail the gate, so "completed" would assure nothing; '
        f'mark a check blocking, or widen the selection'
    )


@dataclass(frozen=True)
class GateOutcome:
    verdict: GateVerdict
    selected: tuple[Check, ...]
    phases: tuple[str, ...]
    exit_code: int


def run_gate(
    spec: GateSpec,
    workspace: Path,
    phases: tuple[str, ...] = (),
    *,
    runner: GateRunner | None = None,
) -> GateOutcome:
    """Select ``spec``'s checks for ``phases``, run them in ``workspace``, judge once.

    No tags runs the whole gate; tags select what a PR carrying them would be gated on.
    The exit code is the run's own vocabulary: ``EXIT_OK`` unless a blocking check
    failed, ``EXIT_BLOCKED`` when one did — a non-blocking red advises, exactly as in a
    series.

    Refusals, all :class:`~convoy.core.gate.GateUsageError` subclasses raised before any
    check command runs:

    - a tag no check declares (:class:`~convoy.core.gate.UnknownPhaseError`) — the
      run-side pre-flight makes the same typo a blocking problem, because a check that
      never runs is worse than a missing one: the result still looks gated;
    - a selection with no blocking check
      (:class:`~convoy.core.gate.AdvisoryOnlySelectionError`) — nothing selected can
      say no, so ``completed`` would be vacuous;
    - an empty selection (:class:`~convoy.core.gate.EmptySelectionError`) — unreachable
      through the two guards above for any loader-produced spec, kept as the
      fail-closed backstop for a directly constructed one;
    - a blocking independent check whose isolation is not backed
      (:class:`~convoy.core.gate.IsolationRefusedError`) — the run reports this
      identical defect as a pre-flight problem; classifying it as a red would point a
      repair loop keyed on ``independent_red`` at a spec misconfiguration it cannot
      fix.
    """
    declared = {phase for check in spec.checks for phase in check.phases}
    unknown = [phase for phase in phases if phase not in declared]
    if unknown:
        named = ', '.join(repr(phase) for phase in unknown)
        raise UnknownPhaseError(
            f'phase tag(s) {named} appear on no check (declared: '
            f'{", ".join(sorted(declared)) or "none"}) — the gate you named cannot run, '
            f'and a green from the remaining checks would look gated while it never was'
        )
    selected = checks_for_phases(spec.checks, phases)
    if not selected:
        raise EmptySelectionError(
            f'the selection is empty ({len(spec.checks)} check(s) in the spec) — a green '
            f'verdict from zero checks would be vacuous, so it is refused'
        )
    if not any(check.blocking for check in selected):
        raise AdvisoryOnlySelectionError(advisory_only_detail(selected))
    for check in selected:
        refused = isolation_result(workspace, check)
        if refused is not None:
            raise IsolationRefusedError(
                f'check {check.name!r}: {refused.detail} — a gate-spec defect, not a '
                f"red; fix the check's asset, or drop independent"
            )
    gate_runner = runner if runner is not None else SubprocessGateRunner(spec.timeout_seconds)
    verdict = decide(gate_runner.run(workspace, selected))
    exit_code = EXIT_BLOCKED if verdict.blocking_red else EXIT_OK
    return GateOutcome(verdict=verdict, selected=selected, phases=phases, exit_code=exit_code)


def gate_envelope(spec: GateSpec, workspace: Path, outcome: GateOutcome) -> dict[str, Any]:
    """The one result envelope both surfaces emit for a gate-only invocation.

    ``outcome`` keeps the run's vocabulary — ``completed`` for a green gate, ``blocked``
    for a blocking red — so a consumer already reading run envelopes learns no new
    words. Every selected check appears (capped at ``_CHECK_CAP`` with the run
    envelope's ``truncated`` report shape) with its verdict, the structured failure
    facts (``exit_code``, ``timed_out``) and the prose ``detail`` a repair can be
    briefed with. ``workspace`` is resolved so the envelope means the same thing
    outside the invoking shell. ``advisories`` is always present and currently always
    empty — the same read-unconditionally guarantee every other convoy envelope gives,
    reserved so a future non-fatal remark is an addition, not a shape change.

    Two fields serve a caller that orchestrates its own repairs. ``repair_brief`` is the
    ready-to-append failing-checks section — :func:`convoy.core.gate.repair_brief`, the
    same text the run's own fix loop briefs a fix spawn with, and ``''`` on a green gate
    — so an external orchestrator appends it to its implementer's brief instead of
    reassembling one from the per-check fields. ``convoy_version`` names the engine that
    produced the envelope, so a stored verdict stays interpretable when the shape later
    grows.

    ``repair_brief`` is deliberately uncapped, unlike the neighbouring ``checks`` list:
    the list is a record, and a record can report what it dropped, while the brief is an
    instruction to repair every blocking red. A brief missing some of them would send a
    fix at part of the problem while reading as the whole of it. A gate wide enough for
    the size to matter has a spec problem the cap would only hide.
    """
    results = outcome.verdict.results
    passed = sum(1 for result in results if result.passed)
    listed = results[:_CHECK_CAP]
    return {
        'ok': outcome.exit_code == EXIT_OK,
        'outcome': 'blocked' if outcome.verdict.blocking_red else 'completed',
        'series_id': spec.id,
        'workspace': str(Path(workspace).resolve()),
        'phases': list(outcome.phases),
        'checks': [
            {
                'name': result.check.name,
                'passed': result.passed,
                'blocking': result.check.blocking,
                'independent': result.check.independent,
                'phases': list(result.check.phases),
                'exit_code': result.exit_code,
                'timed_out': result.timed_out,
                'detail': result.detail,
            }
            for result in listed
        ],
        'blocking_red': outcome.verdict.blocking_red,
        'independent_red': outcome.verdict.independent_red,
        'repair_brief': repair_brief(outcome.verdict),
        'counts': {
            'total': len(spec.checks),
            'selected': len(results),
            'passed': passed,
            'failed': len(results) - passed,
        },
        'advisories': [],
        'truncated': {
            'any': len(results) > _CHECK_CAP,
            'checks': max(0, len(results) - _CHECK_CAP),
        },
        'exit_code': outcome.exit_code,
        'convoy_version': __version__,
    }


def gate_brief_envelope(outcome: GateOutcome) -> dict[str, Any]:
    """The compact envelope: ``ok``, ``outcome``, ``repair_brief``, ``convoy_version``.

    For a caller that must read the verdict inside a model turn and wants nothing else
    in it — the four fields a repair decision needs, and no per-check list to skim past.
    Agrees with :func:`gate_envelope` field for field; the full envelope remains the
    record.
    """
    return {
        'ok': outcome.exit_code == EXIT_OK,
        'outcome': 'blocked' if outcome.verdict.blocking_red else 'completed',
        'repair_brief': repair_brief(outcome.verdict),
        'convoy_version': __version__,
    }


def gate_usage_envelope(
    error: Exception,
    *,
    error_kind: str,
    series_id: str | None = None,
) -> dict[str, Any]:
    """The could-not-answer envelope, shared by both surfaces (CLI ``--json`` and MCP).

    Mirrors the run surfaces' usage results and carries the two fields a consumer
    branches on unconditionally: ``exit_code`` (the documented ``3``, which would
    otherwise appear in prose only) and ``series_id`` when the spec loaded far enough
    to have one.
    """
    envelope: dict[str, Any] = {
        'ok': False,
        'outcome': 'usage',
        'error_kind': error_kind,
        'error': str(error),
        'exit_code': EXIT_USAGE,
    }
    if series_id is not None:
        envelope['series_id'] = series_id
    return envelope
