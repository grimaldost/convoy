"""Tests for the exclusive per-workspace lock (interface/workspace_lock.py)."""

from pathlib import Path

import pytest

from convoy.interface.workspace_lock import WorkspaceBusyError, workspace_lock


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
