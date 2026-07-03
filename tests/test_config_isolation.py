"""Tests for credential-only ``CLAUDE_CONFIG_DIR`` isolation.

All fakes: a monkeypatched ``Path.home`` and ``tmp_path``-based config dirs. These
tests never read the real ``~/.claude`` and never touch the network.
"""

import shutil
from pathlib import Path

import pytest

from convoy.interface.config_isolation import host_config_dir, isolated_config


def _fake_host(tmp_path: Path, *, credential: str | None) -> Path:
    """A fake host config dir under ``tmp_path``, optionally holding a credential file."""
    cfg = tmp_path / 'host-claude'
    cfg.mkdir()
    if credential is not None:
        (cfg / '.credentials.json').write_text(credential, encoding='utf-8')
    return cfg


def test_copies_credential_when_present(tmp_path: Path) -> None:
    host = _fake_host(tmp_path, credential='{"claudeAiOauth": "tok"}')
    with isolated_config({'CLAUDE_CONFIG_DIR': str(host)}) as cfg:
        assert cfg.credential_copied is True
        copied = (cfg.path / '.credentials.json').read_text(encoding='utf-8')
        assert copied == '{"claudeAiOauth": "tok"}'


def test_isolated_dir_holds_only_the_credential(tmp_path: Path) -> None:
    host = _fake_host(tmp_path, credential='cred')
    # Ambient config that must NOT leak into the isolated dir.
    (host / 'settings.json').write_text('{"hooks": {}}', encoding='utf-8')
    (host / 'CLAUDE.md').write_text('global memory', encoding='utf-8')
    (host / 'plugins').mkdir()
    with isolated_config({'CLAUDE_CONFIG_DIR': str(host)}) as cfg:
        contents = sorted(p.name for p in cfg.path.iterdir())
        assert contents == ['.credentials.json']


def test_empty_dir_when_no_credential(tmp_path: Path) -> None:
    host = _fake_host(tmp_path, credential=None)
    with isolated_config({'CLAUDE_CONFIG_DIR': str(host)}) as cfg:
        assert cfg.credential_copied is False
        assert list(cfg.path.iterdir()) == []


def test_missing_source_dir_is_keychain_path(tmp_path: Path) -> None:
    # Source dir doesn't exist (keychain-backed auth): no copy, empty isolated dir, no error.
    with isolated_config({'CLAUDE_CONFIG_DIR': str(tmp_path / 'nope')}) as cfg:
        assert cfg.credential_copied is False
        assert list(cfg.path.iterdir()) == []


def test_temp_dir_removed_on_normal_exit(tmp_path: Path) -> None:
    host = _fake_host(tmp_path, credential='cred')
    with isolated_config({'CLAUDE_CONFIG_DIR': str(host)}) as cfg:
        path = cfg.path
        assert path.exists()
    assert not path.exists()


def test_temp_dir_removed_on_exception(tmp_path: Path) -> None:
    host = _fake_host(tmp_path, credential='cred')
    path: Path | None = None
    with pytest.raises(RuntimeError), isolated_config({'CLAUDE_CONFIG_DIR': str(host)}) as cfg:
        path = cfg.path
        assert path.exists()
        raise RuntimeError('boom')
    assert path is not None
    assert not path.exists()


def test_isolated_dir_is_outside_a_given_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    host = _fake_host(tmp_path, credential='cred')
    with isolated_config({'CLAUDE_CONFIG_DIR': str(host)}) as cfg:
        assert workspace not in cfg.path.parents
        assert cfg.path != workspace


def test_concurrent_configs_are_distinct(tmp_path: Path) -> None:
    host = _fake_host(tmp_path, credential='cred')
    env = {'CLAUDE_CONFIG_DIR': str(host)}
    with isolated_config(env) as a, isolated_config(env) as b:
        assert a.path != b.path
        assert a.path.exists()
        assert b.path.exists()


def test_host_config_dir_prefers_env(tmp_path: Path) -> None:
    assert (
        host_config_dir({'CLAUDE_CONFIG_DIR': str(tmp_path / 'explicit')}) == tmp_path / 'explicit'
    )


def test_host_config_dir_falls_back_to_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    assert host_config_dir({}) == tmp_path / 'home' / '.claude'
    # An empty override is treated as unset (not a real path), so it also falls back.
    assert host_config_dir({'CLAUDE_CONFIG_DIR': ''}) == tmp_path / 'home' / '.claude'


def test_credential_copy_is_byte_identical(tmp_path: Path) -> None:
    blob = '{"a": "b", "nested": {"x": 1}}\nextra-line'
    host = _fake_host(tmp_path, credential=blob)
    with isolated_config({'CLAUDE_CONFIG_DIR': str(host)}) as cfg:
        assert (cfg.path / '.credentials.json').read_text(encoding='utf-8') == blob


def test_credential_is_unlinked_even_if_dir_removal_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate a failed directory removal (e.g. a held handle): the copied credential must
    # still be gone, so a plaintext token is never left behind under the temp dir.
    monkeypatch.setattr(shutil, 'rmtree', lambda *a, **k: None)
    host = _fake_host(tmp_path, credential='secret-token')
    with isolated_config({'CLAUDE_CONFIG_DIR': str(host)}) as cfg:
        path = cfg.path
        assert (path / '.credentials.json').exists()
    # The dir lingers (rmtree was a no-op) but the credential was unlinked first.
    assert path.exists()
    assert not (path / '.credentials.json').exists()
