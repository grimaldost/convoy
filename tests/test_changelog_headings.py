"""The ``### `` headings of CHANGELOG.md's ``[Unreleased]`` section keep the vocabulary.

This file uses exactly the Keep a Changelog section names. A heading outside them
(``### Documentation``) reached ``main`` once, caught by a merge-conflict resolution and not by
anything mechanical. The record-or-declare and release-heading rules moved to ``railform
changelog-gate`` with the railform adoption; that gate does not read section headings, so this
small check keeps the one rule it has no seat for.

Only ``[Unreleased]`` is read, because it is where a new heading can arrive: the released
sections are history, and a few of them predate the vocabulary.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

VOCABULARY = ('Added', 'Changed', 'Deprecated', 'Removed', 'Fixed', 'Security')


def _unreleased(changelog: str) -> str | None:
    """The body of the ``## [Unreleased]`` section, or ``None`` if the file has none."""
    match = re.search(r'^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)', changelog, re.M | re.S)
    return None if match is None else match.group(1)


def _rogue_headings(section: str) -> list[str]:
    return [
        name.strip()
        for name in re.findall(r'^### (.*)$', section, re.M)
        if name.strip() not in VOCABULARY
    ]


def test_the_unreleased_section_is_found() -> None:
    """Non-vacuity guard: a changed heading style would make the check below read nothing."""
    changelog = (_ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    assert _unreleased(changelog) is not None


def test_unreleased_headings_keep_the_vocabulary() -> None:
    changelog = (_ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    section = _unreleased(changelog)
    assert section is not None  # the guard above owns this failure
    rogue = _rogue_headings(section)
    assert not rogue, (
        f'[Unreleased] has section headings outside {" / ".join(VOCABULARY)}: '
        + ', '.join(f'### {name}' for name in rogue)
    )


def test_a_heading_outside_the_vocabulary_is_caught() -> None:
    """The check can say no: the section below is read the way the real one is."""
    sample = '## [Unreleased]\n\n### Added\n\n- one\n\n### Documentation\n\n- two\n\n## [0.1.0]\n'
    section = _unreleased(sample)
    assert section is not None
    assert _rogue_headings(section) == ['Documentation']
