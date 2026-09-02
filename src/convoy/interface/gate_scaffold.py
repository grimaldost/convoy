"""Scaffold a per-project gate spec (shell): ``convoy gate --init``.

Writes ``.convoy/gate.toml`` — the gate-only file shape — from the toolchain found in the
project, as blocking, non-independent checks: the project's own suite. That is the
default gate, and it is exactly what an implementer can satisfy by self-report, so the
file's header says what it is and names the next step: the held-out oracles a project
keeps under ``CONVOY_ORACLES`` and declares with ``--independent NAME``. The oracle this
module scaffolds is a placeholder that stays red until written — the judge is appointed
before the defendant, and a gate that has not been written yet says so instead of
passing.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from convoy.core.spec import DEFAULT_GATE_TIMEOUT_SECONDS, Check, GateSpec, dump_gate_spec
from convoy.interface.gate_service import GATE_SPEC_RELPATH, ORACLES_ENV, oracles_dir_for
from convoy.interface.proc import TEXT_ENCODING, TEXT_ERRORS


class GateScaffoldError(RuntimeError):
    """``convoy gate --init`` could not scaffold (a target path exists, or a name is invalid)."""


@dataclass(frozen=True)
class Toolchain:
    """What ``--init`` found: a label for the header and the checks it implies."""

    label: str
    checks: tuple[Check, ...]


# The check written when nothing is detected: red until the author declares the project's
# checks, because a scaffold that passed vacuously would arm a hook that assures nothing.
_PLACEHOLDER = Check(
    name='configure',
    run='exit 1',
    blocking=True,
    independent=False,
    repair_hint=(
        "no toolchain was detected; declare this project's checks in .convoy/gate.toml "
        '(the gate stays red until you do)'
    ),
)

_ORACLE_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_-]*$')

_ORACLE_TEMPLATE = '''"""Held-out oracle `{name}` for {project}.

