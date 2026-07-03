"""Tests for the filesystem pre-flight probes (interface/preflight_probe.py)."""

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
)
from convoy.interface.preflight_probe import (
    check_isolation,
    check_outputs,
    check_prompts,
    preflight,
)


def _series(
    *,
    prompts: Path,
    outputs: Path,
    prs: tuple[PR, ...] = (),
    checks: tuple[Check, ...] = (),
) -> Series:
    return Series(
        id='s',
        version='1',
        branches=Branches(base='base', integration='integration'),
        paths=Paths(prompts=str(prompts), outputs=str(outputs)),
        governance=Governance(
            effort='low',
            permission_mode='default',
            timeout_seconds=60,
            budgets=Budgets(implementation=1.0, review=1.0, fix=1.0),
            tools=Tools(implementation=('Read',), review=(), fix=()),
            model='claude-haiku-4-5',
        ),
        review=Review(blocking=False, max_fix_attempts=0),
        checks=checks,
        prs=prs,
    )


def _dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A workspace, an out-of-tree prompts dir, and an out-of-tree outputs dir."""
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    outputs = tmp_path / 'outputs'
    return workspace, prompts, outputs


def test_all_clean_has_no_problems(tmp_path: Path) -> None:
    workspace, prompts, outputs = _dirs(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series = _series(
        prompts=prompts,
        outputs=outputs,
        prs=(PR(id='pr-1', branch='pr-1', prompt='pr1.md', phase='p'),),
    )
    assert preflight(series, workspace) == []


def test_missing_prompts_dir_is_one_paths_problem(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    series = _series(
        prompts=tmp_path / 'missing',
        outputs=tmp_path / 'outputs',
        prs=(
            PR(id='pr-1', branch='pr-1', prompt='a.md', phase='p'),
            PR(id='pr-2', branch='pr-2', prompt='b.md', phase='p'),
        ),
    )
    problems = check_prompts(series)
    # A single "dir missing" problem, not one per PR.
    assert len(problems) == 1
    assert problems[0].kind == 'paths'


def test_missing_prompt_file_is_reported_per_pr(tmp_path: Path) -> None:
    _, prompts, outputs = _dirs(tmp_path)
    (prompts / 'a.md').write_text('a')  # b.md is absent
    series = _series(
        prompts=prompts,
        outputs=outputs,
        prs=(
            PR(id='pr-1', branch='pr-1', prompt='a.md', phase='p'),
            PR(id='pr-2', branch='pr-2', prompt='b.md', phase='p'),
        ),
    )
    problems = check_prompts(series)
    assert len(problems) == 1
    assert problems[0].kind == 'prompt'
    assert "'pr-2'" in problems[0].where


def test_outputs_that_is_a_file_is_a_paths_problem(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    outputs = tmp_path / 'outputs-file'
    outputs.write_text('not a dir')
    series = _series(prompts=tmp_path / 'prompts', outputs=outputs)
    problems = check_outputs(series, workspace)
    assert any('not a directory' in p.message for p in problems)


def test_missing_outputs_dir_is_not_a_problem(tmp_path: Path) -> None:
    workspace, prompts, outputs = _dirs(tmp_path)  # outputs does not exist yet
    series = _series(prompts=prompts, outputs=outputs)
    assert check_outputs(series, workspace) == []


def test_outputs_inside_the_workspace_is_a_paths_problem(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    inside = workspace / 'outputs'
    series = _series(prompts=tmp_path / 'prompts', outputs=inside)
    problems = check_outputs(series, workspace)
    assert len(problems) == 1
    assert problems[0].kind == 'paths'
    assert 'inside the scored workspace' in problems[0].message


def test_in_tree_independent_asset_surfaces_an_isolation_problem(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    asset = workspace / 'oracle.py'  # in-tree -> fails closed
    asset.write_text('x')
    check = Check(name='ind', run='python x', blocking=True, independent=True, asset=str(asset))
    problems = check_isolation(
        _series(prompts=tmp_path, outputs=tmp_path, checks=(check,)), workspace
    )
    assert len(problems) == 1
    assert problems[0].kind == 'isolation'


def test_out_of_tree_independent_asset_has_no_isolation_problem(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    asset = tmp_path / 'oracle.py'  # out-of-tree and present -> isolated
    asset.write_text('x')
    check = Check(name='ind', run='python x', blocking=True, independent=True, asset=str(asset))
    assert (
        check_isolation(_series(prompts=tmp_path, outputs=tmp_path, checks=(check,)), workspace)
        == []
    )


def test_non_blocking_independent_check_is_not_probed(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    asset = workspace / 'oracle.py'  # in-tree, but the check is non-blocking
    asset.write_text('x')
    check = Check(name='ind', run='python x', blocking=False, independent=True, asset=str(asset))
    assert (
        check_isolation(_series(prompts=tmp_path, outputs=tmp_path, checks=(check,)), workspace)
        == []
    )


def test_preflight_collects_across_categories(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    inside_outputs = workspace / 'out'
    # Missing prompts dir + outputs inside workspace => at least two problems of kind 'paths'.
    series = _series(
        prompts=tmp_path / 'missing',
        outputs=inside_outputs,
        prs=(PR(id='pr-1', branch='pr-1', prompt='a.md', phase='p'),),
    )
    problems = preflight(series, workspace)
    assert len(problems) >= 2
    assert all(problem.kind == 'paths' for problem in problems)
