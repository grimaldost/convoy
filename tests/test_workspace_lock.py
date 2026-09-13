"""Tests for the exclusive per-workspace lock (interface/workspace_lock.py)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from convoy.interface.workspace_lock import (
    WorkspaceBusyError,
    lock_owner_pid,
    lock_ownership,
    lock_path,
    workspace_lock,
)


def test_second_acquire_raises_busy_while_first_holds_the_lock(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()

    with workspace_lock(ws), pytest.raises(WorkspaceBusyError), workspace_lock(ws):
        pass


def test_lock_is_released_on_normal_exit_so_a_later_acquire_succeeds(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()

    with workspace_lock(ws):
        pass

    with workspace_lock(ws):
        pass  # would have raised WorkspaceBusyError if the first lock leaked


def test_lock_is_released_after_an_exception_inside_the_block(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()

    with pytest.raises(ValueError), workspace_lock(ws):
        raise ValueError('boom')

    with workspace_lock(ws):
        pass  # would have raised WorkspaceBusyError if the failed run leaked the lock


# --- the owner pid: the one durable trace a hard-killed run leaves behind -------------------


def test_lock_owner_pid_is_this_process_while_the_lock_is_held(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()

    with workspace_lock(ws):
        assert lock_owner_pid(ws) == os.getpid()


def test_lock_owner_pid_is_none_when_no_lock_is_held(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()

    assert lock_owner_pid(ws) is None


@pytest.mark.parametrize('contents', ['', '   ', 'not-a-pid', '12.5'])
def test_lock_owner_pid_is_none_for_contents_that_are_not_a_pid(
    tmp_path: Path, contents: str
) -> None:
    """A lock caught between O_CREAT and the write is empty, not corrupt — same answer."""
    ws = tmp_path / 'ws'
    (ws / '.git').mkdir(parents=True)
    lock_path(ws).write_text(contents, encoding='utf-8')

    assert lock_owner_pid(ws) is None


# --- lock_ownership: the one place "is this lock stale" is decided ------------------------
#
# Composes lock_owner_pid with process_is_alive so convoy status (dead/running) and
# convoy unlock (refuse a live owner) read the same judgement instead of two inline
# copies of it drifting apart.


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.DEVNULL)
    pid = child.pid
    child.wait()
    return pid


def test_lock_ownership_has_no_pid_when_there_is_no_lock(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    ws.mkdir()

    ownership = lock_ownership(ws)
    assert ownership.pid is None
    assert ownership.stale is False


def test_lock_ownership_is_not_stale_while_the_owner_is_alive(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    (ws / '.git').mkdir(parents=True)
    lock_path(ws).write_text(str(os.getpid()), encoding='utf-8')

    ownership = lock_ownership(ws)
    assert ownership.pid == os.getpid()
    assert ownership.stale is False


def test_lock_ownership_is_stale_once_the_owner_is_gone(tmp_path: Path) -> None:
    ws = tmp_path / 'ws'
    (ws / '.git').mkdir(parents=True)
    dead_pid = _dead_pid()
    lock_path(ws).write_text(str(dead_pid), encoding='utf-8')

    ownership = lock_ownership(ws)
    assert ownership.pid == dead_pid
    assert ownership.stale is True
