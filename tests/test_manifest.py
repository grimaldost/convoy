"""The plugin manifests declare the server correctly and stay version-locked.

Guards the "manifest declares the server with a ``${CLAUDE_PLUGIN_ROOT}`` anchor and an
in-process module launch" and "versions in lockstep" requirements.
"""

import json
import tomllib
from pathlib import Path

import convoy

_ROOT = Path(__file__).resolve().parent.parent


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
    plugin_version = _plugin()['version']
    pyproject = tomllib.loads((_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert plugin_version == pyproject['project']['version'] == convoy.__version__


def test_marketplace_lists_the_convoy_plugin_from_this_repo() -> None:
    marketplace = json.loads(
        (_ROOT / '.claude-plugin' / 'marketplace.json').read_text(encoding='utf-8')
    )
    plugins = marketplace['plugins']
    assert any(p['name'] == 'convoy' for p in plugins)
    assert plugins[0]['source'] == '.'  # the repo is its own plugin
