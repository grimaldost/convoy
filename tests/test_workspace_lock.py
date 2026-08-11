"""Tests for the exclusive per-workspace lock (interface/workspace_lock.py)."""

import os
from pathlib import Path

import pytest

from convoy.interface.workspace_lock import (
    WorkspaceBusyError,
    lock_owner_pid,
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
