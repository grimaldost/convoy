"""Fail a pull request that changes the engine without recording the change.

``AGENTS.md`` and ``CONTRIBUTING.md`` mandate docs and CHANGELOG in the same change; until
this gate the rule was prose. Every substantive change of the last build round did carry a
CHANGELOG entry, but nothing mechanical would have failed the one that did not — and by
this repository's own doctrine a rule without an enforcer is a mechanization candidate,
not an aspiration. ``.github/workflows/changelog.yml`` runs this on every pull request.

Three checks and one advisory, all over the merge-base diff:

- **Record or declare.** Judged per commit: a commit whose own diff touches ``src/``
  must be recorded by the PR's ``CHANGELOG.md`` diff, or that commit carries the
  trailer ``Changelog: none (<reason>)`` — the opt-out for a change nothing a
  changelog reader could notice (comment wording, an internal rename). Touching
  ``CHANGELOG.md`` is not recording, and neither is rearranging what it already
  said: a record is one added line whose whitespace-collapsed form the same diff
  does not also remove, so an appended blank line, a trailing space or a re-indent
  on an existing line, a CRLF conversion and a reordering of existing bullets all
  record nothing (see ``_records``). A trailer declares only the commit it rides
  on, not the whole range. A merge commit is not skipped, and it is charged only
  with its *resolution* — the content an automatic merge of its parents would not
  have produced (``git merge-tree --write-tree``, diffed against the merge's own
  tree; git 2.38 or newer, and the gate fails naming the git it ran rather than
  guessing on an older one). Unrelated histories are the exception: there is no
  automatic merge to compare against, so the combined diff stands in — a
  conservative approximation that under-charges a resolution taking one root
  verbatim. A hand resolution that edits ``src/`` needs the same
  recording as any other commit; a clean auto-merge, including the synthetic
  ``refs/pull/N/merge`` CI checks out, contributes nothing and is charged nothing.
  An octopus merge is outside ``--write-tree``'s two-parent scope and keeps the
  combined (``--cc``) diff, which OVER-charges: an octopus git merged cleanly is
  charged with the files its branches both touched, though no one authored the
  result. The trailer on the octopus commit is the remedy, and convoy's history
  holds no octopus merge to need it. Granularity
  has a cost of its own: an intermediate commit's engine change that a later commit
  in the same range reverts still needs its own trailer or entry, even though the
  range's final diff never shows it — convoy's own history integrates by merge
  commit rather than squash, so a WIP commit like that stays attributable instead
  of disappearing.
- **A release heading moves the version forward.** When the diff adds a ``## [X.Y.Z]``
  heading, ``pyproject.toml`` at HEAD must carry exactly ``X.Y.Z`` and the merge-base
  version must be smaller. The three version *sites* agreeing is
  ``tests/test_manifest.py::test_versions_are_locked``'s job; this pins the heading to an
  actual bump.
- **Section headings keep the vocabulary.** An added ``### `` heading in ``CHANGELOG.md``
  must be one of Added / Changed / Deprecated / Removed / Fixed / Security. A heading
  outside it reached ``main`` once and was caught by a merge-conflict resolution, not by
  anything mechanical. Only added lines are read, so history is grandfathered.
- **Consumer-affecting marker (advisory).** A diff touching a file that defines a
  contract surface a consumer keys on — see ``CONTRACT_SURFACES`` — should carry the
  literal ``(consumer-affecting)`` somewhere in its CHANGELOG addition. Advisory,
  deliberately: most edits to those files do not move the contract, so this prints a
  workflow warning and never fails the job. Escalate it to an error only once it has
  proven quiet on ordinary pull requests.

Repo-local tooling, deliberately not part of the package: it enforces this repository's
recording discipline, not a consumer's. Stdlib only; ``tests/test_changelog_gate.py``
holds the red proofs.

    python scripts/changelog_gate.py origin/main
"""

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RECORD = 'CHANGELOG.md'

# What ships: the package. A docs-, test-, or workflow-only change carries no obligation.
ENGINE_PREFIXES = ('src/',)

# The files defining the protocol surfaces CHANGELOG.md's own header enumerates — "a new
# process exit code, a new telemetry `outcome` / `error_kind` value, event, or field, or a
# new series.toml key". The header is the definition; this list only locates it in code.
CONTRACT_SURFACES = (
    'src/convoy/core/telemetry.py',  # events, fields, outcome / error_kind values
    'src/convoy/core/spec.py',  # series.toml keys
    'src/convoy/interface/drivers/headless.py',  # the EXIT_* process exit codes
)

MARKER = '(consumer-affecting)'

