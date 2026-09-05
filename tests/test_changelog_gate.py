"""Red proofs for ``scripts/changelog_gate.py`` — the check must be able to say no.

The verdict is the pure ``evaluate``; the tests up top feed it synthetic diffs and prove
each arm can fail, plus the one non-vacuity guard the advisory arm needs: the
contract-surface list must keep naming files that exist, or a rename silently retires the
warning while the workflow stays green. What ``evaluate`` is *given* — which commits are
merges and what each one contributed — is ``main``'s half of the decision and the harder
one to get right, so the record-or-declare and merge cases are proven end to end instead:
a real git repository in ``tmp_path`` and the real script as a subprocess.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / 'scripts' / 'changelog_gate.py'

_spec = importlib.util.spec_from_file_location('changelog_gate', _SCRIPT)
assert _spec is not None and _spec.loader is not None
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _evaluate(
    changed: list[str],
    messages: str = 'fix: something\n',
    changelog_added: str = '',
    changelog_removed: str = '',
    base_version: tuple[int, int, int] | None = (0, 9, 1),
    head_version: tuple[int, int, int] | None = (0, 9, 1),
) -> tuple[list[str], list[str]]:
    """Single-commit convenience: ``changed``/``messages`` are that one commit's own
    diff and message, which is also the whole range's aggregate for the other checks."""
    commits = [(changed, messages)]
    return gate.evaluate(
        changed, commits, changelog_added, changelog_removed, base_version, head_version
    )


# --- record or declare -------------------------------------------------------


def test_an_engine_change_without_a_changelog_entry_fails() -> None:
    """The red proof for the main arm: src/ moved, CHANGELOG.md did not, nothing declared."""
    errors, _ = _evaluate(['src/convoy/interface/git.py', 'tests/test_git.py'])
    assert len(errors) == 1
    assert 'CHANGELOG.md' in errors[0]


def test_an_engine_change_with_a_changelog_entry_passes() -> None:
    """A changelog *entry* means added lines, not merely the path being touched."""
    errors, _ = _evaluate(
        ['src/convoy/interface/git.py', 'CHANGELOG.md'],
        changelog_added='- Recorded the change.\n',
    )
    assert errors == []


def test_the_declared_exemption_needs_a_reason() -> None:
    """A bare `Changelog: none` is not the trailer — the parenthesis is the reviewable part."""
    declared = _evaluate(
        ['src/convoy/interface/git.py'],
        messages='chore: rename an internal\n\nChangelog: none (no observable change)\n',
    )
    bare = _evaluate(
        ['src/convoy/interface/git.py'],
        messages='chore: rename an internal\n\nChangelog: none\n',
    )
    assert declared[0] == []
    assert len(bare[0]) == 1


def test_the_declared_exemption_is_case_insensitive() -> None:
    """A casing typo states the same decision; rejecting it would mislead, not protect."""
    errors, _ = _evaluate(
        ['src/convoy/interface/git.py'],
        messages='chore: rename an internal\n\nchangelog: None (no observable change)\n',
    )
    assert errors == []


def test_a_whitespace_only_changelog_edit_does_not_record_the_change() -> None:
    """A trailing-space edit to a blank line, or an appended blank line, produces a
    non-empty added diff that carries no content at all."""
    errors, _ = _evaluate(['src/convoy/interface/git.py'], changelog_added='   \n\n')
    assert len(errors) == 1
    assert 'CHANGELOG.md' in errors[0]


def test_an_added_line_the_diff_also_removes_does_not_record_the_change() -> None:
    """Red proof for the harder half: a trailing space on an *existing* line adds a
    line that survives ``strip()``. It is a record only if the same diff does not also
    remove it — which, in collapsed form, it does."""
    errors, _ = _evaluate(
        ['src/convoy/interface/git.py'],
        changelog_added='- an old line \n',
        changelog_removed='- an old line\n',
    )
    assert len(errors) == 1
    assert 'CHANGELOG.md' in errors[0]


def test_one_new_line_among_re_added_ones_records_the_change() -> None:
    """The positive counterpart: churn around a genuinely new line is still a record."""
    errors, _ = _evaluate(
        ['src/convoy/interface/git.py'],
        changelog_added='  - an old line\n- a new line\n',
        changelog_removed='- an old line\n',
    )
    assert errors == []


