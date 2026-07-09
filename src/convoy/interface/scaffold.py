"""Scaffold a runnable starter convoy series (shell).

``convoy init <dir>`` writes a small, self-contained example a user can run immediately: a
``series.toml``, a prompt, and an out-of-tree oracle for a blocking *independent* check
(demonstrating the ``asset`` field), plus a git-initialized ``workspace/`` staged on the
base branch. The scored workspace is that ``workspace/`` subdir, so the oracle and the
telemetry outputs live out-of-tree — the layout a real independent-check series needs.
"""

import subprocess
from pathlib import Path

from convoy.core.spec import (
    PR,
    Branches,
    Budgets,
    Check,
    Governance,
    Paths,
    Review,
    Series,
    Tools,
    dump_series,
)
from convoy.interface.proc import GIT_HERMETIC_FLAGS, TEXT_ENCODING, TEXT_ERRORS


class ScaffoldError(RuntimeError):
    """``convoy init`` could not scaffold (e.g. a target path already exists, or git failed)."""


_HEADER = (
    '# convoy starter series. From the scored workspace, run:\n'
    '#   cd workspace && convoy run ../series.toml\n\n'
)

_PROMPT_TEXT = """\
Create a file named `greeting.txt` in the repository root containing exactly one line:

hello convoy

Do not create or modify any other files.
"""

_ORACLE_TEXT = """\
import pathlib
import sys

# An out-of-tree independent oracle: it verifies the PR's result but lives outside the
# scored workspace, so the implementing agent cannot reach or edit it. It runs with the
# workspace as its working directory, so it reads the produced file by relative path.
greeting = pathlib.Path('greeting.txt')
ok = greeting.is_file() and 'hello convoy' in greeting.read_text(encoding='utf-8')
sys.exit(0 if ok else 1)
"""


def build_starter_series(root: Path) -> Series:
    """The starter :class:`Series` for ``convoy init``, with absolute paths under ``root``.

    Every budget is positive and every tool role is populated, and the single check is a
    blocking independent check whose ``asset`` is the out-of-tree oracle — so the emitted
    ``series.toml`` is a correct, copyable exemplar of the independent-check lane.
    """
    root = root.resolve()
    oracle = (root / 'oracles' / 'greeting_check.py').as_posix()
    return Series(
        id='starter',
        version='1',
        branches=Branches(base='base', integration='integration'),
        paths=Paths(prompts=(root / 'prompts').as_posix(), outputs=(root / 'outputs').as_posix()),
        governance=Governance(
            effort='low',
            permission_mode='acceptEdits',
            timeout_seconds=1800,
            budgets=Budgets(implementation=1.0, review=0.5, fix=0.5),
            tools=Tools(
                implementation=('Read', 'Edit', 'Write', 'Bash'),
                review=('Read', 'Grep', 'Glob'),
                fix=('Read', 'Edit', 'Write', 'Bash'),
            ),
            model='claude-haiku-4-5',
        ),
        review=Review(blocking=False, max_fix_attempts=1),
        checks=(
            Check(
                name='greeting',
                run=f'python "{oracle}"',
                blocking=True,
                independent=True,
                asset=oracle,
            ),
        ),
        prs=(PR(id='pr-1', branch='pr-1', prompt='implement.md', phase='core'),),
    )


def _git(workspace: Path, *args: str) -> None:
    result = subprocess.run(
        ['git', *GIT_HERMETIC_FLAGS, *args],
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding=TEXT_ENCODING,
        errors=TEXT_ERRORS,
    )
    if result.returncode != 0:
        raise ScaffoldError(f'git {" ".join(args)} failed: {result.stderr.strip()}')


def _init_workspace(workspace: Path) -> None:
    """Create ``workspace`` as a git repo on the base branch with one seed commit."""
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / 'README.md').write_text('# starter workspace\n', encoding='utf-8')
    _git(workspace, 'init', '-b', 'base')
    _git(workspace, 'config', 'user.email', 'convoy@example.invalid')
    _git(workspace, 'config', 'user.name', 'convoy')
    _git(workspace, 'add', '-A')
    _git(workspace, 'commit', '-m', 'seed')


def scaffold(root: Path) -> list[Path]:
    """Write the starter series under ``root`` and return the paths created.

    Refuses to overwrite: if the series file, the prompt, the oracle, or the workspace
    already exists, raises :class:`ScaffoldError` before writing anything (no partial
    scaffold). On success the workspace is a committed git repo on the base branch.
    """
    root = Path(root)
    series_file = root / 'series.toml'
    prompt_file = root / 'prompts' / 'implement.md'
    oracle_file = root / 'oracles' / 'greeting_check.py'
    workspace = root / 'workspace'

    for path in (series_file, prompt_file, oracle_file, workspace):
        if path.exists():
            raise ScaffoldError(f'refusing to overwrite existing path: {path}')

    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    oracle_file.parent.mkdir(parents=True, exist_ok=True)
    (root / 'outputs').mkdir(parents=True, exist_ok=True)

    prompt_file.write_text(_PROMPT_TEXT, encoding='utf-8')
    oracle_file.write_text(_ORACLE_TEXT, encoding='utf-8')
    series_file.write_text(_HEADER + dump_series(build_starter_series(root)), encoding='utf-8')
    _init_workspace(workspace)

    return [series_file, prompt_file, oracle_file, workspace]
