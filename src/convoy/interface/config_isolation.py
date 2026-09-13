"""Credential-only ``CLAUDE_CONFIG_DIR`` isolation for scored spawns (shell).

A scored ``claude -p`` spawn must not inherit the operator's ambient config — global
settings, hooks, installed plugins, or ``CLAUDE.md`` memory — or the run is neither
reproducible nor comparable across operators (the "credential-only config isolation"
invariant in ``docs/design/00-overview.md`` §5 C5). This module builds a throwaway
config directory holding *only* the authenticating credential (nothing else), so the
spawn authenticates but starts from a clean, standardized config.

``isolated_config`` is a context manager: it creates a temp dir outside any workspace,
copies the credential file when the host keeps auth in a file (subscription/API auth),
yields it, and removes it on exit — including on exception. Keychain-backed auth keeps
nothing under the config dir, so the isolated dir is simply empty and still
authenticates; that case is handled by copying nothing.
"""

import contextlib
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Credential filename(s) the CLI keeps under its config dir. Copying just this file
# (when present) carries the auth token into the isolated dir without any settings,
# hooks, plugins, or memory. The whole file is copied verbatim — convoy does not parse
# or strip it — so any inert cached tokens it also holds travel too, harmlessly.
_CREDENTIAL_BASENAMES: tuple[str, ...] = ('.credentials.json',)


def host_config_dir(environ: Mapping[str, str] | None = None) -> Path:
    """The operator's active config dir: ``$CLAUDE_CONFIG_DIR`` if set, else ``~/.claude``.

    An empty ``CLAUDE_CONFIG_DIR`` is treated as unset (falls back to the home default),
    matching how the CLI itself ignores a blank override.
    """
    env = environ if environ is not None else os.environ
    configured = env.get('CLAUDE_CONFIG_DIR')
    if configured:
        return Path(configured)
    return Path.home() / '.claude'


@dataclass(frozen=True)
class IsolatedConfig:
    """A credential-only config dir: its ``path`` and whether a credential was copied in."""

    path: Path
    credential_copied: bool


def credential_file(config_dir: Path) -> Path | None:
    """The credential file under ``config_dir``, if one is there; ``None`` otherwise.

    ``None`` covers both "keychain-backed auth, which keeps nothing here" and "this
    directory does not exist" — a caller that only wants to know whether a file is
    available to read (the seat probe's pre-spawn credential check, for one) needs
    neither distinguished. Named once here so a reader never re-derives the filename
    this module already knows (``_CREDENTIAL_BASENAMES``).
    """
    for name in _CREDENTIAL_BASENAMES:
        candidate = config_dir / name
        if candidate.is_file():
            return candidate
    return None


def _copy_credential(source_dir: Path, dest_dir: Path) -> bool:
    """Copy the first present credential file from ``source_dir`` into ``dest_dir``.

    Returns ``True`` when a credential file was found and copied, ``False`` when none
    exists (a keychain-backed host keeps no credential file here).
    """
    found = credential_file(source_dir)
    if found is None:
        return False
    shutil.copy2(found, dest_dir / found.name)
    return True


@contextmanager
def isolated_config(environ: Mapping[str, str] | None = None) -> Iterator[IsolatedConfig]:
    """Yield a temp credential-only config dir, removed on exit (incl. on exception).

    Creates a fresh temp dir outside any workspace, copies only the auth credential from
    the host config dir when present, and yields an :class:`IsolatedConfig`. The dir and
    its single credential file are removed when the block exits, whether normally or by
    exception (best-effort ``rmtree``; a lingering OS file lock degrades to a leaked temp
    dir, never a masked error).
    """
    source_dir = host_config_dir(environ)
    temp_dir = Path(tempfile.mkdtemp(prefix='convoy-cfg-'))
    try:
        copied = _copy_credential(source_dir, temp_dir) if source_dir.is_dir() else False
        yield IsolatedConfig(path=temp_dir, credential_copied=copied)
    finally:
        # Remove the copied credential FIRST, so the plaintext token is gone even if the
        # directory removal later fails (e.g. a held handle after a timeout kill); then the dir.
        for name in _CREDENTIAL_BASENAMES:
            with contextlib.suppress(OSError):
                (temp_dir / name).unlink(missing_ok=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