def test_a_change_outside_the_engine_carries_no_obligation() -> None:
    errors, warnings = _evaluate(['docs/backlog.md', '.github/workflows/ci.yml'])
    assert errors == []
    assert warnings == []


def test_windows_path_separators_are_normalized() -> None:
    errors, _ = _evaluate(['src\\convoy\\interface\\git.py'])
    assert len(errors) == 1


# --- record or declare is judged per commit, not per range --------------------


def test_a_trailer_on_one_commit_does_not_exempt_a_different_untrailered_commit() -> None:
    """Red proof: commit A touches src/ with no changelog and no trailer; commit B is
    unrelated and carries the trailer. The declaration is reviewable for B and must not
    silently cover A."""
    commits = [
        (['src/convoy/interface/git.py'], 'fix: change engine behavior\n'),
        (['docs/backlog.md'], 'chore: tidy a comment\n\nChangelog: none (comment only)\n'),
    ]
    errors, _ = gate.evaluate([], commits, '', '', (0, 9, 1), (0, 9, 1))
    assert len(errors) == 1
    assert 'git.py' in errors[0]


def test_a_commit_that_deletes_the_changelog_still_fails() -> None:
    """Red proof: a commit touching src/ that only deletes or whitespace-edits
    CHANGELOG.md must fail — touching the file is not recording the change."""
    commits = [(['src/convoy/interface/git.py', 'CHANGELOG.md'], 'fix: change engine behavior\n')]
    errors, _ = gate.evaluate([], commits, '', '', (0, 9, 1), (0, 9, 1))
    assert len(errors) == 1


def test_a_trailer_on_the_commit_that_touches_the_engine_passes() -> None:
    commits = [
        (
            ['src/convoy/interface/git.py'],
            'fix: change engine behavior\n\nChangelog: none (internal only)\n',
        ),
        (['docs/backlog.md'], 'chore: tidy a comment\n'),
    ]
    errors, _ = gate.evaluate([], commits, '', '', (0, 9, 1), (0, 9, 1))
    assert errors == []


def test_an_added_changelog_line_exempts_every_engine_commit_in_the_range() -> None:
    commits = [
        (['src/convoy/interface/git.py'], 'fix: change engine behavior\n'),
        (['src/convoy/interface/other.py'], 'fix: another engine change\n'),
    ]
    errors, _ = gate.evaluate([], commits, '- Recorded the change.\n', '', (0, 9, 1), (0, 9, 1))
    assert errors == []


# A merge commit is no longer skipped — ``main`` charges it with its resolution, the
# content an automatic merge of its parents would not have produced. Which commits are
# merges and what they resolved is ``main``'s job, not ``evaluate``'s, so it is proven
# end to end below (a real repo, real merges, the real script as a subprocess) rather
# than through ``evaluate`` directly: see the ``test_end_to_end_*merge*`` cases.


# --- the merge charge refuses to guess ---------------------------------------


def test_a_merge_tree_that_wrote_no_tree_fails_naming_the_git_version() -> None:
    """``git merge-tree --write-tree`` arrived in git 2.38; an older git answers the
    option with a usage error on stdout, and a git that cannot merge the two parents
    answers with a diagnostic. Neither is a tree, and neither may be quietly downgraded
    back to the combined diff — the failure has to name the git it ran."""
    refused = subprocess.CompletedProcess(
        args=['git', 'merge-tree', '--write-tree', 'a', 'b'],
        returncode=129,
        stdout='usage: git merge-tree [--trivial-merge] <base-tree> <branch1> <branch2>\n',
        stderr='',
    )
    try:
        gate._auto_merge_tree(refused, 'git version 2.30.0\n')
    except RuntimeError as failure:
        assert 'git version 2.30.0' in str(failure)
        assert '2.38' in str(failure)
    else:
        raise AssertionError('a merge-tree that wrote no tree must not return an object id')


def test_a_conflicted_merge_tree_is_still_a_tree() -> None:
    """Exit 1 is a *conflicted* automatic merge, not a failure: merge-tree writes the
    tree with the conflict markers in it, and diffing that against the merge commit is
    exactly how a hand resolution is told from an automatic one."""
    conflicted = subprocess.CompletedProcess(
        args=['git', 'merge-tree', '--write-tree', 'a', 'b'],
        returncode=1,
        stdout='0' * 40 + '\n\n100644 ' + '1' * 40 + ' 1\tsrc/convoy/engine.py\n',
        stderr='',
    )
    assert gate._auto_merge_tree(conflicted, 'git version 2.53.0') == '0' * 40


