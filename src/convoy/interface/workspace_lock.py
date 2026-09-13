"""An exclusive per-workspace lock so two concurrent runs never interleave git operations.

convoy's posture is fail-loud: a second ``convoy run`` against a workspace already in use
must fail immediately with a clear message, not corrupt the tree by racing the first run's
checkouts and commits. The lock file lives under ``.git`` so it never dirties the tracked
working tree.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from convoy.interface.proc import process_is_alive

_LOCK_NAME = 'convoy-run.lock'


class WorkspaceBusyError(Exception):
    """Another run already holds the workspace lock."""


def lock_path(workspace: Path) -> Path:
    """Where ``workspace``'s run lock lives — under ``.git``, out of the tracked tree."""
    return workspace / '.git' / _LOCK_NAME


def lock_owner_pid(workspace: Path) -> int | None:
    """The process id recorded in ``workspace``'s run lock, or ``None`` when there is not one.

    The lock has always written its owner's pid; nothing read it back, so the one durable
    trace a hard-killed run leaves behind was unused. ``None`` covers every way the answer
    is unavailable — no lock file, an unreadable one, a lock caught between ``O_CREAT`` and
    the write, contents that are not an integer — so a caller distinguishes "no owner to ask
    about" from "an owner that is gone" without handling four failure shapes.
    """
    try:
        recorded = lock_path(workspace).read_text(encoding='utf-8').strip()
    except OSError:
        return None
    try:
        return int(recorded)
    except ValueError:
        return None


@dataclass(frozen=True)
class LockOwnership:
    """What ``workspace``'s run lock currently says about who holds it.

    ``pid`` is ``None`` when there is no lock file at all — nothing to report an owner
    for, and nothing for ``stale`` to mean anything about. ``stale`` is ``True`` only
    on positive evidence: a lock naming a process that ``process_is_alive`` says is
    gone. A lock naming a live process is not stale, and neither is one this cannot
    read — the conservative direction throughout this module, since a false "stale"
    is what lets two runs race one workspace.
    """

    pid: int | None
    stale: bool


def lock_ownership(workspace: Path) -> LockOwnership:
    """Whether ``workspace``'s run lock is stale, and whose it is either way.

    The one place this judgement is made — composing :func:`lock_owner_pid` with
    :func:`~convoy.interface.proc.process_is_alive` — so a reader (``convoy status``'s
    ``dead``/``running`` split) and a writer (``convoy unlock``'s refusal) can never
    silently disagree about what "stale" means, the way two inline copies of the same
    two-line check eventually would.
    """
    pid = lock_owner_pid(workspace)
    if pid is None:
        return LockOwnership(pid=None, stale=False)
    return LockOwnership(pid=pid, stale=not process_is_alive(pid))


def remove_stale_lock(workspace: Path) -> bool:
    """Remove ``workspace``'s run lock if present; return whether one was there.

    For the recovery verbs only (``convoy clean``, ``convoy unlock``). A lock survives
    a hard-killed run because no ``finally`` ever ran, and it then blocks every later
    run with :class:`WorkspaceBusyError` until someone deletes the file by hand. This
    does that deletion. It deliberately does NOT check whether a run is still live
    itself — this function only ever removes what it is told to, and a caller that
    needs to know first uses :func:`lock_ownership` before calling it. ``unlock`` does;
    ``clean`` does not, because it already discards uncommitted work unconditionally,
    documented as destructive either way.
    """
    path = lock_path(workspace)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


@contextmanager
def workspace_lock(workspace: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``workspace`` for the duration of the ``with`` block.

    Raises :class:`WorkspaceBusyError` if the lock is already held. Always releases the
    lock on the way out, including when the block raises — a crashing run should not leave
    a permanent lock, though one left by a hard-killed process (no ``finally`` ever ran)
    may require manual removal, per the message below.
    """
    git_dir = workspace / '.git'
    git_dir.mkdir(parents=True, exist_ok=True)
    lock_path = git_dir / _LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise WorkspaceBusyError(
            f'workspace {workspace} is locked by another run (lock file: {lock_path}). '
            'If no convoy run is currently active against this workspace, the lock is '
            'stale (left behind by a killed process) and the lock file can be removed by hand.'
        ) from exc
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(str(os.getpid()))
        yield
    finally:
        lock_path.unlink(missing_ok=True)
