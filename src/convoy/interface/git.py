"""Git working-tree operations the headless driver needs (shell).

The driver stages a fixture, branches per PR, and integrates the results. Those are the
operations here: reading the current branch, checking out (optionally creating) a ref,
staging-and-committing every change, and merging one branch into another with a merge
commit. Each is a thin wrapper over ``git`` run via ``subprocess.run`` in the tree's root;
a nonzero exit becomes a :class:`GitError` carrying the command's stderr.
"""

import subprocess
from pathlib import Path


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
            ['git', *args],
            cwd=self._repo,
            capture_output=True,
            text=True,
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

    def merge(self, source: str, into: str) -> None:
        """Check out ``into``, then merge ``source`` into it with a merge commit.

        Uses ``git merge --no-ff --no-edit source`` and leaves ``into`` checked out. Raise
        :class:`GitError` on conflict/failure.
        """
        self._run_checked('checkout', into)
        self._run_checked('merge', '--no-ff', '--no-edit', source)
