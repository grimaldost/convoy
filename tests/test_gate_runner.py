"""Tests for the subprocess gate runner against a real ``tmp_path`` workspace.

These genuinely spawn processes on this machine: a passing check (exit 0), a
failing check (exit 1, which must carry a non-empty detail), and a hanging check
run under a short timeout (which must go red with a detail that names the
timeout). ``sys.executable`` is reused so every command runs under the same
interpreter as the test.
"""

import sys
from pathlib import Path

from convoy.core.gate import CheckResult
from convoy.core.spec import Check
from convoy.interface.gate_runner import SubprocessGateRunner

_PY = sys.executable


def _check(name: str, run: str) -> Check:
    """A blocking check with the given command; independence is irrelevant here."""
    return Check(name=name, run=run, blocking=True)


def test_exit_zero_passes(tmp_path: Path) -> None:
    runner = SubprocessGateRunner()
    (result,) = runner.run(tmp_path, [_check('ok', f'"{_PY}" -c "exit(0)"')])
    assert isinstance(result, CheckResult)
    assert result.passed is True
    assert result.detail == ''
    assert result.check.name == 'ok'


def test_exit_nonzero_fails_with_detail(tmp_path: Path) -> None:
    runner = SubprocessGateRunner()
    (result,) = runner.run(tmp_path, [_check('bad', f'"{_PY}" -c "exit(1)"')])
    assert result.passed is False
    assert result.detail != ''


def test_stderr_tail_is_in_the_detail(tmp_path: Path) -> None:
    # A failing check that prints to stderr should surface that text in the detail
    # so a fix loop has something to re-brief with.
    command = f'"{_PY}" -c "import sys; sys.stderr.write(\'boom-marker\'); sys.exit(1)"'
    runner = SubprocessGateRunner()
    (result,) = runner.run(tmp_path, [_check('bad', command)])
    assert result.passed is False
    assert 'boom-marker' in result.detail


def test_hang_times_out_and_detail_mentions_timeout(tmp_path: Path) -> None:
    runner = SubprocessGateRunner(timeout_seconds=1.0)
    command = f'"{_PY}" -c "import time; time.sleep(30)"'
    (result,) = runner.run(tmp_path, [_check('hang', command)])
    assert result.passed is False
    assert 'timed out' in result.detail.lower()


def test_results_are_one_per_check_in_order(tmp_path: Path) -> None:
    runner = SubprocessGateRunner()
    checks = [
        _check('first', f'"{_PY}" -c "exit(0)"'),
        _check('second', f'"{_PY}" -c "exit(1)"'),
        _check('third', f'"{_PY}" -c "exit(0)"'),
    ]
    results = runner.run(tmp_path, checks)
    assert isinstance(results, tuple)
    assert [r.check.name for r in results] == ['first', 'second', 'third']
    assert [r.passed for r in results] == [True, False, True]


# --- fail-closed isolation for blocking independent checks -------------------


def _touch_command(target: Path) -> str:
    """A command that creates ``target`` and exits 0, as a proof-of-execution probe.

    The path is emitted with forward slashes (``as_posix``) so it needs no
    backslash escaping inside the ``-c`` string literal; Windows accepts ``/`` as
    a separator in ``open``.
    """
    literal = target.as_posix()
    return f'"{_PY}" -c "open(\'{literal}\', \'w\').close()"'


def test_blocking_independent_in_tree_asset_fails_closed_without_running(tmp_path: Path) -> None:
    # A blocking independent check whose asset is IN the workspace must fail closed
    # and must NOT run its command. The command would create a sentinel; its
    # absence afterwards proves the command never ran.
    sentinel = tmp_path / 'ran.sentinel'
    in_tree_asset = tmp_path / 'oracle.py'
    in_tree_asset.write_text('# reachable by the implementer\n', encoding='utf-8')
    check = Check(
        name='oracle',
        run=_touch_command(sentinel),
        blocking=True,
        independent=True,
        asset=str(in_tree_asset),
    )

    (result,) = SubprocessGateRunner().run(tmp_path, [check])

    assert result.passed is False
    assert result.detail != ''
    assert not sentinel.exists(), 'the run command must not execute when isolation fails closed'


def test_blocking_independent_missing_asset_fails_closed_without_running(tmp_path: Path) -> None:
    # An out-of-tree but nonexistent asset also fails closed without running.
    sentinel = tmp_path / 'ran.sentinel'
    missing_asset = tmp_path.parent / 'no-such-oracle' / 'oracle.py'
    check = Check(
        name='oracle',
        run=_touch_command(sentinel),
        blocking=True,
        independent=True,
        asset=str(missing_asset),
    )

    (result,) = SubprocessGateRunner().run(tmp_path, [check])

    assert result.passed is False
    assert not sentinel.exists()


def test_blocking_independent_valid_out_of_tree_asset_runs(tmp_path: Path) -> None:
    # With a real out-of-tree asset, isolation holds, so the check runs normally.
    # The command creates a sentinel (proving it ran) and exits 0 (so it passes).
    outside = tmp_path.parent / f'{tmp_path.name}-oracle'
    outside.mkdir(exist_ok=True)
    asset = outside / 'oracle.py'
    asset.write_text('# out-of-tree oracle\n', encoding='utf-8')
    sentinel = tmp_path / 'ran.sentinel'
    check = Check(
        name='oracle',
        run=_touch_command(sentinel),
        blocking=True,
        independent=True,
        asset=str(asset),
    )

    (result,) = SubprocessGateRunner().run(tmp_path, [check])

    assert result.passed is True
    assert sentinel.exists(), 'an isolated check must actually run its command'