Runs with the scored workspace as its working directory, out of the implementer's reach.
Exit 0 when the work passes, non-zero with a message on stderr when it does not. Write the
assertion the implementer must not see here, BEFORE dispatching the implementer.
"""

import sys

sys.stderr.write('oracle {name} is not written yet\\n')
sys.exit(1)
'''


def _mentions(text: str, tool: str) -> bool:
    """Whether *tool* appears in a pyproject as a word — ``ty`` must not match ``pytest``."""
    return re.search(rf'(?<![A-Za-z0-9_-]){re.escape(tool)}(?![A-Za-z0-9_-])', text) is not None


def _python_checks(root: Path, pyproject: Path) -> tuple[Check, ...]:
    text = pyproject.read_text(encoding=TEXT_ENCODING, errors=TEXT_ERRORS)
    uv = (root / 'uv.lock').is_file()
    prefix = 'uv run ' if uv else ''
    checks: list[Check] = []
    if uv:
        checks.append(
            Check(
                name='lock',
                run='uv lock --check',
                blocking=True,
                independent=False,
                repair_hint='run `uv lock` and commit the lockfile',
            )
        )
    ruff = (
        _mentions(text, 'ruff') or (root / 'ruff.toml').is_file() or (root / '.ruff.toml').is_file()
    )
    if ruff:
        checks.append(
            Check(
                name='lint',
                run=f'{prefix}ruff check .',
                blocking=True,
                independent=False,
                repair_hint=(
                    'fix the reported lint, or run `ruff check --fix .` and review the diff'
                ),
            )
        )
        checks.append(
            Check(
                name='format',
                run=f'{prefix}ruff format --check .',
                blocking=True,
                independent=False,
                repair_hint='run `ruff format .`',
            )
        )
    if _mentions(text, 'mypy') or (root / 'mypy.ini').is_file():
        checks.append(Check(name='types', run=f'{prefix}mypy .', blocking=True, independent=False))
    elif _mentions(text, 'ty'):
        checks.append(
            Check(name='types', run=f'{prefix}ty check', blocking=True, independent=False)
        )
    if (root / 'tests').is_dir() or _mentions(text, 'pytest'):
        checks.append(
            Check(
                name='tests',
                run=f'{prefix}pytest -q',
                blocking=True,
                independent=False,
                repair_hint='make the failing tests pass without weakening them',
            )
        )
    return tuple(checks) if checks else (_PLACEHOLDER,)


def _node_checks(package: Path) -> tuple[Check, ...]:
    try:
        data = json.loads(package.read_text(encoding='utf-8'))
    except OSError, ValueError:
        return ()
    scripts = data.get('scripts') if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return ()
    checks: list[Check] = []
    for script, name in (('lint', 'lint'), ('typecheck', 'types'), ('test', 'tests')):
        if script in scripts:
            checks.append(
                Check(name=name, run=f'npm run {script}', blocking=True, independent=False)
            )
    return tuple(checks)


def detect_toolchain(root: Path) -> Toolchain:
    """The project's toolchain and the default gate it implies.

    Python (``pyproject.toml``): the lockfile check when ``uv.lock`` exists, ruff lint and
    format when ruff is configured, the type checker the pyproject names (mypy, else ty),
    and pytest when a ``tests/`` directory or a pytest mention exists — under ``uv run``
    when the project is uv-managed. Node (``package.json``): the ``lint``, ``typecheck``
    and ``test`` scripts that exist. Anything else, or a toolchain with nothing to run:
    the ``configure`` placeholder, red until the author declares the checks.
    """
    pyproject = root / 'pyproject.toml'
    if pyproject.is_file():
        return Toolchain('python', _python_checks(root, pyproject))
    package = root / 'package.json'
    if package.is_file():
        checks = _node_checks(package)
        if checks:
            return Toolchain('node', checks)
    return Toolchain('none', (_PLACEHOLDER,))


def _header(root: Path, toolchain: Toolchain, oracle_path: Path | None) -> str:
    found = (
        'no toolchain detected'
        if toolchain.label == 'none'
        else f'{toolchain.label} toolchain detected'
    )
    lines = [
        f'# convoy gate for {root.name} — scaffolded by `convoy gate --init` ({found}).',
        '# Run it with `convoy gate` from anywhere in the project (no argument needed); the',
        '# plugin hook runs it after every subagent dispatch once this file exists.',
        '#',
        "# The checks below are the project's own suite: blocking, non-independent. They",
        '# catch regressions; they are also exactly what an implementer can satisfy by',
        '# self-report. The class of defect the gate exists for needs an INDEPENDENT check —',
        '# a held-out oracle the implementer cannot reach, written by the spec author before',
        '# any implementer is dispatched. `convoy gate --init --independent <name>` scaffolds',
        f'# one under CONVOY_ORACLES (default ~/.convoy/oracles/{root.name}/); it stays red',
        '# until written. The hook runs this file only where `convoy gate --init` or',
        '# `convoy gate --trust` recorded the project in ~/.convoy/hook-trust.toml.',
    ]
    if oracle_path is not None:
        lines.append(f'# Independent oracle scaffolded at: {oracle_path}')
    return '\n'.join(lines) + '\n\n'


def _oracle_name(name: str) -> str:
    if not _ORACLE_NAME.match(name):
        raise GateScaffoldError(
            f'invalid oracle name {name!r}: use letters, digits, underscore and hyphen, '
            f'starting with a letter or underscore'
        )
    return name


def scaffold_gate(
    root: Path,
    env: Mapping[str, str],
    *,
    independent: str | None = None,
) -> list[Path]:
    """Write the project gate spec under *root* and return the paths created.

    ``.convoy/gate.toml`` from :func:`detect_toolchain`, plus ``.convoy/.gitignore``
    (ignoring the hook's ``hook.log``) when none exists. With *independent*, also a
    placeholder oracle ``<name>.py`` under the project's oracles directory
    (``CONVOY_ORACLES`` from *env*, else the default) and a blocking independent check
    naming it through ``${CONVOY_ORACLES}``, so the spec stays portable. Refuses to
    overwrite any target, before writing anything. Trusting the project for the hook is
    the caller's step (``convoy gate --init`` does it): the scaffold only writes files.
    """
    root = Path(root).resolve()
    spec_path = root / GATE_SPEC_RELPATH
    ignore_path = spec_path.parent / '.gitignore'
    toolchain = detect_toolchain(root)
    checks = list(toolchain.checks)
    targets = [spec_path]
    oracle_path: Path | None = None
    if independent is not None:
        name = _oracle_name(independent)
        oracle_path = oracles_dir_for(root, env) / f'{name}.py'
        targets.append(oracle_path)
        reference = f'${{{ORACLES_ENV}}}/{name}.py'
        checks.append(
            Check(
                name=name,
                run=f'python "{reference}"',
                blocking=True,
                independent=True,
                asset=reference,
                repair_hint=f'(edit me) what a red {name} means, and how to repair it',
            )
        )
    for path in targets:
        if path.exists():
            raise GateScaffoldError(f'refusing to overwrite existing path: {path}')

    spec = GateSpec(
        id=root.name, checks=tuple(checks), timeout_seconds=DEFAULT_GATE_TIMEOUT_SECONDS
    )
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        _header(root, toolchain, oracle_path) + dump_gate_spec(spec), encoding='utf-8'
    )
    written = [spec_path]
    if not ignore_path.exists():
        ignore_path.write_text('hook.log\n', encoding='utf-8')
        written.append(ignore_path)
    if oracle_path is not None:
        oracle_path.parent.mkdir(parents=True, exist_ok=True)
        oracle_path.write_text(
            _ORACLE_TEMPLATE.format(name=oracle_path.stem, project=root.name), encoding='utf-8'
        )
        written.append(oracle_path)
    return written
