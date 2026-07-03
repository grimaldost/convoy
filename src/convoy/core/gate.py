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

from convoy.core.spec import Check


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
