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


@dataclass(frozen=True)
class CheckResult:
    check: Check
    passed: bool
    detail: str


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
