"""Tests for the git adapter, driving real ``git`` in a ``tmp_path`` repo.

Every test builds a fresh repo under ``tmp_path`` via :func:`_init_repo`, which sets local
``user.email``/``user.name`` so commits work regardless of global config and lays down one
initial commit on a known base branch. State is asserted by shelling ``git`` directly (with
``cwd`` at the repo root), never through the adapter under test.
"""

import subprocess
from pathlib import Path

import pytest

from convoy.interface.git import Git, GitError

# The base branch every fixture repo starts on — named explicitly so tests do not depend on
# whatever ``init.defaultBranch`` happens to be configured on the host.
_BASE = 'base'


def _git(repo: Path, *args: str) -> str:
    """Run ``git <args>`` in ``repo`` and return stripped stdout, failing the test on error."""
    result = subprocess.run(
        ['git', *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    """Init a repo on branch ``_BASE`` with local identity and one initial commit."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-b', _BASE)
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test User')
    (repo / 'README.md').write_text('initial\n', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'initial commit')
    return repo


def test_current_branch_after_init(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    assert Git(repo).current_branch() == _BASE


def test_checkout_create_makes_and_switches_to_new_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)

    git.checkout('feature', create=True)

    assert git.current_branch() == 'feature'
    assert _git(repo, 'rev-parse', '--abbrev-ref', 'HEAD') == 'feature'


def test_checkout_existing_branch_switches(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)
    git.checkout('feature', create=True)

    git.checkout(_BASE)

    assert git.current_branch() == _BASE


def test_commit_all_commits_new_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)
    before = _git(repo, 'rev-parse', 'HEAD')

    (repo / 'new.txt').write_text('content\n', encoding='utf-8')
    git.commit_all('add new file')

    after = _git(repo, 'rev-parse', 'HEAD')
    assert after != before
    # The file is tracked in the new commit and the tree is clean.
    assert 'new.txt' in _git(repo, 'ls-files')
    assert _git(repo, 'status', '--porcelain') == ''
    assert _git(repo, 'log', '-1', '--pretty=%s') == 'add new file'


def test_commit_all_with_no_changes_is_clean_no_op(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)

    (repo / 'new.txt').write_text('content\n', encoding='utf-8')
    git.commit_all('add new file')
    head_after_first = _git(repo, 'rev-parse', 'HEAD')

    # Second call with nothing staged/changed: no new commit, no error.
    git.commit_all('nothing to do')

    assert _git(repo, 'rev-parse', 'HEAD') == head_after_first


def test_merge_brings_feature_file_onto_target_and_leaves_it_checked_out(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)

    # Create a file on a feature branch.
    git.checkout('feature', create=True)
    (repo / 'feature.txt').write_text('from feature\n', encoding='utf-8')
    git.commit_all('add feature file')

    # Merge feature into base; base ends up checked out with the feature file present.
    git.merge('feature', into=_BASE)

    assert git.current_branch() == _BASE
    assert (repo / 'feature.txt').read_text(encoding='utf-8') == 'from feature\n'
    assert 'feature.txt' in _git(repo, 'ls-files')
    # ``--no-ff`` forces a merge commit: HEAD has two parents.
    parents = _git(repo, 'rev-list', '--parents', '-n', '1', 'HEAD').split()
    assert len(parents) == 3


def test_checkout_nonexistent_ref_raises_git_error(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)

    with pytest.raises(GitError):
        git.checkout('does-not-exist')


def test_reset_to_base_deletes_existing_branches_and_checks_out_base(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)
    git.checkout('feature', create=True)
    git.checkout(_BASE)

    git.reset_to_base(_BASE, ['feature'])

    assert git.current_branch() == _BASE
    branches = _git(repo, 'branch', '--list')
    assert 'feature' not in branches


def test_reset_to_base_is_a_no_op_for_a_missing_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)

    git.reset_to_base(_BASE, ['does-not-exist'])

    assert git.current_branch() == _BASE


def test_reset_to_base_raises_git_error_on_a_real_failure(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    git = Git(repo)

    with pytest.raises(GitError):
        git.reset_to_base('does-not-exist-base', [])