# --- the release heading must move the version forward -----------------------


def test_a_release_heading_matching_a_forward_bump_passes() -> None:
    errors, _ = _evaluate(
        ['CHANGELOG.md', 'pyproject.toml'],
        changelog_added='## [0.9.2] - 2026-08-29\n',
        base_version=(0, 9, 1),
        head_version=(0, 9, 2),
    )
    assert errors == []


def test_a_release_heading_that_does_not_move_the_version_fails() -> None:
    errors, _ = _evaluate(
        ['CHANGELOG.md'],
        changelog_added='## [0.9.1] - 2026-08-29\n',
        base_version=(0, 9, 1),
        head_version=(0, 9, 1),
    )
    assert any('does not move the version forward' in error for error in errors)


def test_a_release_heading_disagreeing_with_pyproject_fails() -> None:
    errors, _ = _evaluate(
        ['CHANGELOG.md'],
        changelog_added='## [0.10.0] - 2026-08-29\n',
        base_version=(0, 9, 1),
        head_version=(0, 9, 2),
    )
    assert any('must move together' in error for error in errors)


# --- the consumer-affecting marker is advisory -------------------------------


def test_a_contract_surface_change_without_the_marker_warns_and_does_not_fail() -> None:
    errors, warnings = _evaluate(
        ['src/convoy/core/telemetry.py', 'CHANGELOG.md'],
        changelog_added='- A new telemetry field nobody marked.\n',
    )
    assert errors == []
    assert len(warnings) == 1
    assert '(consumer-affecting)' in warnings[0]


def test_a_contract_surface_change_with_the_marker_is_quiet() -> None:
    _, warnings = _evaluate(
        ['src/convoy/core/telemetry.py', 'CHANGELOG.md'],
        changelog_added='- A new telemetry field. **(consumer-affecting)**\n',
    )
    assert warnings == []


def test_the_contract_surface_list_names_files_that_exist() -> None:
    """Non-vacuity: a renamed surface file would retire the advisory without a sound."""
    missing = [path for path in gate.CONTRACT_SURFACES if not (_ROOT / path).is_file()]
    assert not missing, f'CONTRACT_SURFACES names files that do not exist: {missing}'


# --- the section-heading vocabulary ------------------------------------------


def test_a_heading_outside_the_vocabulary_fails() -> None:
    """The red proof: `### Documentation` reached main once; the gate must say no."""
    errors, _ = _evaluate(
        ['src/convoy/interface/git.py', 'CHANGELOG.md'],
        changelog_added='### Documentation\n\n- Described a behaviour.\n',
    )
    assert len(errors) == 1
    assert 'Documentation' in errors[0]
    assert 'Added / Changed / Deprecated / Removed / Fixed / Security' in errors[0]


def test_every_keep_a_changelog_heading_passes() -> None:
    added = '\n'.join(f'### {word}' for word in gate.SECTION_VOCABULARY)
    errors, _ = _evaluate(
        ['src/convoy/interface/git.py', 'CHANGELOG.md'],
        changelog_added=added + '\n',
    )
    assert errors == []


def test_deeper_and_shallower_headings_are_not_section_headings() -> None:
    """`## [0.9.1]` and `#### detail` are other grammar; only `### ` carries the vocabulary."""
    errors, _ = _evaluate(
        ['src/convoy/interface/git.py', 'CHANGELOG.md'],
        changelog_added='## [0.9.2] - 2026-09-01\n#### a nested note\n- a bullet\n',
        base_version=(0, 9, 1),
        head_version=(0, 9, 2),
    )
    assert errors == []


def test_the_vocabulary_check_reads_only_the_added_lines() -> None:
    """History is grandfathered: an empty diff of CHANGELOG.md raises nothing."""
    errors, _ = _evaluate(
        ['src/convoy/interface/git.py', 'CHANGELOG.md'],
        changelog_added='- an ordinary bullet under an existing heading\n',
    )
    assert errors == []


