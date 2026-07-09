"""The core/ package is pure: it may not import from convoy.interface.

Guards the functional-core / imperative-shell boundary (docs/GUARDRAILS.md): the
engine's decisions must stay testable without I/O and reusable behind any surface.
"""

import ast
from pathlib import Path

_CORE = Path(__file__).resolve().parent.parent / 'src' / 'convoy' / 'core'
_FORBIDDEN_PREFIX = 'convoy.interface'


def _imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or '')
    return names


def test_core_imports_nothing_from_interface() -> None:
    """Every module under core/ is free of convoy.interface imports."""
    core_files = sorted(_CORE.rglob('*.py'))
    assert core_files, f'no core modules found under {_CORE}'

    offenders = [
        f'{path.relative_to(_CORE)}: {name}'
        for path in core_files
        for name in _imported_names(ast.parse(path.read_text(encoding='utf-8')))
        if name.startswith(_FORBIDDEN_PREFIX)
    ]
    assert offenders == []