# The reason is required, not decoration: a bare `Changelog: none` records that the rule
# was skipped, while the parenthesis records why, which is the reviewable part. Casing is
# folded — `changelog: None (...)` states the same decision, and rejecting it over case
# would produce the misleading error, not the safer one.
_TRAILER = re.compile(r'^Changelog: none \(.+\)$', re.MULTILINE | re.IGNORECASE)
_ADDED_HEADING = re.compile(r'^## \[(\d+)\.(\d+)\.(\d+)\]', re.MULTILINE)

# The Keep a Changelog section vocabulary — the only `### ` headings this file uses. A
# heading outside it (`### Documentation`) reached main once, caught by a merge-conflict
# resolution rather than by anything mechanical; content claims were gated while shape was
# prose. Only added lines are read, so history is grandfathered by construction.
SECTION_VOCABULARY = ('Added', 'Changed', 'Deprecated', 'Removed', 'Fixed', 'Security')
_SECTION_HEADING = re.compile(r'^### (.*)$', re.MULTILINE)

# What `git merge-tree --write-tree` prints on its first line when it wrote a tree —
# SHA-1 or SHA-256, so the object id is 40 or 64 hex digits.
_OBJECT_ID = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?')
# The ONE non-tree outcome that is about this merge rather than about this git, and so
# the one that may be answered with the combined diff instead of a failure. Everything
# else raises - see _auto_merge_tree, and note the direction: an unrecognised message
# must fail, never fall back, or the machine that cannot detect the bug is the machine
# that silently keeps it.
#
# Matching the message and not the exit code is deliberate: git 2.38 exits 128 for this,
# for a bad rev, and for a repository it cannot read. Matching a guess at what an OLD git
# says was the round-4 defect: `git merge-tree --write-tree A B` is four arguments, which
# is exactly what pre-2.38 merge-tree expects, so it never prints usage - it reaches
# get_tree_descriptor and dies `unknown rev --write-tree`, which no old-git pattern here
# would have caught. The gate runs merge-tree under LC_ALL=C so this text is the text.
_SAFE_REFUSAL = re.compile(r'refusing to merge unrelated histories', re.I)

Version = tuple[int, int, int]


def evaluate(
    changed: list[str],
    commits: list[tuple[list[str], str]],
    changelog_added: str,
    changelog_removed: str,
    base_version: Version | None,
    head_version: Version | None,
) -> tuple[list[str], list[str]]:
    """The whole decision, pure: ``(errors, warnings)`` for one pull request's diff.

    ``changed`` is the merge-base changed-file list, read by the contract-surface
    advisory alone — it judges the PR's final shape rather than any one commit. (The
    release-heading and section-vocabulary checks read ``changelog_added``; the
    record-or-declare check reads ``commits``.) ``commits`` is one ``(paths,
    message)`` pair per commit in the range, merges included: ``paths`` that commit's
    *own* diff (a merge's own resolution, an ordinary commit's diff against its
    parent), ``message`` that commit's own message — the record-or-declare check
    needs this per-commit, not range-wide, or a trailer on one commit exempts every
    commit, and a commit's own engine touch (a merge's own conflict resolution
    included) could be missed inside the range's aggregate. ``changelog_added`` and
    ``changelog_removed`` are the two sides of CHANGELOG.md's diff across the whole
    range (without the ``+``/``-`` prefixes) — a shared PR-level record, since one
    entry can cover several commits — and the versions come from ``pyproject.toml``
    at each end. Both sides are needed because an added line is a record only if the
    same diff does not also remove it: see ``_records``.
    """
    errors: list[str] = []
    warnings: list[str] = []
    paths = [path.strip().replace('\\', '/') for path in changed if path.strip()]
    recorded = _records(changelog_added, changelog_removed)

    for raw_paths, message in commits:
        commit_paths = [path.strip().replace('\\', '/') for path in raw_paths if path.strip()]
        engine_paths = [path for path in commit_paths if path.startswith(ENGINE_PREFIXES)]
        if engine_paths and not recorded and not _TRAILER.search(message):
            listed = ', '.join(engine_paths[:5]) + (' …' if len(engine_paths) > 5 else '')
            subject = next(iter(message.splitlines()), '(empty message)')
            errors.append(
                f'commit "{subject}" changes the engine ({listed}) without the PR '
                f'adding lines to {RECORD}. Record the change under [Unreleased], or '
                f'declare the exemption on that commit with a trailer: '
                f'Changelog: none (<reason>)'
            )

    headings = _ADDED_HEADING.findall(changelog_added)
    if headings:
        cut = tuple(int(part) for part in headings[0])
        if head_version is not None and cut != head_version:
            errors.append(
                f'the diff adds a release heading [{_dotted(cut)}] but pyproject.toml is at '
                f'{_dotted(head_version)}; the heading and the version sites must move together'
            )
        if base_version is not None and cut <= base_version:
            errors.append(
                f'the diff adds a release heading [{_dotted(cut)}] that does not move the '
                f'version forward from {_dotted(base_version)}'
            )

    rogue = [
        name.strip()
        for name in _SECTION_HEADING.findall(changelog_added)
        if name.strip() not in SECTION_VOCABULARY
    ]
    if rogue:
        listed = ', '.join(f'### {name}' for name in rogue)
        errors.append(
            f'the diff adds a CHANGELOG section heading outside the vocabulary ({listed}); '
            f'this file uses exactly Added / Changed / Deprecated / Removed / Fixed / '
            f'Security'
        )

    touched_surfaces = [path for path in paths if path in CONTRACT_SURFACES]
    if touched_surfaces and MARKER not in changelog_added:
        warnings.append(
            f'the diff touches a contract surface ({", ".join(touched_surfaces)}) and its '
            f'CHANGELOG addition never says {MARKER}. If the change adds an exit code, a '
            f'telemetry event/field/value, or a series.toml key, mark the entry; if not, '
            f'ignore this — it is advisory while it earns (or loses) its escalation.'
        )

    return errors, warnings


