"""Tests for the filesystem pre-flight probes (interface/preflight_probe.py)."""

import hashlib
import subprocess
from dataclasses import replace
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
    check_spec_pin,
    gate_scope,
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
        checks=(Check(name='suite', run='true', blocking=True),),
    )
    report = preflight(series, workspace)
    assert report.problems == ()
    assert report.advisories == ()
    assert report.clean


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
    report = preflight(series, workspace)
    assert len(report.problems) >= 2
    assert all(problem.kind == 'paths' for problem in report.problems)
    assert not report.clean


# --- both advisory producers ---------------------------------------------------------------


def test_an_inert_asset_reaches_the_report_without_making_it_unclean(tmp_path: Path) -> None:
    workspace, prompts, outputs = _dirs(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series = _series(
        prompts=prompts,
        outputs=outputs,
        prs=(PR(id='pr-1', branch='pr-1', prompt='pr1.md', phase='p'),),
        checks=(
            Check(name='suite', run='true', blocking=True),
            Check(name='oracle', run='true', blocking=False, asset=str(tmp_path / 'o.py')),
        ),
    )

    report = preflight(series, workspace)

    assert report.problems == ()
    assert report.clean is True
    assert [(a.kind, a.where) for a in report.advisories] == [('gate', "[[checks]] 'oracle'")]


def test_the_ungated_pr_advisory_stays_first(tmp_path: Path) -> None:
    """A consumer has been reading advisories[0] as the ungated-PR remark since 0.3.0."""
    workspace, prompts, outputs = _dirs(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series = _series(
        prompts=prompts,
        outputs=outputs,
        prs=(PR(id='pr-1', branch='pr-1', prompt='pr1.md', phase='p'),),
        # Non-blocking, so it gates nothing (an ungated PR) AND its asset is inert.
        checks=(Check(name='oracle', run='true', blocking=False, asset=str(tmp_path / 'o.py')),),
    )

    report = preflight(series, workspace)

    assert [a.where for a in report.advisories] == ["[[prs]] 'pr-1'", "[[checks]] 'oracle'"]


# --- gate scope: what the gate does not run ------------------------------------------------
#
# Phase scoping made subset gates possible and convoy said nothing about how to scope one. A
# 16-PR wave gated 16/16 green while two repository-wide guards were red, found only by
# running the full suite by hand after the run reported `completed` -- so the series' own
# quality claim was stronger than the tree warranted. convoy already holds the gate commands
# and the workspace, so this is answerable for free at dry_run.


def _tree(workspace: Path, *relative: str) -> None:
    for entry in relative:
        path = workspace / entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('x', encoding='utf-8')


def _scoped(tmp_path: Path, run: str, *, blocking: bool = True) -> tuple[Series, Path]:
    workspace, prompts, outputs = _dirs(tmp_path)
    series = _series(
        prompts=prompts,
        outputs=outputs,
        checks=(Check(name='suite', run=run, blocking=blocking),),
    )
    return series, workspace


def test_a_path_scoped_gate_names_the_test_files_it_will_not_run(tmp_path: Path) -> None:
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(workspace, 'src/core/test_core.py', 'tests/test_registry.py', 'tests/test_wiring.py')

    (advisory,) = gate_scope(series, workspace)

    assert advisory.kind == 'gate'
    assert '2' in advisory.message
    # Named, so the author can judge rather than take a bare count on trust.
    assert 'test_registry.py' in advisory.message


def test_an_unscoped_blocking_check_says_nothing(tmp_path: Path) -> None:
    """`pytest -q` runs the whole tree, so there is nothing the gate does not run."""
    series, workspace = _scoped(tmp_path, 'python -m pytest -q')
    _tree(workspace, 'tests/test_registry.py')

    assert gate_scope(series, workspace) == []


def test_a_scope_that_covers_every_test_file_says_nothing(tmp_path: Path) -> None:
    series, workspace = _scoped(tmp_path, 'python -m pytest tests')
    _tree(workspace, 'tests/test_a.py', 'tests/nested/test_b.py')

    assert gate_scope(series, workspace) == []


def test_an_out_of_tree_oracle_does_not_suppress_the_advisory(tmp_path: Path) -> None:
    """A check pointing outside the workspace says nothing about in-tree coverage.

    Treating it as "runs everything" would silence the advisory for exactly the series
    shape -- a subtree-scoped suite plus an independent oracle -- it exists to warn about.
    """
    workspace, prompts, outputs = _dirs(tmp_path)
    oracle = tmp_path / 'oracles' / 'probe.py'
    oracle.parent.mkdir()
    oracle.write_text('x', encoding='utf-8')
    series = _series(
        prompts=prompts,
        outputs=outputs,
        checks=(
            Check(name='suite', run='python -m pytest src/core', blocking=True),
            Check(name='oracle', run=f'python {oracle}', blocking=True),
        ),
    )
    _tree(workspace, 'src/core/mod.py', 'tests/test_registry.py')

    (advisory,) = gate_scope(series, workspace)

    assert 'test_registry.py' in advisory.message


def test_a_workspace_with_no_test_files_says_nothing(tmp_path: Path) -> None:
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(workspace, 'src/core/mod.py', 'README.md')

    assert gate_scope(series, workspace) == []


def test_a_non_blocking_check_does_not_count_as_scope(tmp_path: Path) -> None:
    """Only a blocking check can stop a merge, so only a blocking check defines the gate."""
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core', blocking=False)
    _tree(workspace, 'tests/test_registry.py')

    assert gate_scope(series, workspace) == []


def test_ignored_directories_are_not_searched_for_test_files(tmp_path: Path) -> None:
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(workspace, 'src/core/mod.py', 'node_modules/pkg/test_vendor.py', '.venv/lib/test_dep.py')

    assert gate_scope(series, workspace) == []


def test_the_advisory_reaches_the_preflight_report(tmp_path: Path) -> None:
    """It has to arrive on the channel the surfaces already read, or nobody meets it."""
    workspace, prompts, outputs = _dirs(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    series = _series(
        prompts=prompts,
        outputs=outputs,
        prs=(PR(id='pr-1', branch='pr-1', prompt='pr1.md', phase='p'),),
        checks=(Check(name='suite', run='python -m pytest src/core', blocking=True),),
    )
    _tree(workspace, 'src/core/mod.py', 'tests/test_registry.py')

    report = preflight(series, workspace)

    assert report.clean  # advice, never a problem
    assert [a.where for a in report.advisories] == ['[[checks]]']


# --- the spec pin: resolved and matched before any paid run --------------------------------


def _pinned(tmp_path: Path, *, path: str, digest: str) -> tuple[Series, Path]:
    workspace, prompts, outputs = _dirs(tmp_path)
    series = _series(prompts=prompts, outputs=outputs)
    return replace(series, spec_path=path, spec_sha256=digest), workspace


def _write_spec(workspace: Path, relative: str, body: str) -> str:
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode('utf-8'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def test_a_matching_pin_is_no_problem(tmp_path: Path) -> None:
    workspace, prompts, outputs = _dirs(tmp_path)
    digest = _write_spec(workspace, 'docs/spec.md', '# the spec\n')
    series = replace(
        _series(prompts=prompts, outputs=outputs), spec_path='docs/spec.md', spec_sha256=digest
    )

    assert check_spec_pin(series, workspace) == []


def test_a_spec_that_moved_since_decomposition_blocks_the_run(tmp_path: Path) -> None:
    """Blocking, not advisory: no paid run executes against a spec that has changed."""
    workspace, prompts, outputs = _dirs(tmp_path)
    _write_spec(workspace, 'docs/spec.md', '# the spec, edited since\n')
    stale = hashlib.sha256(b'# the spec\n').hexdigest()
    series = replace(
        _series(prompts=prompts, outputs=outputs), spec_path='docs/spec.md', spec_sha256=stale
    )

    (problem,) = check_spec_pin(series, workspace)

    assert problem.kind == 'spec_pin'
    assert problem.where == '[series]'
    assert stale in problem.message  # both hashes, so the reader can see which is which


def test_a_pinned_spec_that_is_not_there_blocks_the_run(tmp_path: Path) -> None:
    series, workspace = _pinned(tmp_path, path='docs/gone.md', digest='b' * 64)

    (problem,) = check_spec_pin(series, workspace)

    assert problem.kind == 'spec_pin'
    assert 'gone.md' in problem.message


def test_an_unpinned_series_is_never_asked_about_a_spec(tmp_path: Path) -> None:
    workspace, prompts, outputs = _dirs(tmp_path)

    assert check_spec_pin(_series(prompts=prompts, outputs=outputs), workspace) == []


def test_a_stale_pin_reaches_the_preflight_report(tmp_path: Path) -> None:
    """It has to be on the blocking list, or it is decoration."""
    workspace, prompts, outputs = _dirs(tmp_path)
    (prompts / 'pr1.md').write_text('do it')
    _write_spec(workspace, 'docs/spec.md', '# edited\n')
    series = replace(
        _series(
            prompts=prompts,
            outputs=outputs,
            prs=(PR(id='pr-1', branch='pr-1', prompt='pr1.md', phase='p'),),
        ),
        spec_path='docs/spec.md',
        spec_sha256='c' * 64,
    )

    report = preflight(series, workspace)

    assert not report.clean
    assert [p.kind for p in report.problems] == ['spec_pin']


def _init_repo(workspace: Path, *, gitignore: str) -> None:
    """Make ``workspace`` a git repo with ``gitignore`` as its ignore rules."""
    subprocess.run(['git', 'init', '-q'], cwd=workspace, check=True)
    (workspace / '.gitignore').write_text(gitignore, encoding='utf-8')


def test_a_test_file_the_repo_ignores_is_not_counted_against_the_gate(tmp_path: Path) -> None:
    """The borrowed-directory case: a virtualenv under a name no hardcoded list anticipates."""
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(workspace, 'src/core/mod.py', '.venv-core/lib/test_dep.py')
    _init_repo(workspace, gitignore='.venv-core/\n')

    assert gate_scope(series, workspace) == []


def test_an_ignored_test_file_does_not_inflate_a_real_advisory(tmp_path: Path) -> None:
    """The advisory still fires for the tracked file, and counts only it."""
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(workspace, 'src/core/mod.py', 'tests/test_real.py', 'containers/context/test_copy.py')
    _init_repo(workspace, gitignore='containers/\n')

    (advisory,) = gate_scope(series, workspace)

    assert 'tests/test_real.py' in advisory.message
    assert '1 test file' in advisory.message
    assert 'test_copy.py' not in advisory.message


def test_a_workspace_that_is_not_a_repository_still_gets_the_advisory(tmp_path: Path) -> None:
    """No repo means no ignore rules to consult, not an advisory withheld."""
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(workspace, 'src/core/mod.py', 'tests/test_real.py')

    (advisory,) = gate_scope(series, workspace)

    assert 'tests/test_real.py' in advisory.message


def test_a_long_uncovered_list_is_summarised_by_directory(tmp_path: Path) -> None:
    """Past a handful, three arbitrary file names hide where the rest are."""
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(
        workspace,
        'src/core/mod.py',
        'tests/unit/test_a.py',
        'tests/unit/test_b.py',
        'tests/unit/test_c.py',
        'tests/e2e/test_d.py',
        'other/test_e.py',
    )

    (advisory,) = gate_scope(series, workspace)

    assert '5 test file(s)' in advisory.message
    # Ranked by how many each holds, so the biggest offender is the first thing read.
    assert 'tests/unit/ (3)' in advisory.message
    assert 'tests/e2e/ (1)' in advisory.message
    assert 'other/ (1)' in advisory.message
    # No individual file name survives the switch to directories.
    assert 'test_a.py' not in advisory.message


def test_a_short_uncovered_list_still_names_the_files(tmp_path: Path) -> None:
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(workspace, 'src/core/mod.py', 'tests/test_a.py', 'tests/test_b.py')

    (advisory,) = gate_scope(series, workspace)

    assert 'tests/test_a.py' in advisory.message
    assert 'tests/test_b.py' in advisory.message


def test_many_files_in_few_directories_names_every_directory(tmp_path: Path) -> None:
    """Past the file budget but inside the directory one: nothing is left over to count."""
    series, workspace = _scoped(tmp_path, 'python -m pytest src/core')
    _tree(
        workspace,
        'src/core/mod.py',
        'tests/test_a.py',
        'tests/test_b.py',
        'tests/test_c.py',
        'tests/test_d.py',
    )

    (advisory,) = gate_scope(series, workspace)

    assert 'tests/ (4)' in advisory.message
    assert 'more director' not in advisory.message
