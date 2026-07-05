"""An exclusive per-workspace lock so two concurrent runs never interleave git operations.

convoy's posture is fail-loud: a second ``convoy run`` against a workspace already in use
must fail immediately with a clear message, not corrupt the tree by racing the first run's
checkouts and commits. The lock file lives under ``.git`` so it never dirties the tracked
working tree.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LOCK_NAME = 'convoy-run.lock'


class WorkspaceBusyError(Exception):
    """Another run already holds the workspace lock."""


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