def _dotted(version: Version) -> str:
    return '.'.join(str(part) for part in version)


def _collapsed(blob: str) -> list[str]:
    """Each line with every run of whitespace collapsed to one space and the ends
    trimmed, so a re-indent, a trailing space and a ``\\r`` line terminator all fold
    onto the same form as the line they churn."""
    return [' '.join(line.split()) for line in blob.splitlines()]


def _records(added: str, removed: str) -> bool:
    """Whether a CHANGELOG diff records anything.

    A record is one added line that is non-blank once collapsed *and* that the same
    diff does not also remove in collapsed form. Stripping the added blob alone is not
    enough: a trailing space on an existing line adds a line that survives ``strip()``
    while telling a changelog reader nothing it could not already read. Reordering,
    re-indenting and converting the file's line endings are the same shape.
    """
    gone = set(_collapsed(removed))
    return any(line and line not in gone for line in _collapsed(added))


def _git(*args: str) -> str:
    return subprocess.run(
        ['git', *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    ).stdout


def _auto_merge_tree(written: subprocess.CompletedProcess[str], git_version: str) -> str | None:
    """The tree id ``git merge-tree --write-tree`` wrote, ``None`` if there is no
    automatic merge to compare against, or a loud failure if this git cannot compute one.

    Three outcomes, and the difference between the last two is the whole point:

    Exit 1 is a *conflicted* automatic merge, not an error: merge-tree still writes a
    tree — the conflict markers are in it — and that tree is exactly what tells a hand
    resolution from an automatic one, so it is used like any other.

    ``refusing to merge unrelated histories`` is a property of the *merge*, and it is
    not an error at all: there is no automatic merge of unrelated histories, so there is
    nothing to diff the result against. ``None`` says that, and the caller falls back to
    the combined diff. That fallback is a conservative approximation and not an
    equivalent reading: ``-c`` lists what differs from *every* parent, so a resolution
    that takes one root's file verbatim matches that root and goes uncharged, where
    the module's own rule ("no automatic merge, so all of it is authored") would charge
    it. Accepted because the alternative — charging both roots entire — is worse, and
    because the trailer remains available on the merge.

    Anything else raises, naming the git it ran under, and the job says why. That
    includes a git too old for ``--write-tree``, which is a property of the *machine* and
    holds for every merge in the range: falling back there would restore the bug this
    replaces on exactly the machines that cannot detect it. The classification is by the
    message and in this direction on purpose. Round 4 had it the other way, keying on a
    guess at what an old git prints, and the guess was wrong: ``merge-tree --write-tree A
    B`` is the four arguments pre-2.38 merge-tree expects, so it never prints usage — it
    dies ``unknown rev --write-tree``, matched nothing, and fell through to the silent
    fallback. An unrecognised message now fails loudly instead.
    """
    first = next(iter(written.stdout.splitlines()), '').strip()
    if _OBJECT_ID.fullmatch(first):
        return first
    said = written.stderr.strip() or written.stdout.strip() or '(no output)'
    if _SAFE_REFUSAL.search(said):
        return None
    headline = next(iter(said.splitlines()), said)
    raise RuntimeError(
        f'git merge-tree --write-tree wrote no tree (exit {written.returncode}) under '
        f'{git_version.strip()}, and did not refuse for a reason this gate can read as '
        f'a fact about the merge. Charging a merge commit with its resolution needs git '
        f'2.38 or newer. It said: {headline}'
    )


def _diff_side(diff: str, sign: str) -> str:
    """One side of a unified diff without its prefixes: ``+`` for the added lines,
    ``-`` for the removed, each skipping that side's ``+++``/``---`` file header."""
    header = sign * 3
    return '\n'.join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith(sign) and not line.startswith(header)
    )


