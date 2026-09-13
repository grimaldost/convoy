"""The plugin manifests declare the server correctly and stay version-locked.

Guards the "manifest declares the server with a ``${CLAUDE_PLUGIN_ROOT}`` anchor and an
in-process module launch" and "versions in lockstep" requirements.
"""

import json
import re
import tomllib
from pathlib import Path

import convoy

_ROOT = Path(__file__).resolve().parent.parent
_SKILL_MD = _ROOT / 'skills' / 'convoy' / 'SKILL.md'

# The one sentence SKILL.md states its own version in — a session driving the skill can
# then read its served version from the skill body itself, without walking a plugin cache.
_SKILL_VERSION = re.compile(r'This document describes convoy `(\d+\.\d+\.\d+)`')


def _plugin() -> dict:
    return json.loads((_ROOT / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))


def test_plugin_declares_server_with_plugin_root_anchor_and_module_launch() -> None:
    server = _plugin()['mcpServers']['convoy']
    assert server['command'] == 'uv'
    args = server['args']
    assert '${CLAUDE_PLUGIN_ROOT}' in args  # cwd-independent launch
    # In-process module launch, never a PATH-dependent shim.
    assert args[-3:] == ['python', '-m', 'convoy.interface.mcp']


def test_plugin_has_an_author() -> None:
    # A missing author is the common `claude plugin validate` warning.
    assert _plugin()['author']['name'].strip()


def test_versions_are_locked() -> None:
    """The four hand-edited version sites agree.

    Three are structured fields (``plugin.json``, ``pyproject.toml``, ``__version__``);
    the fourth is the sentence ``skills/convoy/SKILL.md`` states its own version in — a
    session reading the skill can then name the version it was served without walking a
    plugin cache, which is exactly the gap that produced a CRITICAL report against an
    already-shipped primitive (a session served 0.9.0 while 0.9.1 and 0.11.0 sat in cache).

    ``uv.lock`` is a fifth place the version lives — it recorded ``0.1.1`` through the
    whole of ``0.2.0`` — but it is deliberately NOT asserted here. ``uv run`` re-locks
    before it runs anything, so by the time pytest reads that file it has already been
    repaired: an assertion here could never go red, which is worse than no assertion at
    all. ``uv lock --check`` is the mechanism that catches it, and CI runs it ahead of
    every step that would rewrite the lock.
    """
    plugin_version = _plugin()['version']
    pyproject = tomllib.loads((_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    skill_match = _SKILL_VERSION.search(_SKILL_MD.read_text(encoding='utf-8'))
    assert skill_match is not None, 'SKILL.md does not state its own version'
    assert (
        plugin_version
        == pyproject['project']['version']
        == convoy.__version__
        == skill_match.group(1)
    )


def test_marketplace_lists_the_convoy_plugin_from_this_repo() -> None:
    marketplace = json.loads(
        (_ROOT / '.claude-plugin' / 'marketplace.json').read_text(encoding='utf-8')
    )
    plugins = marketplace['plugins']
    assert any(p['name'] == 'convoy' for p in plugins)
    assert plugins[0]['source'] == '.'  # the repo is its own plugin
