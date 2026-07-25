"""Running a series' checks against a workspace (shell).

The pure verdict (``convoy.core.gate``) receives pass/fail as data; this adapter
is where the commands actually run. ``SubprocessGateRunner`` executes each
check's ``run`` command in the workspace under a bounded timeout via
``convoy.interface.proc.run_with_timeout``. A check passes only when it neither
timed out nor exited nonzero; on a red it carries a short, useful ``detail`` — a
timeout note, or the tail of stderr (falling back to stdout) — so a fix loop has
something to re-brief with.

Checks run under a sanitized environment (:func:`gate_env`): the host env minus the
variables that make a Python launcher print an environment-mismatch warning, which would
otherwise take stderr's first line and therefore ``detail``'s.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from convoy.core.gate import CheckResult
from convoy.core.spec import Check
from convoy.interface.fs_probe import isolation_result
from convoy.interface.proc import ProcResult, run_with_timeout

# How much of a failing command's captured output to keep in the detail. Enough
# to be useful in a re-brief without dragging a whole test log into telemetry.
_DETAIL_TAIL_CHARS = 2000

# Host variables that make a Python launcher announce an environment mismatch on stderr
# before the check has done anything. convoy runs checks in the scored workspace, which is
# not the environment convoy itself was launched from, so an inherited ``VIRTUAL_ENV``
# pointing elsewhere is *expected* — and a warning about it is noise convoy provoked, not a
# signal from the check.
#
# It is not harmless noise. ``_red_detail`` prefers stderr, so that warning becomes the
# FIRST thing in ``detail``, displacing the real failure — and ``detail`` is what the fix
# spawn is re-briefed with, so the repair agent is pointed at a non-problem. Stripping the
# variables removes the warning at its source rather than filtering it downstream, where a
# pattern match would rot with every launcher release.
#
# Same posture as ``_ENV_STRIP`` in ``headless_spawn`` (which strips billing/routing
# overrides from a scored spawn); these are the check-environment counterpart.
_ENV_STRIP: frozenset[str] = frozenset({'VIRTUAL_ENV', 'VIRTUAL_ENV_PROMPT', 'UV_PROJECT'})


def gate_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The host environment minus the variables that provoke a launcher mismatch warning.

    Everything else is inherited unchanged: a check legitimately needs ``PATH``, the
    platform variables, and whatever the repo's own tooling reads. Defaults to
    ``os.environ`` and takes a mapping so the behaviour is testable without mutating the
    process environment.
    """
    source = os.environ if environ is None else environ
    return {key: value for key, value in source.items() if key not in _ENV_STRIP}


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
        ``run_with_timeout`` under :func:`gate_env` — the host environment minus
        the variables that would make a launcher print a mismatch warning ahead
        of the check's own output.
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
            result = run_with_timeout(check.run, workspace, self._timeout_seconds, env=gate_env())
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
