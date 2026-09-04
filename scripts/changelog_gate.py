"""Fail a pull request that changes the engine without recording the change.

``AGENTS.md`` and ``CONTRIBUTING.md`` mandate docs and CHANGELOG in the same change; until
this gate the rule was prose. Every substantive change of the last build round did carry a
CHANGELOG entry, but nothing mechanical would have failed the one that did not — and by
this repository's own doctrine a rule without an enforcer is a mechanization candidate,
not an aspiration. ``.github/workflows/changelog.yml`` runs this on every pull request.

Three checks and one advisory, all over the merge-base diff:

- **Record or declare.** Judged per commit: a commit whose own diff touches ``src/``
  must have the PR's ``CHANGELOG.md`` diff *add* lines, or that commit carries the
  trailer ``Changelog: none (<reason>)`` — the opt-out for a change nothing a
  changelog reader could notice (comment wording, an internal rename). Touching
  ``CHANGELOG.md`` without adding non-whitespace content does not count — a trailing-
  space edit or an appended blank line is not a record — and a trailer declares only
  the commit it rides on, not the whole range. A merge commit is judged on its own
  resolution diff (``git diff-tree --cc``), not skipped: a conflict resolution that
  edits ``src/`` needs the same recording as any other commit. Granularity has a
  cost of its own: an intermediate commit's engine change that a later commit in the
  same range reverts still needs its own trailer or entry, even though the range's
  final diff never shows it — convoy's own history integrates by merge commit rather
  than squash, so a WIP commit like that stays attributable instead of disappearing.
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

Version = tuple[int, int, int]


def evaluate(
    changed: list[str],
    commits: list[tuple[list[str], str]],
    changelog_added: str,
    base_version: Version | None,
    head_version: Version | None,
) -> tuple[list[str], list[str]]:
    """The whole decision, pure: ``(errors, warnings)`` for one pull request's diff.

    ``changed`` is the merge-base changed-file list, read by the section-heading and
    contract-surface checks below — both judge the PR's final shape, not any one
    commit. ``commits`` is one ``(paths, message)`` pair per commit in the range,
    merges included: ``paths`` that commit's *own* diff (a merge's own resolution
    diff, an ordinary commit's diff against its parent), ``message`` that commit's
    own message — the record-or-declare check needs this per-commit, not range-wide,
    or a trailer on one commit exempts every commit, and a commit's own engine touch
    (a merge's own conflict resolution included) could be missed inside the range's
    aggregate. ``changelog_added`` is the added lines of CHANGELOG.md's diff across
    the whole range (without the ``+`` prefixes) — a shared PR-level record, since
    one entry can cover several commits — and the versions come from
    ``pyproject.toml`` at each end. Whitespace-only content (a trailing-space edit to
    an existing line, or blank lines) does not count as a record: it is stripped
    before the record-or-declare check reads it.
    """
    errors: list[str] = []
    warnings: list[str] = []
    paths = [path.strip().replace('\\', '/') for path in changed if path.strip()]
    recorded = bool(changelog_added.strip())

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


def _git(*args: str) -> str:
    return subprocess.run(
        ['git', *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    ).stdout


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

    commit_shas = _git('log', '--format=%H', f'{merge_base}..HEAD').split()
    commits: list[tuple[list[str], str]] = []
    for sha in commit_shas:
        parents = _git('log', '-1', '--format=%P', sha).split()
        if len(parents) > 1:
            # A merge commit's own diff is its conflict resolution: empty for a clean
            # merge, non-empty exactly when the merge introduced content of its own —
            # `--cc` is what makes that distinction (a plain diff-tree on a merge shows
            # nothing at all, which is not the same claim).
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
    changelog_added = '\n'.join(
        line[1:]
        for line in changelog_diff.splitlines()
        if line.startswith('+') and not line.startswith('+++')
    )

    head_version = _version_of(Path('pyproject.toml').read_text(encoding='utf-8'))
    try:
        base_version = _version_of(_git('show', f'{merge_base}:pyproject.toml'))
    except subprocess.CalledProcessError:  # a history with no pyproject at the base
        base_version = None

    errors, warnings = evaluate(changed, commits, changelog_added, base_version, head_version)
    for warning in warnings:
        print(f'::warning::{warning}')
    for error in errors:
        print(f'::error::{error}')
    if not errors:
        print('OK: the change is recorded, declared, or carries no recording obligation.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
