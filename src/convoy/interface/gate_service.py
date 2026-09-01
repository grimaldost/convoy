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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from convoy.core.gate import (
    AdvisoryOnlySelectionError,
    EmptySelectionError,
    GateVerdict,
    IsolationRefusedError,
    UnknownPhaseError,
    checks_for_phases,
    decide,
)
from convoy.core.spec import Check, GateSpec
from convoy.interface.drivers.headless import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE
from convoy.interface.fs_probe import isolation_result
from convoy.interface.gate_runner import GateRunner, SubprocessGateRunner

# Cap the per-check list projected inline, the same bound and report shape as the run
# envelope's per-PR list (`run_summary._PR_CAP`). Unlike a run there is no on-disk
# trace to point at — the envelope IS the record — so what is dropped is counted,
# never silent.
_CHECK_CAP = 50


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
        raise AdvisoryOnlySelectionError(
            f'the selection ({len(selected)} check(s)) contains no blocking check — '
            f'nothing in it can fail the gate, so "completed" would assure nothing; '
            f'mark a check blocking, or widen the selection'
        )
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
