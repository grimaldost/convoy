"""Run external commands under a bounded timeout with whole-tree kill (shell).

convoy runs external commands — quality-gate checks now, agent spawns later. A gate
command that hangs must not leave grandchildren lingering in the scored workspace, so on
timeout we kill the whole process tree, not just the direct child.

Launching matters for that reach: on POSIX the child gets its own session
(``start_new_session=True``) so a single ``killpg`` reaps the group; on Windows it gets a
new process group (``CREATE_NEW_PROCESS_GROUP``) and ``taskkill /T`` walks the tree. The
kill itself is best-effort — a command that has already exited is not an error.
"""

import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def kill_process_tree(pid: int) -> None:
    """Kill process ``pid`` and ALL its descendants.

    Windows uses ``taskkill /F /T /PID <pid>`` (``/T`` walks the child tree); POSIX kills
    the process group with ``SIGKILL`` via ``os.killpg``. Best-effort — never raises if the
    process (or group) is already gone.
    """
    if sys.platform == 'win32':
        subprocess.run(
            ['taskkill', '/F', '/T', '/PID', str(pid)],
            capture_output=True,
            check=False,
        )
        return
    # Already reaped, or the group is gone — best-effort, so a missing process is fine.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(pid), signal.SIGKILL)


@dataclass(frozen=True)
class ProcResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def run_with_timeout(
    command: str,
    cwd: Path,
    timeout_seconds: float,
    env: Mapping[str, str] | None = None,
) -> ProcResult:
    """Run ``command`` as a shell command in ``cwd`` under a bounded timeout.

    stdout and stderr are captured as text. The child is launched so its whole tree can be
    killed — POSIX ``start_new_session=True``, Windows ``CREATE_NEW_PROCESS_GROUP`` — then
    driven with ``communicate(timeout=...)``. On ``TimeoutExpired`` the process tree is
    killed via :func:`kill_process_tree`, whatever partial output drained so far is
    collected, and a result with ``exit_code=-1`` and ``timed_out=True`` is returned.
    Otherwise the real exit code is returned with ``timed_out=False``.
    """
    # Launch the child detached from convoy's own group/session so the whole tree can be
    # killed on timeout. Both knobs are passed on every platform at their no-op defaults
    # (0 / False) so ``Popen``'s overloads still resolve to ``Popen[str]`` — the Windows
    # flag is only referenced under the ``win32`` guard, where the attribute exists.
    creationflags = 0
    new_session = False
    if sys.platform == 'win32':
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        new_session = True

    child = subprocess.Popen(
        command,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(env) if env is not None else None,
        creationflags=creationflags,
        start_new_session=new_session,
    )
    try:
        stdout, stderr = child.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        kill_process_tree(child.pid)
        # Drain whatever the child already wrote; the pipes are closed by the kill.
        stdout, stderr = child.communicate()
        return ProcResult(
            exit_code=-1,
            stdout=stdout or '',
            stderr=stderr or '',
            timed_out=True,
        )
    return ProcResult(
        exit_code=child.returncode,
        stdout=stdout or '',
        stderr=stderr or '',
        timed_out=False,
    )
