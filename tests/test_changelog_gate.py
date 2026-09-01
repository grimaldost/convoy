"""Red proofs for ``scripts/changelog_gate.py`` — the check must be able to say no.

The gate's whole decision is the pure ``evaluate``; these tests feed it synthetic diffs
and prove each arm can fail, plus the one non-vacuity guard the advisory arm needs: the
contract-surface list must keep naming files that exist, or a rename silently retires the
warning while the workflow stays green.
"""

import importlib.util
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
    base_version: tuple[int, int, int] | None = (0, 9, 1),
    head_version: tuple[int, int, int] | None = (0, 9, 1),
) -> tuple[list[str], list[str]]:
    return gate.evaluate(changed, messages, changelog_added, base_version, head_version)


# --- record or declare -------------------------------------------------------


def test_an_engine_change_without_a_changelog_entry_fails() -> None:
    """The red proof for the main arm: src/ moved, CHANGELOG.md did not, nothing declared."""
    errors, _ = _evaluate(['src/convoy/interface/git.py', 'tests/test_git.py'])
    assert len(errors) == 1
    assert 'CHANGELOG.md' in errors[0]


def test_an_engine_change_with_a_changelog_entry_passes() -> None:
    errors, _ = _evaluate(['src/convoy/interface/git.py', 'CHANGELOG.md'])
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


def test_a_change_outside_the_engine_carries_no_obligation() -> None:
    errors, warnings = _evaluate(['docs/backlog.md', '.github/workflows/ci.yml'])
    assert errors == []
    assert warnings == []


def test_windows_path_separators_are_normalized() -> None:
    errors, _ = _evaluate(['src\\convoy\\interface\\git.py'])
    assert len(errors) == 1


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