def _version_of(pyproject: str) -> Version | None:
    raw = tomllib.loads(pyproject)['project']['version']
    parts = raw.split('.')
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    major, minor, patch = (int(part) for part in parts)
    return (major, minor, patch)


def main(argv: list[str]) -> int:
    base_ref = argv[0] if argv else 'origin/main'
    merge_base = _git('merge-base', base_ref, 'HEAD').strip()

    changed = _git('diff', '--name-only', f'{merge_base}..HEAD').splitlines()

    git_version = _git('--version')
    commit_shas = _git('log', '--format=%H', f'{merge_base}..HEAD').split()
    commits: list[tuple[list[str], str]] = []
    for sha in commit_shas:
        parents = _git('log', '-1', '--format=%P', sha).split()
        if len(parents) == 2:
            # A merge's own contribution is its resolution: what an automatic merge of
            # its parents would *not* have produced. `git merge-tree --write-tree` writes
            # that automatic merge (conflict markers included) and prints its tree, so
            # diffing that tree against the merge's own tree leaves exactly the content a
            # human put there. `--cc --name-only` cannot make this distinction — in
            # name-only mode `--cc` is `-c`, which lists every file whose result differs
            # from all parents, and a clean auto-merge of two hunks in one file differs
            # from both. That charged content nobody authored, most damagingly on the
            # synthetic refs/pull/N/merge CI checks out: once the base branch touched the
            # same engine file, the pull request failed with no remedy its author could
            # apply, since no trailer can be put on a commit GitHub generates.
            written = subprocess.run(
                ['git', 'merge-tree', '--write-tree', parents[0], parents[1]],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                # _SAFE_REFUSAL reads git's own words, so they must not be localized.
                env={**os.environ, 'LC_ALL': 'C'},
            )
            auto = _auto_merge_tree(written, git_version)
            if auto is None:
                # git refused this pair outright (unrelated histories), so there is no
                # automatic merge to diff against. The combined diff is the conservative
                # approximation left: it under-charges a resolution that takes one root's
                # file verbatim, and the trailer stays available for the rest.
                own_paths = _git(
                    'diff-tree', '--cc', '--no-commit-id', '--name-only', '-r', sha
                ).splitlines()
            else:
                own_paths = _git(
                    'diff-tree', '--no-commit-id', '--name-only', '-r', auto, sha
                ).splitlines()
        elif len(parents) > 2:
            # An octopus is outside `--write-tree`'s two-parent scope (and reducing it to
            # its first two parents would charge it the other branches' content), so it
            # keeps the combined diff. This OVER-charges and the docstring says so: `-c`
            # lists files differing from every parent, which for a clean automatic
            # octopus over two hunks of one file is still nobody's authorship. Left as
            # the conservative reading because a wrong charge has a remedy the author can
            # apply (the trailer) and a missed one does not, and because this repository
            # has never made an octopus merge.
            own_paths = _git(
                'diff-tree', '--cc', '--no-commit-id', '--name-only', '-r', sha
            ).splitlines()
        else:
            own_paths = _git(
                'diff-tree', '--no-commit-id', '--name-only', '-r', '--root', sha
            ).splitlines()
        own_message = _git('log', '-1', '--format=%B', sha)
        commits.append((own_paths, own_message))

    changelog_diff = _git('diff', f'{merge_base}..HEAD', '--', RECORD)
    changelog_added = _diff_side(changelog_diff, '+')
    changelog_removed = _diff_side(changelog_diff, '-')

    head_version = _version_of(Path('pyproject.toml').read_text(encoding='utf-8'))
    try:
        base_version = _version_of(_git('show', f'{merge_base}:pyproject.toml'))
    except subprocess.CalledProcessError:  # a history with no pyproject at the base
        base_version = None

    errors, warnings = evaluate(
        changed, commits, changelog_added, changelog_removed, base_version, head_version
    )
    for warning in warnings:
        print(f'::warning::{warning}')
    for error in errors:
        print(f'::error::{error}')
    if not errors:
        print('OK: the change is recorded, declared, or carries no recording obligation.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