# --- end to end: a real repo, a real merge, the real script as a subprocess --------
#
# ``evaluate`` is pure and the tests above drive it directly, but two things live only
# in ``main``: which commits are merges (and what their own resolution diff is), and
# what the script actually prints and exits with. These run ``scripts/changelog_gate.py``
# unchanged, as CI does, against a repo built from real commits — which makes them the
# black-box counterpart of the record-or-declare red proofs: point the same test, run
# unchanged, at the pre-fix script (swapped in at the same path) and it fails for the
# reported reason, not from a signature mismatch or a `changed=[]` the pre-fix code
# could never fault.


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ['git', *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _wide(top: str = 'top', bottom: str = 'bottom') -> str:
    """An engine file long enough that an edit near its top and one near its bottom fall
    in separate diff hunks, so two branches can each edit it and still merge cleanly."""
    lines = [f'value_{n} = {n}' for n in range(40)]
    lines[1] = f'value_1 = {top!r}'
    lines[38] = f'value_38 = {bottom!r}'
    return '\n'.join(lines) + '\n'


def _init_repo(repo: Path) -> None:
    """One commit on branch ``base``: two engine files, a docs file, an open
    ``[Unreleased]`` section, and ``pyproject.toml`` at 0.9.0 — a PR branch builds on
    top of this."""
    _git(['init', '-q', '-b', 'main', '.'], cwd=repo)
    _git(['config', 'user.email', 't@t'], cwd=repo)
    _git(['config', 'user.name', 't'], cwd=repo)
    _git(['config', 'commit.gpgsign', 'false'], cwd=repo)
    # Pinned, not inherited: the CRLF red proof below commits a file whose only change is
    # its line endings, and a machine whose global `core.autocrlf` is `true` would
    # normalize that change away before the gate ever saw it.
    _git(['config', 'core.autocrlf', 'false'], cwd=repo)
    (repo / 'src' / 'convoy').mkdir(parents=True)
    (repo / 'docs').mkdir()
    (repo / 'pyproject.toml').write_text(
        '[project]\nname = "t"\nversion = "0.9.0"\n', encoding='utf-8'
    )
    (repo / 'CHANGELOG.md').write_text(
        '# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- an old line\n- another old line\n',
        encoding='utf-8',
    )
    (repo / 'src' / 'convoy' / 'engine.py').write_text('x = 1\n', encoding='utf-8')
    (repo / 'src' / 'convoy' / 'wide.py').write_text(_wide(), encoding='utf-8')
    (repo / 'docs' / 'backlog.md').write_text('docs\n', encoding='utf-8')
    _git(['add', '-A'], cwd=repo)
    _git(['commit', '-q', '-m', 'chore: base'], cwd=repo)
    _git(['branch', 'base'], cwd=repo)


def _commit(repo: Path, message: str, edits: dict[str, str]) -> None:
    """Write each ``path -> content`` edit and commit them with ``message``."""
    for rel, content in edits.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    _git(['add', '-A'], cwd=repo)
    _git(['commit', '-q', '-m', message], cwd=repo)


def _run_gate(repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the real script as a subprocess against ``repo``, base ref ``base``."""
    return subprocess.run(
        [sys.executable, str(_SCRIPT), 'base'], cwd=repo, capture_output=True, text=True
    )


def test_end_to_end_a_trailer_on_one_commit_does_not_exempt_another(tmp_path: Path) -> None:
    """Red proof: commit A touches the engine with no trailer; commit B is unrelated
    and carries the trailer. Pre-fix, ``_TRAILER.search`` ran over every message in the
    range concatenated and found B's trailer, wrongly exempting A."""
    _init_repo(tmp_path)
    _commit(tmp_path, 'fix: change engine behavior\n', {'src/convoy/engine.py': 'x = 2\n'})
    _commit(
        tmp_path,
        'chore: tidy a comment\n\nChangelog: none (comment only)\n',
        {'docs/backlog.md': 'docs, tidied\n'},
    )
    result = _run_gate(tmp_path)
    assert result.returncode == 1
    assert 'change engine behavior' in result.stdout
    assert 'CHANGELOG.md' in result.stdout


def test_end_to_end_deleting_the_changelog_does_not_record_the_change(tmp_path: Path) -> None:
    """Red proof: a commit that changes the engine and deletes CHANGELOG.md must still
    fail. Pre-fix, the aggregate changed-file list contained ``CHANGELOG.md`` (deleted
    is still touched), which alone satisfied the old ``RECORD not in paths`` check."""
    _init_repo(tmp_path)
    (tmp_path / 'CHANGELOG.md').unlink()
    _commit(tmp_path, 'fix: change engine behavior\n', {'src/convoy/engine.py': 'x = 2\n'})
    result = _run_gate(tmp_path)
    assert result.returncode == 1
    assert 'CHANGELOG.md' in result.stdout


def test_end_to_end_a_whitespace_only_changelog_edit_does_not_record_the_change(
    tmp_path: Path,
) -> None:
    """Red proof: a commit that changes the engine and only appends blank lines to
    CHANGELOG.md must still fail — a non-empty diff is not the same as a record."""
    _init_repo(tmp_path)
    original = (tmp_path / 'CHANGELOG.md').read_text(encoding='utf-8')
    _commit(
        tmp_path,
        'fix: change engine behavior\n',
        {'src/convoy/engine.py': 'x = 2\n', 'CHANGELOG.md': original + '\n\n'},
    )
    result = _run_gate(tmp_path)
    assert result.returncode == 1
    assert 'CHANGELOG.md' in result.stdout


def test_end_to_end_a_merge_resolution_that_touches_the_engine_needs_recording(
    tmp_path: Path,
) -> None:
    """Red proof: a merge whose conflict resolution edits the engine, with neither a
    changelog addition nor a trailer on the merge commit itself, must fail — the merge
    is not exempt just because it is a merge. Both sides record their own change with a
    trailer, so the only unrecorded change left is the merge's own resolution."""
    _init_repo(tmp_path)
    _git(['checkout', '-q', '-b', 'side'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: side engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/engine.py': 'x = 2  # side\n'},
    )
    _git(['checkout', '-q', 'main'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: main engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/engine.py': 'x = 2  # main\n'},
    )
    subprocess.run(  # a real conflict: both sides touched the same line; do not check=True
        ['git', 'merge', '--no-ff', 'side'], cwd=tmp_path, capture_output=True, text=True
    )
    # Resolve by hand with content matching neither parent verbatim — the merge's own
    # contribution, the thing the fix charges to the merge commit.
    (tmp_path / 'src' / 'convoy' / 'engine.py').write_text('x = 2  # merged\n', encoding='utf-8')
    _git(['add', '-A'], cwd=tmp_path)
    _git(['commit', '-q', '-m', 'Merge branch side'], cwd=tmp_path)
    result = _run_gate(tmp_path)
    assert result.returncode == 1
    assert 'Merge branch side' in result.stdout
    assert 'CHANGELOG.md' in result.stdout


def test_end_to_end_a_clean_merge_passes(tmp_path: Path) -> None:
    """A merge with no conflict-resolution content of its own (each side's own change
    already recorded on its own commit) must not be charged a second time."""
    _init_repo(tmp_path)
    _git(['checkout', '-q', '-b', 'side'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: side engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/engine.py': 'x = 2\n'},
    )
    _git(['checkout', '-q', 'main'], cwd=tmp_path)
    _commit(tmp_path, 'docs: unrelated tidy\n', {'docs/backlog.md': 'docs, tidied\n'})
    _git(['merge', '--no-ff', '-m', 'Merge branch side', 'side'], cwd=tmp_path)
    result = _run_gate(tmp_path)
    assert result.returncode == 0


def test_end_to_end_a_clean_automerge_of_the_same_file_is_not_charged(tmp_path: Path) -> None:
    """Red proof: two branches edit the same engine file in *different hunks*, git merges
    them with no conflict, and the merge contributes nothing a reader could review — so
    the merge must not be charged. ``git diff-tree --cc --name-only`` charges it anyway:
    in ``--name-only`` mode ``--cc`` is ``-c``, which lists every file whose merge result
    differs from all parents, and a clean auto-merge of two hunks differs from both."""
    _init_repo(tmp_path)
    _git(['checkout', '-q', '-b', 'side'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: side engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/wide.py': _wide(top='side')},
    )
    _git(['checkout', '-q', 'main'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: main engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/wide.py': _wide(bottom='main')},
    )
    _git(['merge', '--no-ff', '-m', 'Merge branch side', 'side'], cwd=tmp_path)
    assert (tmp_path / 'src' / 'convoy' / 'wide.py').read_text(encoding='utf-8') == _wide(
        top='side', bottom='main'
    ), 'the fixture must be a clean auto-merge, not a resolution'
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout


def test_end_to_end_a_github_merge_ref_over_a_moved_base_is_not_charged(tmp_path: Path) -> None:
    """Red proof for the shape CI actually runs on. ``actions/checkout`` on a
    ``pull_request`` event checks out ``refs/pull/N/merge`` — a synthetic clean merge of
    the pull request's head into the base branch — so HEAD is a merge nobody authored.
    Charging it with ``--cc`` fails a legitimate pull request the moment the base branch
    edits the same engine file, and the author has no remedy: no trailer can be put on a
    commit GitHub generates."""
    _init_repo(tmp_path)
    _git(['checkout', '-q', '-b', 'pr'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: the engine change this pull request carries\n\nChangelog: none (internal only)\n',
        {'src/convoy/wide.py': _wide(top='pr')},
    )
    _git(['checkout', '-q', 'main'], cwd=tmp_path)
    _commit(tmp_path, 'fix: the base branch moved\n', {'src/convoy/wide.py': _wide(bottom='base')})
    _git(['branch', '-f', 'base', 'main'], cwd=tmp_path)
    # The merge ref's shape: base first, pull-request head second, message not the author's.
    _git(['checkout', '-q', '--detach', 'main'], cwd=tmp_path)
    _git(['merge', '--no-ff', '-m', 'Merge pr into main', 'pr'], cwd=tmp_path)
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout


def test_end_to_end_a_trailing_space_on_an_existing_changelog_line_is_not_a_record(
    tmp_path: Path,
) -> None:
    """Red proof: adding a trailing space to an *existing* CHANGELOG line produces an
    added line that is non-empty after ``strip()``, so stripping the added blob is not
    enough to tell churn from content. Nothing was recorded; the gate must still say no."""
    _init_repo(tmp_path)
    original = (tmp_path / 'CHANGELOG.md').read_text(encoding='utf-8')
    _commit(
        tmp_path,
        'fix: change engine behavior\n',
        {
            'src/convoy/engine.py': 'x = 2\n',
            'CHANGELOG.md': original.replace('- an old line', '- an old line '),
        },
    )
    result = _run_gate(tmp_path)
    assert result.returncode == 1, result.stdout
    assert 'CHANGELOG.md' in result.stdout


def test_end_to_end_reindenting_an_existing_changelog_line_is_not_a_record(
    tmp_path: Path,
) -> None:
    """The same defect from the other side: leading whitespace also survives ``strip()``."""
    _init_repo(tmp_path)
    original = (tmp_path / 'CHANGELOG.md').read_text(encoding='utf-8')
    _commit(
        tmp_path,
        'fix: change engine behavior\n',
        {
            'src/convoy/engine.py': 'x = 2\n',
            'CHANGELOG.md': original.replace('- an old line', '  - an old line'),
        },
    )
    result = _run_gate(tmp_path)
    assert result.returncode == 1, result.stdout
    assert 'CHANGELOG.md' in result.stdout


def test_end_to_end_converting_the_changelog_to_crlf_is_not_a_record(tmp_path: Path) -> None:
    """A line-ending conversion re-adds every line of the file and records nothing."""
    _init_repo(tmp_path)
    original = (tmp_path / 'CHANGELOG.md').read_text(encoding='utf-8')
    _commit(
        tmp_path,
        'fix: change engine behavior\n',
        {'src/convoy/engine.py': 'x = 2\n', 'CHANGELOG.md': original.replace('\n', '\r\n')},
    )
    result = _run_gate(tmp_path)
    assert result.returncode == 1, result.stdout
    assert 'CHANGELOG.md' in result.stdout


def test_end_to_end_reordering_existing_changelog_lines_is_not_a_record(tmp_path: Path) -> None:
    """Two existing bullets swapped: the diff adds lines, but every one of them it also
    removes. Nothing a changelog reader could not already read is there."""
    _init_repo(tmp_path)
    _commit(
        tmp_path,
        'fix: change engine behavior\n',
        {
            'src/convoy/engine.py': 'x = 2\n',
            'CHANGELOG.md': (
                '# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- another old line\n- an old line\n'
            ),
        },
    )
    result = _run_gate(tmp_path)
    assert result.returncode == 1, result.stdout
    assert 'CHANGELOG.md' in result.stdout


def test_end_to_end_a_new_bullet_among_whitespace_churn_is_a_record(tmp_path: Path) -> None:
    """The positive counterpart, so the check cannot pass by refusing everything: one
    genuinely new bullet is a record even when the same commit reflows the lines around
    it."""
    _init_repo(tmp_path)
    _commit(
        tmp_path,
        'fix: change engine behavior\n',
        {
            'src/convoy/engine.py': 'x = 2\n',
            'CHANGELOG.md': (
                '# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n'
                '  - an old line\n- another old line \n- a genuinely new bullet\n\n'
            ),
        },
    )
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout


def test_end_to_end_a_merge_resolution_outside_the_engine_is_not_charged(tmp_path: Path) -> None:
    """A conflict resolution is charged for what it resolves: a docs-only resolution
    carries no recording obligation, exactly as a docs-only commit does."""
    _init_repo(tmp_path)
    _git(['checkout', '-q', '-b', 'side'], cwd=tmp_path)
    _commit(tmp_path, 'docs: side wording\n', {'docs/backlog.md': 'docs, from the side\n'})
    _git(['checkout', '-q', 'main'], cwd=tmp_path)
    _commit(tmp_path, 'docs: main wording\n', {'docs/backlog.md': 'docs, from main\n'})
    subprocess.run(  # a real conflict on the docs file; do not check=True
        ['git', 'merge', '--no-ff', 'side'], cwd=tmp_path, capture_output=True, text=True
    )
    (tmp_path / 'docs' / 'backlog.md').write_text('docs, merged\n', encoding='utf-8')
    _git(['add', '-A'], cwd=tmp_path)
    _git(['commit', '-q', '-m', 'Merge branch side'], cwd=tmp_path)
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout


def test_end_to_end_a_merge_resolution_takes_the_trailer_like_any_commit(tmp_path: Path) -> None:
    """The remedy for a charged merge is the same one every other commit has: the
    resolution below edits ``src/``, and the trailer on the merge commit declares it."""
    _init_repo(tmp_path)
    _git(['checkout', '-q', '-b', 'side'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: side engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/engine.py': 'x = 2  # side\n'},
    )
    _git(['checkout', '-q', 'main'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: main engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/engine.py': 'x = 2  # main\n'},
    )
    subprocess.run(  # a real conflict; do not check=True
        ['git', 'merge', '--no-ff', 'side'], cwd=tmp_path, capture_output=True, text=True
    )
    (tmp_path / 'src' / 'convoy' / 'engine.py').write_text('x = 2  # merged\n', encoding='utf-8')
    _git(['add', '-A'], cwd=tmp_path)
    _git(
        ['commit', '-q', '-m', 'Merge branch side\n\nChangelog: none (resolution only)\n'],
        cwd=tmp_path,
    )
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout


def test_end_to_end_an_octopus_merge_keeps_the_combined_diff(tmp_path: Path) -> None:
    """Three parents are out of ``git merge-tree --write-tree``'s two-parent scope, so an
    octopus keeps the older ``--cc`` charge. This fixture separates the two: ``--cc``
    lists nothing (no file differs from *every* parent), while charging the first two
    parents as if they were the whole merge would charge the third branch's engine file
    to the octopus commit."""
    _init_repo(tmp_path)
    _git(['checkout', '-q', '-b', 'b'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: branch b engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/engine.py': 'x = 2\n'},
    )
    _git(['checkout', '-q', '-b', 'c', 'main'], cwd=tmp_path)
    _commit(
        tmp_path,
        'fix: branch c engine tweak\n\nChangelog: none (internal only)\n',
        {'src/convoy/other.py': 'y = 1\n'},
    )
    _git(['checkout', '-q', 'main'], cwd=tmp_path)
    _git(['merge', '--no-ff', '-m', 'Merge branches b and c', 'b', 'c'], cwd=tmp_path)
    assert len(_git(['log', '-1', '--format=%P'], cwd=tmp_path).split()) == 3
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout
