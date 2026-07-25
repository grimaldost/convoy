"""Tests for the detached launch — the handle-now path behind ``convoy_run(detach=true)``.

Two levels. The unit tests patch ``subprocess.Popen`` and assert the command line, the
platform detach flags, and the stream redirection, since those are the whole contract and
a real process cannot show them. One integration test then launches a **real** detached
child against a workspace whose run lock is already held: the child raises
``WorkspaceBusyError`` at ``os.open(O_EXCL)``, which precedes the seat probe and every
scored spawn, so the test provably cannot reach a real agent — the suite-wide
``_no_real_seat_probe`` guard does not cross a process boundary, so nothing else may be
assumed about the child.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from convoy.interface.detached import Launch, launch_detached, log_path, result_path

# How long to wait for the detached child to write its verdict. Generous: it pays a fresh
# interpreter start and convoy's imports, and a slow CI box is not a failure.
_CHILD_DEADLINE_S = 90.0


def _series_toml(prompts: Path, outputs: Path) -> str:
    return f"""
[series]
id = "detach-test"
version = "1"
[branches]
base = "base"
integration = "integration"
[paths]
prompts = "{prompts.as_posix()}"
outputs = "{outputs.as_posix()}"
[governance]
model = "claude-haiku-4-5"
effort = "low"
permission_mode = "acceptEdits"
timeout_seconds = 60
[governance.budgets]
implementation = 0.5
review = 0.25
fix = 0.25
[governance.tools]
implementation = ["Read", "Write"]
review = ["Read"]
fix = ["Read", "Write"]
[review]
blocking = false
max_fix_attempts = 0
[[checks]]
name = "noop"
run = "python -c \\"exit(0)\\""
blocking = false
[[prs]]
id = "pr-1"
branch = "pr-1"
prompt = "pr1.md"
phase = "core"
"""


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A workspace, an out-of-tree prompts dir with one prompt, and an outputs dir."""
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'pr1.md').write_text('do it', encoding='utf-8')
    return workspace, prompts, tmp_path / 'outputs'


class _FakePopen:
    """Records the arguments a launch would have used instead of starting anything."""

    calls: list[dict[str, Any]] = []

    def __init__(self, command: list[str], **kwargs: Any) -> None:
        self.pid = 4242
        # Capture the stream objects' names now: the caller closes them on the way out.
        streams = {
            key: getattr(kwargs.get(key), 'name', kwargs.get(key))
            for key in ('stdin', 'stdout', 'stderr')
        }
        _FakePopen.calls.append({'command': command, **kwargs, **streams})


