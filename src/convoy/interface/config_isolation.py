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

The config dir is not the only route for memory. The CLI also reads ``CLAUDE.md``,
``CLAUDE.local.md`` and ``.claude/CLAUDE.md`` in its working directory and in every
directory above it, whatever ``CLAUDE_CONFIG_DIR`` says, so a spawn whose working
directory lies under the operator's home reads the operator's own ``~/.claude/CLAUDE.md``
as an ancestor's memory. ``write_isolation_settings`` writes a settings layer, passed
with ``--settings``, whose ``claudeMdExcludes`` lists those ancestor files.
"""

import contextlib
import hashlib
import json
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

# The instruction files the CLI reads in its working directory and in every directory above
# it, whatever CLAUDE_CONFIG_DIR says.
_MEMORY_FILES: tuple[str, ...] = ('CLAUDE.md', 'CLAUDE.local.md', '.claude/CLAUDE.md')


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


def ancestor_memory_excludes(cwd: Path) -> list[str]:
    """``claudeMdExcludes`` globs for every instruction file above ``cwd``, none in it.

    Absolute, with forward slashes, for each directory above ``cwd`` in each of its
    spellings (as given and resolved: a Windows temporary directory can be an 8.3 short
    path). The working directory's own files are not listed: the repository a spawn works
    on keeps its project instructions.
    """
    folders: list[Path] = []
    candidates = [Path(os.path.abspath(cwd))]
    with contextlib.suppress(OSError):
        candidates.append(Path(cwd).resolve())
    for candidate in candidates:
        folders += [folder for folder in candidate.parents if folder not in folders]
    return [
        f'{folder.as_posix().rstrip("/")}/{name}' for folder in folders for name in _MEMORY_FILES
    ]


def write_isolation_settings(config_dir: Path, cwd: Path) -> Path:
    """Write the settings layer that keeps the instruction files above ``cwd`` out of a spawn
    into ``config_dir``, and return its path for ``--settings``.

    The file is named after ``cwd``: spawns that share one isolated dir but run in
    different worktrees never overwrite each other's layer, and spawns in the same
    worktree find the same bytes already there.
    """
    digest = hashlib.sha256(os.path.abspath(cwd).encode('utf-8')).hexdigest()[:16]
    path = config_dir / f'isolation-{digest}.json'
    body = json.dumps({'claudeMdExcludes': ancestor_memory_excludes(cwd)}, indent=2) + '\n'
    with contextlib.suppress(OSError):
        if path.read_text(encoding='utf-8') == body:
            return path
    staged = path.with_suffix(f'.{os.getpid()}.tmp')
    staged.write_text(body, encoding='utf-8')
    os.replace(staged, path)
    return path


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
