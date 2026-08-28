"""Git working-tree operations the headless driver needs (shell).

The driver stages a fixture, branches per PR, and integrates the results. Those are the
operations here: reading the current branch, checking out (optionally creating) a ref,
staging-and-committing every change, and merging one branch into another with a merge
commit. Each is a thin wrapper over ``git`` run via ``subprocess.run`` in the tree's root;
a nonzero exit becomes a :class:`GitError` naming the failing command and carrying its
stderr.
"""

import shlex
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

    def _run(self, *args: str, stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
        """Run ``git <args>`` in the repo, returning the completed process.

        Captures stdout/stderr as text and does not raise on nonzero exit — callers decide
        what a failure means. ``stdin_text`` feeds a command that reads operands from
        standard input rather than argv, which is how a path list longer than the platform
        command line is passed; without it stdin stays closed.
        """
        return subprocess.run(
            ['git', *GIT_HERMETIC_FLAGS, *args],
            cwd=self._repo,
            stdin=subprocess.DEVNULL if stdin_text is None else None,
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding=TEXT_ENCODING,
            errors=TEXT_ERRORS,
            check=False,
        )

    def _failure(self, args: Sequence[str], result: subprocess.CompletedProcess[str]) -> GitError:
        """A :class:`GitError` naming the command that failed, then what git said about it.

        The command comes first because it is the half a reader cannot recover: git's
        stderr says *what* went wrong ("pathspec did not match any file(s) known to git"),
        never *which* invocation asked — and convoy shells a dozen of them per PR. The
        hermetic ``-c`` flags are left out; they are on every command, so including them
        would bury the subcommand in constant noise, which is the burial this message
        exists to undo. An argument carrying whitespace is quoted, so a commit message
        cannot be mistaken for further operands.

        When git said nothing on stderr the exit code stands in. That path is real, not
        defensive: ``git commit`` reports "nothing to commit" on *stdout* and leaves
        stderr empty, which used to raise a `GitError` whose message was the empty string.
        """
        command = ' '.join(shlex.quote(arg) for arg in ('git', *args))
        detail = result.stderr.strip() or f'exited {result.returncode}'
        return GitError(f'{command}: {detail}')

    def _run_checked(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run ``git <args>``; raise :class:`GitError` naming it on nonzero exit."""
        result = self._run(*args)
        if result.returncode != 0:
            raise self._failure(args, result)
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
            self.delete_branch(branch)

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

    def rev_parse(self, ref: str) -> str:
        """The commit sha ``ref`` resolves to."""
        return self._run_checked('rev-parse', ref).stdout.strip()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether every commit of ``ancestor`` is contained in ``descendant``.

        ``git merge-base --is-ancestor``: exit 0 means contained, 1 means not. Note a
        commit is an ancestor of ITSELF, which is why :meth:`is_merged_into` exists.
        """
        return self._run('merge-base', '--is-ancestor', ancestor, descendant).returncode == 0

    def is_merged_into(self, branch: str, target: str) -> bool:
        """Whether ``branch`` was actually merged into ``target`` — not merely contained by it.

        Containment alone is the wrong question, and getting it wrong is expensive. A PR
        branch created from the integration branch whose implementation committed nothing
        points at the *same commit*, and ``merge-base --is-ancestor`` duly reports it as
        contained — so a resumed run would skip a PR that never landed, and the series
        would report completed having silently dropped it.

        The driver always integrates with ``merge --no-ff``, so a genuinely merged branch
        is a **strict** ancestor: contained, and not the same commit. That is the signal.
        """
        if self.rev_parse(branch) == self.rev_parse(target):
            return False
        return self.is_ancestor(branch, target)

    def delete_branch(self, name: str) -> None:
        """Force-delete local branch ``name``; a branch that does not exist is not an error."""
        args = ('branch', '-D', name)
        result = self._run(*args)
        if result.returncode != 0 and 'not found' not in result.stderr:
            raise self._failure(args, result)

    def merge(self, source: str, into: str) -> None:
        """Check out ``into``, then merge ``source`` into it with a merge commit.

        Uses ``git merge --no-ff --no-edit source`` and leaves ``into`` checked out. Raise
        :class:`GitError` on conflict/failure.
        """
        self._run_checked('checkout', into)
        self._run_checked('merge', '--no-ff', '--no-edit', source)

    def ignored(self, paths: Sequence[str]) -> frozenset[str]:
        """Which of ``paths`` this repository's own ignore rules exclude.

        Asks ``git check-ignore``, so the answer is the repo's rules — ``.gitignore``, the
        global excludes file, ``.git/info/exclude`` — rather than convoy's guess at what a
        borrowed directory is called. A tracked file is never reported, which is the right
        reading: the repo decided to keep it.

        Empty on any failure, so a caller can treat the answer as advice. There are three
        ordinary ways to fail — no ``git`` on PATH, a workspace that is not a repository,
        and exit 1 meaning "none of them are ignored" — and none of them should be louder
        than the question. Paths are given repo-relative and NUL-delimited on stdin, which
        both survives a path containing whitespace and keeps a large tree off the command
        line.
        """
        if not paths:
            return frozenset()
        try:
            result = self._run('check-ignore', '--stdin', '-z', stdin_text='\0'.join(paths))
        except OSError:
            return frozenset()
        if result.returncode != 0:
            return frozenset()
        return frozenset(entry for entry in result.stdout.split('\0') if entry)
