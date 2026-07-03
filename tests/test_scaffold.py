"""Tests for the convoy init scaffold (interface/scaffold.py)."""

import subprocess
import sys
from pathlib import Path

import pytest

from convoy.core.spec import load_series
from convoy.interface.fs_probe import isolation_result
from convoy.interface.scaffold import ScaffoldError, build_starter_series, scaffold


def test_scaffold_writes_expected_files(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    written = scaffold(root)
    series_file = root / 'series.toml'
    prompt = root / 'prompts' / 'implement.md'
    oracle = root / 'oracles' / 'greeting_check.py'
    workspace = root / 'workspace'
    assert series_file.is_file() and series_file.read_text().strip()
    assert prompt.is_file() and prompt.read_text().strip()
    assert oracle.is_file() and oracle.read_text().strip()
    assert workspace.is_dir()
    assert set(written) == {series_file, prompt, oracle, workspace}


def test_scaffolded_series_loads(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    scaffold(root)
    series = load_series((root / 'series.toml').read_text())
    assert series.id == 'starter'
    assert len(series.prs) == 1
    assert len(series.checks) == 1


def test_starter_check_is_a_correct_independent_check(tmp_path: Path) -> None:
    check = build_starter_series(tmp_path / 'proj').checks[0]
    assert check.blocking is True
    assert check.independent is True
    assert check.asset  # a non-empty out-of-tree asset path


def test_starter_asset_passes_isolation_from_the_workspace(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    scaffold(root)
    series = load_series((root / 'series.toml').read_text())
    # From the scored workspace, the out-of-tree oracle is isolated (the probe returns None).
    assert isolation_result(root / 'workspace', series.checks[0]) is None


def test_all_starter_budgets_are_positive(tmp_path: Path) -> None:
    budgets = build_starter_series(tmp_path / 'proj').governance.budgets
    assert budgets.implementation > 0
    assert budgets.review > 0
    assert budgets.fix > 0


def test_scaffold_refuses_to_clobber(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    scaffold(root)
    with pytest.raises(ScaffoldError):
        scaffold(root)


def test_workspace_is_a_git_repo_on_base(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    scaffold(root)
    branch = subprocess.run(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
        cwd=root / 'workspace',
        capture_output=True,
        text=True,
    )
    assert branch.stdout.strip() == 'base'


def test_generated_oracle_passes_only_when_greeting_present(tmp_path: Path) -> None:
    root = tmp_path / 'proj'
    scaffold(root)
    oracle = root / 'oracles' / 'greeting_check.py'
    workspace = root / 'workspace'
    absent = subprocess.run([sys.executable, str(oracle)], cwd=workspace)
    assert absent.returncode == 1
    (workspace / 'greeting.txt').write_text('hello convoy\n', encoding='utf-8')
    present = subprocess.run([sys.executable, str(oracle)], cwd=workspace)
    assert present.returncode == 0
