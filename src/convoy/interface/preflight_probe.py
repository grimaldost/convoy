"""Filesystem pre-flight probes (shell): the pre-run checks that must touch disk.

Composes the pure ``core.preflight.structural_problems`` with filesystem checks — each
PR's prompt file exists, ``[paths]`` are usable and out-of-tree, and every blocking
independent check's asset is isolated (reusing ``fs_probe.isolation_result``) — into one
list of :class:`~convoy.core.preflight.Problem`. Used by ``convoy validate`` and by
``convoy run`` before any git mutation, so a misconfigured series fails fast and whole
rather than half-executing and leaving a partially-branched tree behind.

The result is a :class:`~convoy.core.preflight.PreflightReport`: the blocking problems that
decide runnability, plus the non-blocking advisories that do not.
"""

import hashlib
from pathlib import Path

from convoy.core.preflight import (
    Advisory,
    PreflightReport,
    Problem,
    inert_assets,
    structural_problems,
    ungated_prs,
)
from convoy.core.spec import Series
from convoy.interface.fs_probe import isolation_result


def check_prompts(series: Series) -> list[Problem]:
    """A Problem when the prompts dir is missing, or a PR's prompt file is not found."""
    prompts_dir = Path(series.paths.prompts)
    if not prompts_dir.is_dir():
        return [
            Problem(
                kind='paths', where='[paths]', message=f'prompts dir does not exist: {prompts_dir}'
            )
        ]
    problems: list[Problem] = []
    for pr in series.prs:
        prompt_path = prompts_dir / pr.prompt
        if not prompt_path.is_file():
            problems.append(
                Problem(
                    kind='prompt',
                    where=f'[[prs]] {pr.id!r}',
                    message=f'prompt file not found: {prompt_path}',
                )
            )
    return problems


def check_outputs(series: Series, workspace: Path) -> list[Problem]:
    """A Problem when outputs is a non-directory, or resolves inside the scored workspace.

    Telemetry (``spawns.jsonl``) is appended throughout a run, including between a PR's
    commit and the next checkout. If outputs lives inside the workspace those writes dirty
    the git tree and abort the checkout, so outputs must be out-of-tree. A missing outputs
    dir is fine — ``convoy run`` creates it.
    """
    outputs = Path(series.paths.outputs)
    problems: list[Problem] = []
    if outputs.exists() and not outputs.is_dir():
        problems.append(
            Problem(
                kind='paths', where='[paths]', message=f'outputs path is not a directory: {outputs}'
            )
        )
    workspace_resolved = workspace.resolve()
    outputs_resolved = outputs.resolve()
    if outputs_resolved == workspace_resolved or workspace_resolved in outputs_resolved.parents:
        problems.append(
            Problem(
                kind='paths',
                where='[paths]',
                message=(
                    f'outputs dir is inside the scored workspace ({outputs}); '
                    'place it out-of-tree so telemetry writes never dirty the git tree'
                ),
            )
        )
    return problems


# The filename globs test runners use for their OWN default discovery — pytest, go test,
# jest/vitest, rspec. They are not convoy's guess at what a test looks like: a file matching
# one of them is a test file by the toolchain's own rule, which is what keeps this a
# comparison rather than a heuristic.
_TEST_FILE_GLOBS = (
    'test_*.py',
    '*_test.py',
    '*_test.go',
    '*.test.js',
    '*.test.jsx',
    '*.test.ts',
    '*.test.tsx',
    '*.spec.js',
    '*.spec.ts',
    '*_spec.rb',
)

# Directory names whose contents belong to somebody else — vendored packages, virtualenvs,
# build output, caches. A test file in there is not the repository's test surface, and
# walking them is slow enough to matter on a large tree.
_UNSEARCHED_DIRS = frozenset(
    {
        '.git',
        '.venv',
        'venv',
        'node_modules',
        '__pycache__',
        '.tox',
        '.nox',
        '.mypy_cache',
        '.pytest_cache',
        '.ruff_cache',
        'dist',
        'build',
        'target',
        'vendor',
    }
)

# How many uncovered files to name before falling back to the count alone.
_NAMED_EXAMPLES = 3


def _declared_paths(command: str, workspace: Path) -> tuple[list[Path], bool]:
    """The in-tree paths ``command`` names, and whether it names any existing path at all.

    A token is a declared path when it resolves to something that exists — nothing is
    guessed from shape, so a flag, a module name or a stray word is simply not a path. The
    second value distinguishes the two ways a check can name no in-tree path, which mean
    opposite things: a command naming **no existing path anywhere** runs whatever its tool
    discovers by default, i.e. the whole tree; a command naming only paths *outside* the
    workspace is an out-of-tree oracle and says nothing about in-tree coverage.
    """
    workspace = workspace.resolve()
    in_tree: list[Path] = []
    names_any_path = False
    for raw in command.split():
        token = raw.strip('"\'')
        if not token or token.startswith('-'):
            continue
        candidate = Path(token)
        resolved = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate
        if not resolved.exists():
            continue
        names_any_path = True
        if resolved == workspace or workspace in resolved.parents:
            in_tree.append(resolved)
    return in_tree, names_any_path


