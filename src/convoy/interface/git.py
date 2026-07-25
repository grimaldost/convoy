"""Git working-tree operations the headless driver needs (shell).

The driver stages a fixture, branches per PR, and integrates the results. Those are the
operations here: reading the current branch, checking out (optionally creating) a ref,
staging-and-committing every change, and merging one branch into another with a merge
commit. Each is a thin wrapper over ``git`` run via ``subprocess.run`` in the tree's root;
a nonzero exit becomes a :class:`GitError` carrying the command's stderr.
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from convoy.interface.proc import GIT_HERMETIC_FLAGS, TEXT_ENCODING, TEXT_ERRORS


class GitError(RuntimeError):
    """A git command failed."""


class Git:
    def __init__(self, repo: Path) -> None:
        """Operate on the git working tree rooted at ``repo``."""
        self._repo = repo

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run ``git <args>`` in the repo, returning the completed process.

        Captures stdout/stderr as text and does not raise on nonzero exit — callers decide
        what a failure means.
        """
        return subprocess.run(
            ['git', *GIT_HERMETIC_FLAGS, *args],
            cwd=self._repo,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding=TEXT_ENCODING,
            errors=TEXT_ERRORS,
            check=False,
        )

    def _run_checked(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run ``git <args>``; raise :class:`GitError` with stderr on nonzero exit."""
        result = self._run(*args)
        if result.returncode != 0:
            raise GitError(result.stderr.strip())
        return result

    def current_branch(self) -> str:
        """The checked-out branch name."""
        result = self._run_checked('rev-parse', '--abbrev-ref', 'HEAD')
        return result.stdout.strip()

    def checkout(self, ref: str, *, create: bool = False) -> None:
        """Check out ``ref``.

        If ``create`` is true, create the branch from current HEAD first
        (``git checkout -b ref``). Raise :class:`GitError` on failure.
        """
        if create:
            self._run_checked('checkout', '-b', ref)
        else:
            self._run_checked('checkout', ref)

    def commit_all(self, message: str) -> None:
        """Stage every change (``git add -A``) and commit with ``message``.

        If there is nothing to commit, do nothing (idempotent no-op, not an error). Raise
        :class:`GitError` on a real git failure.
        """
        # Check for a clean tree BEFORE staging so the no-op path never shells a failing
        # commit: an empty ``git status --porcelain`` means there is nothing to record.
        status = self._run_checked('status', '--porcelain')
        if not status.stdout.strip():
            return
        self._run_checked('add', '-A')
        self._run_checked('commit', '-m', message)

    def reset_to_base(self, base: str, branches: Sequence[str]) -> None:
        """Check out ``base``, then force-delete every name in ``branches``.

        A branch that does not exist is not an error (already-clean state); any other git
        failure (e.g. deleting the currently checked-out branch) raises :class:`GitError`.
        """
        self._run_checked('checkout', base)
        for branch in branches:
            result = self._run('branch', '-D', branch)
            if result.returncode != 0 and 'not found' not in result.stderr:
                raise GitError(result.stderr.strip())

    def status_porcelain(self) -> tuple[str, ...]:
        """Every non-empty line of ``git status --porcelain`` (empty tuple when clean).

        ``--porcelain`` is git's documented stable machine format, so callers can classify
        entries by their two-column status code without parsing human prose — untracked
        paths are the ``??`` lines. Ignored files are excluded, matching ``git clean -fd``.
        """
        result = self._run_checked('status', '--porcelain')
        return tuple(line for line in result.stdout.splitlines() if line.strip())

    def discard_changes(self) -> None:
        """``git reset --hard`` — discard every modification to TRACKED files.

        Destructive and unrecoverable for uncommitted work. Untracked files are untouched
        (that is :meth:`clean_untracked`'s job). Needed before checking out another branch
        after a killed run, whose half-written tracked files would otherwise block or ride
        along with the checkout.
        """
        self._run_checked('reset', '--hard')

    def clean_untracked(self) -> None:
        """``git clean -fd`` — delete untracked files and directories.

        Destructive and unrecoverable. Ignored files are NOT removed (no ``-x``), so a
        local venv or editor state survives. Use :meth:`status_porcelain` to enumerate what
        this would delete before calling it.
        """
        self._run_checked('clean', '-fd')

    def branch_exists(self, name: str) -> bool:
        """Whether a local branch called ``name`` exists."""
        result = self._run('rev-parse', '--verify', '--quiet', f'refs/heads/{name}')
        return result.returncode == 0

    def merge(self, source: str, into: str) -> None:
        """Check out ``into``, then merge ``source`` into it with a merge commit.

        Uses ``git merge --no-ff --no-edit source`` and leaves ``into`` checked out. Raise
        :class:`GitError` on conflict/failure.
        """
        self._run_checked('checkout', into)
        self._run_checked('merge', '--no-ff', '--no-edit', source)