@pytest.fixture
def fake_popen(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    _FakePopen.calls = []
    monkeypatch.setattr('convoy.interface.detached.subprocess.Popen', _FakePopen)
    return _FakePopen.calls


def test_launch_runs_convoy_through_this_interpreter(
    layout: tuple[Path, Path, Path], fake_popen: list[dict[str, Any]]
) -> None:
    """``sys.executable -m convoy``, not a bare ``convoy``: PATH is not ours to assume."""
    workspace, _prompts, outputs = layout

    launch = launch_detached(
        Path('series.toml'), workspace, outputs, run_id='run-1', config_isolation=True
    )

    command = fake_popen[0]['command']
    assert command[:4] == [sys.executable, '-m', 'convoy', 'run']
    assert command[4] == 'series.toml'
    # The id is pinned, or the returned handle would name a run the child never adopted.
    assert '--run-id' in command
    assert command[command.index('--run-id') + 1] == 'run-1'
    # --json, or the child's verdict is prose and the result file is unparseable.
    assert '--json' in command
    assert launch == Launch(
        run_id='run-1',
        pid=4242,
        result_path=result_path(outputs, 'run-1'),
        log_path=log_path(outputs, 'run-1'),
    )


def test_launch_passes_through_only_the_options_that_were_set(
    layout: tuple[Path, Path, Path], fake_popen: list[dict[str, Any]]
) -> None:
    workspace, _prompts, outputs = layout

    launch_detached(Path('s.toml'), workspace, outputs, run_id='r', config_isolation=True)
    assert '--no-config-isolation' not in fake_popen[0]['command']
    assert '--fresh' not in fake_popen[0]['command']
    assert '--resume' not in fake_popen[0]['command']

    launch_detached(
        Path('s.toml'),
        workspace,
        outputs,
        run_id='r2',
        config_isolation=False,
        fresh=True,
        resume=True,
    )
    assert '--no-config-isolation' in fake_popen[1]['command']
    assert '--fresh' in fake_popen[1]['command']
    assert '--resume' in fake_popen[1]['command']


def test_launch_detaches_from_this_process(
    layout: tuple[Path, Path, Path], fake_popen: list[dict[str, Any]]
) -> None:
    """The whole point: default inheritance would take the run down with its parent."""
    workspace, _prompts, outputs = layout

    launch_detached(Path('s.toml'), workspace, outputs, run_id='r')

    kwargs = fake_popen[0]
    if sys.platform == 'win32':
        assert kwargs['creationflags'] & subprocess.DETACHED_PROCESS
        assert kwargs['creationflags'] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert kwargs['start_new_session'] is True


def test_launch_redirects_every_standard_stream(
    layout: tuple[Path, Path, Path], fake_popen: list[dict[str, Any]]
) -> None:
    """stdin especially: an inherited stdio pipe is the server hang fixed in 0.1.1."""
    workspace, _prompts, outputs = layout

    launch_detached(Path('s.toml'), workspace, outputs, run_id='r')

    kwargs = fake_popen[0]
    assert kwargs['stdin'] == subprocess.DEVNULL
    assert kwargs['stdout'] == str(result_path(outputs, 'r'))
    assert kwargs['stderr'] == str(log_path(outputs, 'r'))


def test_launch_creates_the_outputs_dir(
    layout: tuple[Path, Path, Path], fake_popen: list[dict[str, Any]]
) -> None:
    """The child writes there before the engine would have created it."""
    workspace, _prompts, outputs = layout
    assert not outputs.exists()

    launch_detached(Path('s.toml'), workspace, outputs, run_id='r')

    assert outputs.is_dir()


def _await_result(path: Path) -> dict[str, Any]:
    """Poll ``path`` until the detached child has written a complete JSON object."""
    deadline = time.monotonic() + _CHILD_DEADLINE_S
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return dict(json.loads(path.read_text(encoding='utf-8')))
            except json.JSONDecodeError:
                pass  # Still being written.
        time.sleep(0.1)
    raise AssertionError(f'detached child wrote no result to {path} within {_CHILD_DEADLINE_S}s')


def test_a_real_detached_child_records_its_own_failure_to_start(
    layout: tuple[Path, Path, Path],
) -> None:
    """End to end, with a held lock as the guaranteed-cheap failure.

    The lock is taken at ``os.open(O_EXCL)``, before the seat probe and before any scored
    spawn, so this exercises the whole launch — interpreter resolution, flags, redirection,
    the result file — without the child being able to reach an agent.
    """
    workspace, prompts, outputs = layout
    series_file = workspace.parent / 'series.toml'
    series_file.write_text(_series_toml(prompts, outputs), encoding='utf-8')
    # Hold the workspace lock so the child fails the moment it tries to take it.
    (workspace / '.git').mkdir()
    (workspace / '.git' / 'convoy-run.lock').write_text('held by the test', encoding='utf-8')

    launch = launch_detached(series_file, workspace, outputs, run_id='detached-busy')

    envelope = _await_result(launch.result_path)
    assert envelope['ok'] is False
    assert envelope['outcome'] == 'usage'
    assert envelope['error_kind'] == 'busy'
    # Narration went to the log, never to the result file, or the envelope would not parse.
    assert launch.log_path.exists()
