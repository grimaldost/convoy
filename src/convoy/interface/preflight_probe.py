"""Filesystem pre-flight probes (shell): the pre-run checks that must touch disk.

Composes the pure ``core.preflight.structural_problems`` with filesystem checks — each
PR's prompt file exists, ``[paths]`` are usable and out-of-tree, and every blocking
independent check's asset is isolated (reusing ``fs_probe.isolation_result``) — into one
list of :class:`~convoy.core.preflight.Problem`. Used by ``convoy validate`` and by
``convoy run`` before any git mutation, so a misconfigured series fails fast and whole
rather than half-executing and leaving a partially-branched tree behind.
"""

from pathlib import Path

from convoy.core.preflight import Problem, structural_problems
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


def preflight(series: Series, workspace: Path) -> list[Problem]:
    """Every pre-flight Problem for ``series`` run in ``workspace`` — structural then filesystem."""
    return [
        *structural_problems(series),
        *check_prompts(series),
        *check_outputs(series, workspace),
        *check_isolation(series, workspace),
    ]
