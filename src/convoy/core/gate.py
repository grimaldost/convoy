"""The gate verdict (pure; no I/O).

Turns per-check results into a ``GateVerdict``. Two properties drive the run:
``blocking_red`` decides the merge/exit (a red is a red — full stop), and
``independent_red`` reports whether a *trustworthy* red (a blocking check the
implementer cannot reach) failed, which is what a fix loop may safely repair
against. Independence never suppresses ``blocking_red``: an independent-blocking
red is still a red. All command execution lives in the shell runner
(``convoy.interface.gate_runner``); this module never touches the filesystem.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from convoy.core.spec import PR, Check


class GateUsageError(ValueError):
    """A gate-only invocation that cannot yield a meaningful verdict.

    The gate-only service refuses these before running anything — the caller asked a
    question the given spec + arguments cannot answer, which is a usage defect, not a
    red gate. Defined here (pure, data-only) so the classification that maps them to a
    ``usage`` outcome can live anywhere without importing the service.
    """


class EmptySelectionError(GateUsageError):
    """The selection is empty — a vacuous green, refused fail-closed."""


class UnknownPhaseError(GateUsageError):
    """A requested phase tag appears on no check — the named gate cannot run.

    The run-side twin is pre-flight's ``check_phases`` problem: a tag typo silently
    disabling a check is worse than a missing check, because the result still looks
    gated. Without this, a typo'd tag selects only the unscoped checks and reports
    green while the check the caller named the phase FOR never ran.
    """


class AdvisoryOnlySelectionError(GateUsageError):
    """The selection contains no blocking check — nothing can block, so nothing gates.

    Inside a series an ungated PR is the author's declared choice and pre-flight
    advises about it; a gate-only caller asked a question, and ``ok: true`` from a
    selection that cannot say no is the vacuous assurance this surface refuses.
    """


class IsolationRefusedError(GateUsageError):
    """A blocking independent check's isolation cannot be backed — a spec defect.

    The run reports this identical defect as a pre-flight ``usage`` problem before
    anything executes; the gate-only surface classifies it the same way rather than
    synthesizing a failing check result, so a consumer told ``blocked`` can trust the
    WORK is bad, never the gate spec — and an auto-repair loop keyed on
    ``independent_red`` is never launched against a misconfiguration it cannot fix.
    """


@dataclass(frozen=True)
class CheckResult:
    check: Check
    passed: bool
    detail: str
    # The structured half of ``detail``, for a consumer that branches rather than
    # parses prose: the command's process exit code (``None`` when it never ran to an
    # exit — a timeout, or an isolation-refused synthetic result) and whether the
    # timeout fired. Defaulted so existing constructors and telemetry are unchanged.
    exit_code: int | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class GateVerdict:
    results: tuple[CheckResult, ...]

    @property
    def blocking_red(self) -> bool:
        "Any blocking check failed. A red is a red — this drives the merge/exit decision."
        return any(not r.passed and r.check.blocking for r in self.results)

    @property
    def independent_red(self) -> bool:
        "A blocking *independent* check failed — a trustworthy signal (safe to auto-fix against)."
        return any(not r.passed and r.check.blocking and r.check.independent for r in self.results)


def decide(results: Sequence[CheckResult]) -> GateVerdict:
    """Wrap results into a verdict (pure)."""
    return GateVerdict(results=tuple(results))


def checks_for(checks: Sequence[Check], pr: PR) -> tuple[Check, ...]:
    """The checks that gate ``pr``, in declaration order.

    A check with no ``phases`` gates every PR — the series-global default, so a series
    that sets ``phases`` nowhere selects the whole tuple for every PR and behaves exactly
    as it did before the field existed. A check that names phases gates only the PRs
    whose ``phase`` tag is among them, which is what lets an incremental series run: PR1
    is not gated on a check belonging to a phase PR4 will land.

    Scoping narrows *which checks run*, never what a red means. Whatever is selected here
    is judged by :func:`decide` under the same rules — a blocking red still blocks.
    Selecting nothing is possible and is deliberately not an error: the series author may
    leave a PR ungated (a docs-only PR, say), and pre-flight reports that as a non-blocking
    advisory rather than refusing to run.
    """
    return tuple(check for check in checks if not check.phases or pr.phase in check.phases)


def checks_for_phases(checks: Sequence[Check], phases: Sequence[str]) -> tuple[Check, ...]:
    """The checks a gate-only invocation runs, in declaration order.

    The phase-tag counterpart of :func:`checks_for`, for a caller that stands at no PR
    boundary: no tags selects the whole tuple (the whole gate), and one tag selects
    exactly what :func:`checks_for` selects for a PR carrying it — the unscoped checks
    plus the ones scoped to that tag. Several tags union, so an invocation can stand in
    for a span of phases at once. Selecting nothing is possible here too; the *caller*
    decides what an empty selection means, and the gate-only service refuses it
    (fail-closed) where the per-PR run deliberately does not.
    """
    if not phases:
        return tuple(checks)
    return tuple(
        check
        for check in checks
        if not check.phases or any(phase in check.phases for phase in phases)
    )
