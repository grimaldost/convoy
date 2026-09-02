"""Tests for the per-project gate scaffold (interface/gate_scaffold.py, ``convoy gate --init``)."""

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import convoy.interface.cli as cli
from convoy.core.spec import load_gate_spec
from convoy.interface.drivers.headless import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE
from convoy.interface.fs_probe import isolation_result
from convoy.interface.gate_scaffold import GateScaffoldError, detect_toolchain, scaffold_gate
from convoy.interface.gate_service import find_gate_spec, load_gate_spec_file

runner = CliRunner()


def _python_project(root: Path, *, uv: bool = True, tools: str = 'ruff ty pytest') -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text(
        f'[project]\nname = "demo"\n\n[dependency-groups]\ndev = [{tools!r}]\n',
        encoding='utf-8',
    )
    if uv:
        (root / 'uv.lock').write_text('', encoding='utf-8')
    (root / 'tests').mkdir(exist_ok=True)
    return root


def _spec_text(root: Path) -> str:
    return (root / '.convoy' / 'gate.toml').read_text(encoding='utf-8')


# --- detection ------------------------------------------------------------------------------


def test_python_uv_project_yields_the_full_default_gate(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj')
    toolchain = detect_toolchain(root)
    assert toolchain.label == 'python'
    by_name = {check.name: check.run for check in toolchain.checks}
    assert by_name == {
        'lock': 'uv lock --check',
        'lint': 'uv run ruff check .',
        'format': 'uv run ruff format --check .',
        'types': 'uv run ty check',
        'tests': 'uv run pytest -q',
    }
    assert all(check.blocking and not check.independent for check in toolchain.checks)


def test_python_project_without_uv_runs_the_tools_bare(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj', uv=False, tools='ruff mypy pytest')
    by_name = {check.name: check.run for check in detect_toolchain(root).checks}
    assert 'lock' not in by_name
    assert by_name['lint'] == 'ruff check .'
    assert by_name['types'] == 'mypy .'
    assert by_name['tests'] == 'pytest -q'


def test_ty_detection_does_not_match_pytest(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj', uv=False, tools='pytest')
    names = {check.name for check in detect_toolchain(root).checks}
    assert names == {'tests'}


def test_node_project_yields_its_scripts(tmp_path: Path) -> None:
    root = tmp_path / 'web'
    root.mkdir()
    (root / 'package.json').write_text(
        '{"scripts": {"lint": "eslint .", "test": "vitest run", "build": "vite build"}}',
        encoding='utf-8',
    )
    toolchain = detect_toolchain(root)
    assert toolchain.label == 'node'
    assert [(check.name, check.run) for check in toolchain.checks] == [
        ('lint', 'npm run lint'),
        ('tests', 'npm run test'),
    ]


def test_unknown_toolchain_yields_the_red_placeholder(tmp_path: Path) -> None:
    root = tmp_path / 'bare'
    root.mkdir()
    toolchain = detect_toolchain(root)
    assert toolchain.label == 'none'
    (check,) = toolchain.checks
    assert check.name == 'configure'
    assert check.blocking is True
    assert 'gate.toml' in check.repair_hint


# --- writing --------------------------------------------------------------------------------


def test_scaffold_writes_a_loadable_project_spec_and_the_gitignore(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj')
    written = scaffold_gate(root, {})
    spec_path = root / '.convoy' / 'gate.toml'
    assert set(written) == {spec_path, root / '.convoy' / '.gitignore'}
    assert (root / '.convoy' / '.gitignore').read_text(encoding='utf-8') == 'hook.log\n'
    spec = load_gate_spec(_spec_text(root))
    assert spec.id == 'proj'
    assert [check.name for check in spec.checks] == ['lock', 'lint', 'format', 'types', 'tests']
    assert find_gate_spec(root / 'tests', {}) == spec_path


def test_scaffold_header_names_the_next_step(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj')
    scaffold_gate(root, {})
    text = _spec_text(root)
    assert text.startswith('# convoy gate for proj')
    assert '--independent' in text
    assert 'before' in text and 'implementer' in text


def test_scaffold_refuses_to_clobber_before_writing_anything(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj')
    (root / '.convoy').mkdir()
    (root / '.convoy' / 'gate.toml').write_text('keep', encoding='utf-8')
    with pytest.raises(GateScaffoldError, match='refusing to overwrite'):
        scaffold_gate(root, {})
    assert _spec_text(root) == 'keep'
    assert not (root / '.convoy' / '.gitignore').exists()


def test_scaffold_with_independent_writes_a_placeholder_oracle(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj')
    oracles = tmp_path / 'oracles'
    env = {'CONVOY_ORACLES': str(oracles)}
    written = scaffold_gate(root, env, independent='contract')
    oracle = oracles / 'contract.py'
    assert oracle in written
    assert 'not written yet' in oracle.read_text(encoding='utf-8')
    assert '${CONVOY_ORACLES}/contract.py' in _spec_text(root)
    spec = load_gate_spec_file(root / '.convoy' / 'gate.toml', env)
    check = next(check for check in spec.checks if check.name == 'contract')
    assert check.independent is True and check.blocking is True
    assert check.asset == f'{oracles}/contract.py'
    assert isolation_result(root, check) is None


def test_scaffold_defaults_the_oracles_dir_from_the_project_name(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj')
    home = tmp_path / 'home'
    written = scaffold_gate(root, {'CONVOY_HOME': str(home)}, independent='contract')
    oracle = next(path for path in written if path.name == 'contract.py')
    assert oracle == home / 'oracles' / 'proj' / 'contract.py'


def test_scaffold_refuses_an_existing_oracle(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj')
    oracles = tmp_path / 'oracles'
    oracles.mkdir()
    (oracles / 'contract.py').write_text('real', encoding='utf-8')
    with pytest.raises(GateScaffoldError, match='refusing to overwrite'):
        scaffold_gate(root, {'CONVOY_ORACLES': str(oracles)}, independent='contract')
    assert not (root / '.convoy').exists()


def test_scaffold_refuses_an_invalid_oracle_name(tmp_path: Path) -> None:
    root = _python_project(tmp_path / 'proj')
    with pytest.raises(GateScaffoldError, match='invalid oracle name'):
        scaffold_gate(root, {}, independent='../escape')


# --- the CLI --------------------------------------------------------------------------------


def test_gate_init_scaffolds_and_the_gate_then_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    root = tmp_path / 'bare'
    root.mkdir()
    result = runner.invoke(cli.app, ['gate', '--init', '--workspace', str(root)])
    assert result.exit_code == EXIT_OK, result.stderr
    assert 'created' in result.stdout and 'gate.toml' in result.stdout
    gated = runner.invoke(cli.app, ['gate', '--workspace', str(root)])
    assert gated.exit_code == EXIT_BLOCKED
    assert 'configure' in gated.stderr


def test_gate_init_with_independent_runs_the_placeholder_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    oracles = tmp_path / 'oracles'
    monkeypatch.setenv('CONVOY_ORACLES', str(oracles))
    root = tmp_path / 'web'
    root.mkdir()
    (root / 'package.json').write_text(
        f'{{"scripts": {{"test": "\\"{sys.executable}\\" -c \\"exit(0)\\""}}}}',
        encoding='utf-8',
    )
    result = runner.invoke(
        cli.app, ['gate', '--init', '--independent', 'contract', '--workspace', str(root)]
    )
    assert result.exit_code == EXIT_OK, result.stderr
    assert (oracles / 'contract.py').is_file()
    # Point the scaffolded check at this interpreter so the oracle runs under test.
    spec_path = root / '.convoy' / 'gate.toml'
    text = spec_path.read_text(encoding='utf-8').replace(
        'run = "python "', f'run = "\\"{sys.executable}\\" "'.replace('\\', '\\\\'), 1
    )
    spec_path.write_text(text, encoding='utf-8')
    gated = runner.invoke(cli.app, ['gate', '--workspace', str(root), '--phase', 'x'])
    assert gated.exit_code == EXIT_USAGE  # no check declares phase x: refused, not narrowed
    gated = runner.invoke(cli.app, ['gate', '--workspace', str(root), '--brief'])
    assert gated.exit_code == EXIT_BLOCKED
    assert 'not written yet' in gated.stdout


def test_gate_init_refuses_a_second_time(tmp_path: Path) -> None:
    root = tmp_path / 'bare'
    root.mkdir()
    assert runner.invoke(cli.app, ['gate', '--init', '-w', str(root)]).exit_code == EXIT_OK
    again = runner.invoke(cli.app, ['gate', '--init', '-w', str(root)])
    assert again.exit_code == EXIT_USAGE
    assert 'refusing to overwrite' in again.stderr


def test_independent_without_init_is_usage(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ['gate', '--independent', 'x', '-w', str(tmp_path)])
    assert result.exit_code == EXIT_USAGE
    assert '--init' in result.stderr


# --- trust: --init trusts, --trust arms an existing spec ------------------------------------


def _trust_list(home: Path) -> str:
    path = home / 'hook-trust.toml'
    return path.read_text(encoding='utf-8') if path.exists() else ''


def test_gate_init_does_not_arm_the_hook_and_names_the_next_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / 'home'
    monkeypatch.setenv('CONVOY_HOME', str(home))
    root = tmp_path / 'bare'
    root.mkdir()
    result = runner.invoke(cli.app, ['gate', '--init', '-w', str(root)])
    assert result.exit_code == EXIT_OK, result.stderr
    assert 'convoy gate --trust' in result.stdout
    assert _trust_list(home) == ''


def test_gate_trust_from_a_subdirectory_arms_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / 'home'
    monkeypatch.setenv('CONVOY_HOME', str(home))
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    root = tmp_path / 'repo'
    (root / '.convoy').mkdir(parents=True)
    (root / '.convoy' / 'gate.toml').write_text(
        '[series]\nid = "c"\n\n[[checks]]\nname = "x"\nrun = "exit 0"\n'
        'blocking = true\nindependent = false\n',
        encoding='utf-8',
    )
    sub = root / 'src' / 'pkg'
    sub.mkdir(parents=True)
    result = runner.invoke(cli.app, ['gate', '--trust', '-w', str(sub)])
    assert result.exit_code == EXIT_OK, result.stderr
    assert root.resolve().as_posix() in _trust_list(home)
    assert sub.resolve().as_posix() not in _trust_list(home)


def test_gate_trust_arms_an_existing_project_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / 'home'
    monkeypatch.setenv('CONVOY_HOME', str(home))
    root = tmp_path / 'cloned'
    (root / '.convoy').mkdir(parents=True)
    (root / '.convoy' / 'gate.toml').write_text(
        '[series]\nid = "c"\n\n[[checks]]\nname = "x"\nrun = "exit 0"\n'
        'blocking = true\nindependent = false\n',
        encoding='utf-8',
    )
    result = runner.invoke(cli.app, ['gate', '--trust', '-w', str(root)])
    assert result.exit_code == EXIT_OK, result.stderr
    assert root.resolve().as_posix() in _trust_list(home)


def test_gate_trust_without_a_spec_is_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('CONVOY_HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    root = tmp_path / 'bare'
    root.mkdir()
    result = runner.invoke(cli.app, ['gate', '--trust', '-w', str(root)])
    assert result.exit_code == EXIT_USAGE
    assert 'nothing to arm' in result.stderr
    assert _trust_list(tmp_path / 'home') == ''


def test_explicit_gate_on_an_untrusted_project_notes_the_unarmed_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('CONVOY_HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    root = tmp_path / 'cloned'
    (root / '.convoy').mkdir(parents=True)
    run = f'"{sys.executable}" -c "exit(0)"'
    escaped = run.replace('\\', '\\\\').replace('"', '\\"')
    (root / '.convoy' / 'gate.toml').write_text(
        '[series]\nid = "c"\n\n[[checks]]\nname = "x"\n'
        f'run = "{escaped}"\n'
        'blocking = true\nindependent = false\n',
        encoding='utf-8',
    )
    result = runner.invoke(cli.app, ['gate', '-w', str(root)])
    assert result.exit_code == EXIT_OK, result.stderr
    assert 'hook is not armed' in result.stderr
    trusted = runner.invoke(cli.app, ['gate', '--trust', '-w', str(root)])
    assert trusted.exit_code == EXIT_OK
    again = runner.invoke(cli.app, ['gate', '-w', str(root)])
    assert 'hook is not armed' not in again.stderr
