"""The gate-only service: run a spec's checks against a workspace, once, no run loop.

This is the fold both gate-only surfaces consume — the CLI's ``convoy gate`` and the MCP
``convoy_gate`` tool — so the two can never disagree about a verdict, an envelope, or an
exit code. It reuses the run's own machinery end to end: selection is
:func:`convoy.core.gate.checks_for_phases`, execution is
:class:`~convoy.interface.gate_runner.SubprocessGateRunner` (including the fail-closed
isolation guard on independent checks), and the verdict is
:func:`convoy.core.gate.decide`. Nothing here spawns an agent, moves a branch, writes
telemetry, or takes the workspace lock: gating a workspace another process is driving
gates whatever that driver has checked out.

One rule is this module's own: an invocation whose phase tags select **zero** checks is
refused (:class:`EmptySelectionError`) rather than answered green. The per-PR run
deliberately allows an ungated PR — the series author left it ungated and pre-flight
advises about it — but a gate-only caller asked a question, and "green, from nothing" is
a vacuous assurance no orchestrator should be handed.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from convoy.core.gate import GateVerdict, checks_for_phases, decide
from convoy.core.spec import Check, GateSpec
from convoy.interface.drivers.headless import EXIT_BLOCKED, EXIT_OK
from convoy.interface.gate_runner import GateRunner, SubprocessGateRunner


class EmptySelectionError(ValueError):
    """The given phase tags select no checks — a vacuous green, refused fail-closed."""


@dataclass(frozen=True)
class GateOutcome:
    verdict: GateVerdict
    selected: tuple[Check, ...]
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
    The exit code is the run's own vocabulary: ``EXIT_OK`` unless a blocking check failed,
    ``EXIT_BLOCKED`` when one did — a non-blocking red advises, exactly as in a series.
    Raises :class:`EmptySelectionError` before running anything when the selection is
    empty.
    """
    selected = checks_for_phases(spec.checks, phases)
    if not selected:
        named = ', '.join(phases)
        raise EmptySelectionError(
            f'phase selection ({named}) selects no checks out of {len(spec.checks)} — '
            f'a green verdict from zero checks would be vacuous, so it is refused; '
            f'run without --phase for the whole gate, or fix the tag'
        )
    gate_runner = runner if runner is not None else SubprocessGateRunner(spec.timeout_seconds)
    verdict = decide(gate_runner.run(workspace, selected))
    exit_code = EXIT_BLOCKED if verdict.blocking_red else EXIT_OK
    return GateOutcome(verdict=verdict, selected=selected, exit_code=exit_code)


def gate_envelope(
    spec: GateSpec,
    workspace: Path,
    phases: tuple[str, ...],
    outcome: GateOutcome,
) -> dict[str, Any]:
    """The one result envelope both surfaces emit for a gate-only invocation.

    ``outcome`` keeps the run's vocabulary — ``completed`` for a green gate, ``blocked``
    for a blocking red — so a consumer already reading run envelopes learns no new words.
    Every selected check appears with its verdict and its (possibly empty) failure
    ``detail``; the counts are derivable from ``checks`` and carried anyway so a consumer
    that only wants totals never re-folds the list.
    """
    results = outcome.verdict.results
    passed = sum(1 for result in results if result.passed)
    return {
        'ok': outcome.exit_code == EXIT_OK,
        'outcome': 'blocked' if outcome.verdict.blocking_red else 'completed',
        'series_id': spec.id,
        'workspace': str(workspace),
        'phases': list(phases),
        'checks': [
            {
                'name': result.check.name,
                'passed': result.passed,
                'blocking': result.check.blocking,
                'independent': result.check.independent,
                'phases': list(result.check.phases),
                'detail': result.detail,
            }
            for result in results
        ],
        'blocking_red': outcome.verdict.blocking_red,
        'independent_red': outcome.verdict.independent_red,
        'counts': {'selected': len(results), 'passed': passed, 'failed': len(results) - passed},
        'exit_code': outcome.exit_code,
    }
