"""An exclusive per-workspace lock so two concurrent runs never interleave git operations.

convoy's posture is fail-loud: a second ``convoy run`` against a workspace already in use
must fail immediately with a clear message, not corrupt the tree by racing the first run's
checkouts and commits. The lock file lives under ``.git`` so it never dirties the tracked
working tree.

:func:`judge_lock` is a second, unrelated lock with the same file shape: the hook's, held
while one firing gates a tree. It waits instead of failing at once, and it never uses the
run lock's file name, so nothing that reads the run lock can mistake one for the other.
"""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from convoy.interface.proc import process_is_alive

_LOCK_NAME = 'convoy-run.lock'

_CREATE_NEW = os.O_CREAT | os.O_EXCL | os.O_WRONLY

# Windows refuses to delete a file another process has open, and a waiter reads the lock to
# learn its owner. The read takes microseconds, so a release retries for up to a second.
_UNLINK_ATTEMPTS = 100
_UNLINK_RETRY_SECONDS = 0.01

# A lock file with no readable pid, or a ``.break`` file (which records none), has only its
# age to say whether its owner is gone. Both are alive for milliseconds in a healthy run, so
# a few seconds is long past any process that is still working on them.
_ORPHAN_AFTER_SECONDS = 10.0


class WorkspaceBusyError(Exception):
    """Another run already holds the workspace lock."""


class JudgeBusyError(Exception):
    """Another holder kept a :func:`judge_lock` for the whole bounded wait."""


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
    return _recorded_pid(lock_path(workspace))


def _recorded_pid(path: Path) -> int | None:
    """The pid a lock file at *path* records; ``None`` for every way there is not one."""
    try:
        recorded = path.read_text(encoding='utf-8').strip()
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


def _unlink(path: Path) -> None:
    """Remove *path* if present, retrying while another process briefly has it open.

    A failure that outlasts the retries is left in place rather than raised from a
    ``finally``: the file then names a process that is about to exit, and the next waiter
    removes it as stale. That holds for a lock file, which records a pid. A ``.break`` file
    records none, and :func:`_remove_if_stale` removes it by its age.
    """
    for _ in range(_UNLINK_ATTEMPTS):
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            time.sleep(_UNLINK_RETRY_SECONDS)
        else:
            return


def _seconds_old(path: Path) -> float | None:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _is_orphaned(path: Path) -> bool:
    """Whether the process that made *path* is gone, as far as the file can say.

    A recorded pid is judged as :func:`lock_ownership` judges one: stale when
    :func:`process_is_alive` says no such process, and never when it is this process. A
    file with no readable pid is a holder caught between creating it and writing the pid
    while it is new, and orphaned once it is older than :data:`_ORPHAN_AFTER_SECONDS`: the
    holder was killed in that window and nothing else will ever fill the file in.
    """
    pid = _recorded_pid(path)
    if pid is None:
        age = _seconds_old(path)
        return age is not None and age > _ORPHAN_AFTER_SECONDS
    return pid != os.getpid() and not process_is_alive(pid)


def _remove_if_stale(path: Path) -> bool:
    """Remove the lock at *path* when its holder is gone; return whether it did.

    Two waiters can find the same stale lock, so the removal happens under ``<name>.break``,
    taken with the same ``O_EXCL`` create, and looks again there: a waiter that arrives
    after another has already replaced the lock sees a different pid and leaves the new
    holder alone. The break file records no pid, so one that outlives its waiter (killed
    between the create and the cleanup) is told by its age and removed, or the lock it
    guards could never be taken over again.
    """
    seen = _recorded_pid(path)
    if not _is_orphaned(path):
        return False
    breaker = path.with_name(path.name + '.break')
    age = _seconds_old(breaker)
    if age is not None and age > _ORPHAN_AFTER_SECONDS:
        _unlink(breaker)
    try:
        os.close(os.open(breaker, _CREATE_NEW))
    except OSError:
        return False  # another waiter is removing it; the next poll sees the result
    try:
        if _recorded_pid(path) != seen or not _is_orphaned(path):
            return False
        path.unlink()
    except OSError:
        return False
    else:
        return True
    finally:
        _unlink(breaker)


def _busy_message(path: Path, wait_seconds: float) -> str:
    """Why a judge lock stayed taken for the whole wait, and what removes it."""
    owner = _recorded_pid(path)
    breaker = path.with_name(path.name + '.break')
    if owner is not None and owner != os.getpid() and not process_is_alive(owner):
        return (
            f'{path} was left by pid {owner}, which is gone, and could not be taken over '
            f'within {wait_seconds:g} s; remove {path} and {breaker} by hand'
        )
    holder = f'pid {owner}' if owner is not None else 'another process'
    return (
        f'{path} is held by {holder}; waited {wait_seconds:g} s. If no convoy hook is '
        f'running in this tree, remove {path} (and {breaker}, if it exists) by hand'
    )


@contextmanager
def judge_lock(path: Path, *, wait_seconds: float, poll_seconds: float) -> Iterator[None]:
    """Hold the advisory lock file at *path* for the ``with`` block, waiting up to *wait_seconds*.

    The hook's lock: one firing at a time gates a tree and writes its log line, where
    :func:`workspace_lock` refuses a second run outright. The caller supplies the path, and
    it is never the run lock's — :func:`lock_path`, :func:`lock_ownership`,
    :func:`remove_stale_lock` and the verbs built on them read ``convoy-run.lock`` only, so
    a held judge lock never reads as a driven workspace.

    The file is created with ``O_CREAT | O_EXCL`` and records the holder's pid. A waiter
    tries again every *poll_seconds*; once *wait_seconds* have passed it raises
    :class:`JudgeBusyError`, naming the file and the pid it records. A lock whose recorded
    process is gone (a firing killed at the hook timeout never reaches its ``finally``), or
    that records none and has sat for seconds (killed before it wrote one), is removed and
    taken. The file is removed on the way out, including when the block raises.
    It is advisory: it orders the processes that take it and constrains nothing else.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            fd = os.open(path, _CREATE_NEW)
        except FileExistsError:
            if _remove_if_stale(path):
                continue
            if time.monotonic() >= deadline:
                raise JudgeBusyError(_busy_message(path, wait_seconds)) from None
        except PermissionError:
            # Windows answers a create that races a delete with "access denied". A
            # directory that is really not writable keeps answering it, and that error is
            # raised once the wait runs out.
            if time.monotonic() >= deadline:
                raise
        else:
            break
        time.sleep(poll_seconds)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        _unlink(path)