def _test_files(workspace: Path) -> list[Path]:
    """Every test file in ``workspace``, by the runners' own discovery globs."""
    found: list[Path] = []
    for glob in _TEST_FILE_GLOBS:
        for path in workspace.rglob(glob):
            if any(part in _UNSEARCHED_DIRS for part in path.relative_to(workspace).parts):
                continue
            if path.is_file():
                found.append(path.resolve())
    return sorted(set(found))


def gate_scope(series: Series, workspace: Path) -> list[Advisory]:
    """An Advisory naming the test files the blocking gate will not run.

    Phase scoping made subset gates possible, and a subset gate fails in two opposite ways.
    This one is the quiet half: a subtree-scoped suite cannot see the repository-wide guards
    a PR mutates, so a 16-PR wave gated 16/16 green while two of them were red — found only
    by running the full suite by hand after the run reported ``completed``. The series' own
    quality claim was stronger than the tree warranted, and nothing said so.

    Answerable for free, because convoy already holds both the gate commands and the
    workspace. Unlike a path detector this needs no heuristic and has no false-positive
    budget: it compares the paths a command **names** against the files the test runners'
    own discovery globs **find**.

    Silent whenever the answer would be a guess. Only blocking checks are considered, since
    only they can stop a merge. If any of them names no existing path at all, it runs
    whatever its tool discovers — the whole tree — and there is nothing the gate misses. A
    check naming only out-of-tree paths (an independent oracle) neither scopes the tree nor
    covers it, so it is passed over rather than treated as either.
    """
    blocking = [check for check in series.checks if check.blocking]
    scoped: list[Path] = []
    for check in blocking:
        in_tree, names_any_path = _declared_paths(check.run, workspace)
        if not names_any_path:
            return []  # this check runs the whole tree
        scoped.extend(in_tree)
    if not scoped:
        return []
    uncovered = [
        path
        for path in _test_files(workspace)
        if not any(path == root or root in path.parents for root in scoped)
    ]
    if not uncovered:
        return []
    shown = ', '.join(
        str(path.relative_to(workspace.resolve())) for path in uncovered[:_NAMED_EXAMPLES]
    )
    more = (
        f' and {len(uncovered) - _NAMED_EXAMPLES} more' if len(uncovered) > _NAMED_EXAMPLES else ''
    )
    return [
        Advisory(
            kind='gate',
            where='[[checks]]',
            message=(
                f'the blocking gate does not run {len(uncovered)} test file(s) present in the '
                f'workspace ({shown}{more}), so a green gate is a narrower claim than the '
                'tree warrants; widen a check, or accept it deliberately'
            ),
        )
    ]


def check_spec_pin(series: Series, workspace: Path) -> list[Problem]:
    """A Problem when the pinned spec is missing, or has moved since decomposition.

    A series records nowhere which spec it was decomposed from, so afterwards nobody can
    answer "which version of which spec produced this run" — the same silent shape as an
    unvalidated ``effort``: nothing fails at run time, and the comparison the ledger exists
    to support is simply unavailable later. The pin closes it, and this is the half that
    makes it load-bearing rather than decorative.

    **Blocking, and before the first spawn is purchased**, which is what "before any paid
    run" means: the point is that no paid run executes against a spec that has moved since
    it was decomposed. Unlike a path detector this needs no heuristic and has no
    false-positive budget — a hash matches or it does not.

    Silent for a series with no pin, which is every series written before the key existed.
    """
    if not series.spec_path:
        return []
    resolved = workspace / series.spec_path
    where = '[series]'
    try:
        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        return [
            Problem(
                kind='spec_pin',
                where=where,
                message=(
                    f'the pinned spec cannot be read at {resolved}: {exc}. '
                    'spec_path is resolved against the workspace and is repo-relative.'
                ),
            )
        ]
    if actual == series.spec_sha256:
        return []
    return [
        Problem(
            kind='spec_pin',
            where=where,
            message=(
                f'the spec at {series.spec_path} has changed since this series was '
                f'decomposed from it: pinned {series.spec_sha256}, found {actual}. '
                'Re-decompose against the current spec, or update the pin deliberately.'
            ),
        )
    ]


def check_isolation(series: Series, workspace: Path) -> list[Problem]:
    """A Problem for each blocking independent check whose asset isolation fails closed."""
    problems: list[Problem] = []
    for check in series.checks:
        result = isolation_result(workspace, check)
        if result is not None and not result.passed:
            problems.append(
                Problem(kind='isolation', where=f'[[checks]] {check.name!r}', message=result.detail)
            )
    return problems


def preflight(series: Series, workspace: Path) -> PreflightReport:
    """The full pre-flight report for ``series`` run in ``workspace``.

    Problems are collected structural-then-filesystem, in a stable order, so a caller can
    surface every issue at once. Advisories are collected alongside and never affect
    :attr:`~convoy.core.preflight.PreflightReport.clean`.
    """
    return PreflightReport(
        problems=(
            *structural_problems(series),
            *check_prompts(series),
            *check_outputs(series, workspace),
            *check_spec_pin(series, workspace),
            *check_isolation(series, workspace),
        ),
        # Appended after the existing producers, so a consumer that has been reading
        # advisories[0] since 0.3.0 still finds the ungated-PR remark there.
        advisories=(*ungated_prs(series), *inert_assets(series), *gate_scope(series, workspace)),
    )
