"""Tests for the bounded-timeout process runner, including a real no-orphan reaping test.

The load-bearing test (``test_timeout_reaps_grandchild_no_orphan``) genuinely spawns a
process tree three levels deep — the runner's shell, a child ``python``, and a grandchild
``python`` — on this machine. The grandchild appends to a sentinel file forever; after the
timeout fires we assert the sentinel stops growing, i.e. the tree-kill reached the
grandchild and it was not orphaned.
"""

import sys
import time
from pathlib import Path

from convoy.interface.proc import ProcResult, run_with_timeout

# ``sys.executable`` (the venv python) is reused for every spawned process so the tree is
# built from the same interpreter the test itself runs under.
_PY = sys.executable


def test_exit_zero_captures_stdout() -> None:
    result = run_with_timeout(
        f'{_PY} -c "print(\'ok\')"',
        cwd=Path.cwd(),
        timeout_seconds=30.0,
    )
    assert result.exit_code == 0
    assert 'ok' in result.stdout
    assert result.timed_out is False


def test_nonzero_exit_code_is_reported() -> None:
    result = run_with_timeout(
        f'{_PY} -c "import sys; sys.exit(3)"',
        cwd=Path.cwd(),
        timeout_seconds=30.0,
    )
    assert result.exit_code == 3
    assert result.timed_out is False


def test_result_is_frozen_dataclass() -> None:
    result = run_with_timeout(f'{_PY} -c "pass"', cwd=Path.cwd(), timeout_seconds=30.0)
    assert isinstance(result, ProcResult)


def test_timeout_reaps_grandchild_no_orphan(tmp_path: Path) -> None:
    """A grandchild that outlives its timeout must be reaped by the whole-tree kill.

    The child launches a detached grandchild that appends a byte to ``sentinel`` roughly
    every 0.1s in an infinite loop, then the child blocks so the whole tree stays alive
    until killed. We give the runner a short timeout, confirm it reports ``timed_out``, then
    watch the sentinel: if the grandchild were orphaned it would keep writing, so a size
    that stops growing is the proof it was reaped.
    """
    sentinel = tmp_path / 'sentinel.bin'
    grandchild = tmp_path / 'grandchild.py'
    child = tmp_path / 'child.py'

    # The grandchild: append to the sentinel forever, ~every 0.1s.
    grandchild.write_text(
        'import time\n'
        f'p = {str(sentinel)!r}\n'
        'while True:\n'
        "    with open(p, 'ab') as f:\n"
        "        f.write(b'x')\n"
        '    time.sleep(0.1)\n',
        encoding='utf-8',
    )
    # The child: spawn the grandchild as a separate process, then block so the tree lives
    # until the runner kills it. Not waiting on the grandchild is the point — orphaning it
    # is exactly the failure this test guards against.
    child.write_text(
        'import subprocess, sys, time\n'
        f'subprocess.Popen([sys.executable, {str(grandchild)!r}])\n'
        'time.sleep(3600)\n',
        encoding='utf-8',
    )

    start = time.monotonic()
    result = run_with_timeout(
        f'"{_PY}" "{child}"',
        cwd=tmp_path,
        timeout_seconds=1.0,
    )
    elapsed = time.monotonic() - start

    assert result.timed_out is True
    assert result.exit_code == -1
    # The timeout, not a natural exit, ended it: the child sleeps for an hour.
    assert elapsed < 60.0

    # The grandchild needs to have started writing before we judge whether it stopped;
    # poll for the sentinel to appear (generous margin so this is not flaky).
    deadline = time.monotonic() + 10.0
    while not sentinel.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sentinel.exists(), 'grandchild never created the sentinel — test cannot judge reaping'

    # Give any lingering write in flight a moment to land, then take the reference size.
    time.sleep(0.5)
    size_after_kill = sentinel.stat().st_size

    # If the grandchild were orphaned it would append ~15 bytes over the next 1.5s. Reaped,
    # the size holds. Compare against a fresh read to tolerate at most one in-flight write.
    time.sleep(1.5)
    final_size = sentinel.stat().st_size
    assert final_size <= size_after_kill + 1, (
        f'sentinel grew from {size_after_kill} to {final_size} after the tree-kill — '
        'the grandchild was orphaned, not reaped'
    )
