"""Running a series' checks against a workspace (shell).

The pure verdict (``convoy.core.gate``) receives pass/fail as data; this adapter
is where the commands actually run. ``SubprocessGateRunner`` executes each
check's ``run`` command in the workspace under a bounded timeout via
``convoy.interface.proc.run_with_timeout``. A check passes only when it neither
timed out nor exited nonzero; on a red it carries a short, useful ``detail`` — a
timeout note, or the tail of stderr (falling back to stdout) — so a fix loop has
something to re-brief with.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from convoy.core.gate import CheckResult
from convoy.core.spec import Check
from convoy.interface.fs_probe import isolation_result
from convoy.interface.proc import ProcResult, run_with_timeout

# How much of a failing command's captured output to keep in the detail. Enough
# to be useful in a re-brief without dragging a whole test log into telemetry.
_DETAIL_TAIL_CHARS = 2000


class GateRunner(Protocol):
    def run(self, workspace: Path, checks: Sequence[Check]) -> tuple[CheckResult, ...]: ...


class SubprocessGateRunner:
    def __init__(self, timeout_seconds: float = 300.0) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, workspace: Path, checks: Sequence[Check]) -> tuple[CheckResult, ...]:
        """Run each check's ``run`` command in ``workspace``, in order.

        A blocking independent check is first guarded by
        ``isolation_result(workspace, check)``: if that returns a
        ``CheckResult``, isolation failed, so the command is **not** run and that
        failing result is recorded (fail-closed). Otherwise the command runs via
        ``run_with_timeout(check.run, workspace, self._timeout_seconds)``.
        ``passed`` is true only when the command neither timed out nor exited
        nonzero. On a red the ``detail`` is a short, useful note (the timeout, or
        the tail of stderr/stdout); on a pass it is empty. Returns one
        ``CheckResult`` per check, in the given order.
        """
        results: list[CheckResult] = []
        for check in checks:
            isolation = isolation_result(workspace, check)
            if isolation is not None:
                # Fail-closed: never run a check whose independence isn't backed.
                results.append(isolation)
                continue
            result = run_with_timeout(check.run, workspace, self._timeout_seconds)
            passed = not result.timed_out and result.exit_code == 0
            detail = '' if passed else _red_detail(result, self._timeout_seconds)
            results.append(CheckResult(check=check, passed=passed, detail=detail))
        return tuple(results)


def _red_detail(result: ProcResult, timeout_seconds: float) -> str:
    """A short, useful reason a check went red.

    A timeout is reported as such (the command produced no verdict). Otherwise
    the nonzero exit code is reported with the tail of stderr, falling back to
    stdout when stderr is empty.
    """
    if result.timed_out:
        return f'timed out after {timeout_seconds:g}s'
    output = result.stderr.strip() or result.stdout.strip()
    tail = output[-_DETAIL_TAIL_CHARS:] if output else '(no output)'
    return f'exited {result.exit_code}: {tail}'
