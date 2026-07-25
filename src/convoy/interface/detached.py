"""Launching a run that outlives the process that started it (shell).

``convoy run`` blocks for the length of a series — minutes to hours — which is fine for a
shell the operator owns and wrong for an MCP tool call, where the agent on the other end
has to sit through it. This module starts the same CLI as a detached child and returns a
handle immediately; the run is then followed with ``convoy_status``, which answers from the
ledger and so never needed to be the process that started it.

The child is convoy's own CLI, invoked as ``sys.executable -m convoy run --json``, not a
second engine wiring: one run path stays one run path, and ``--json`` means the child
records its own verdict — including a failure to start — as one object on disk.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from convoy.interface.proc import TEXT_ENCODING


@dataclass(frozen=True)
class Launch:
    """A started detached run: the id to poll it by, and where it writes."""

    run_id: str
    pid: int
    result_path: Path
    log_path: Path


def result_path(outputs: Path, run_id: str) -> Path:
    """Where a detached run writes its final envelope (the child's ``--json`` stdout).

    Derived from the run id rather than tracked, so any process that knows the id can find
    it — the launching process holds no state, exactly as ``convoy_status`` holds none.
    """
    return outputs / f'{run_id}.json'


def log_path(outputs: Path, run_id: str) -> Path:
    """Where a detached run writes its progress narration (the child's stderr)."""
    return outputs / f'{run_id}.log'


def _detach_kwargs() -> dict[str, Any]:
    """Platform flags that keep the child alive after this process exits.

    POSIX: ``start_new_session`` puts the child in its own session, so it has no
    controlling terminal to be hung up on and is reparented to init when we exit.

    Windows: ``DETACHED_PROCESS`` gives it no console (a console it shared would deliver
    close events to it), and ``CREATE_NEW_PROCESS_GROUP`` keeps a Ctrl-C aimed at this
    process out of its group.

    Neither escapes a **job object**: a host that confines its children to a job with
    kill-on-close still takes the run down when it exits. Convoy does not attempt
    ``CREATE_BREAKAWAY_FROM_JOB`` — that limit is usually a deliberate host policy, and
    breaking out of it silently would be worse than honouring it. A run killed that way
    stops advancing, which is what ``convoy_status`` reports.
    """
    if sys.platform == 'win32':
        return {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


def launch_detached(
    series_file: Path,
    workspace: Path,
    outputs: Path,
    *,
    run_id: str,
    config_isolation: bool = True,
    fresh: bool = False,
    resume: bool = False,
) -> Launch:
    """Start ``convoy run`` for ``series_file`` as a detached child and return its handle.

    ``run_id`` is minted by the caller and pinned with ``--run-id``, because a handle the
    caller cannot poll by is not a handle: the child cannot be asked afterwards what id it
    chose. The outputs dir is created first — the child writes its result and log there
    before the engine would have created it.

    Standard streams are all redirected: **stdin** to devnull (a child holding an inherited
    stdin pipe is the stdio-server hang of 0.1.1), **stdout** to
    :func:`result_path` — under ``--json`` that is exactly one envelope, on every path,
    including a run that could not start — and **stderr** to :func:`log_path`, which is
    where the progress narration goes.

    Raises ``OSError`` if the child cannot be started at all (a missing interpreter, an
    unwritable outputs dir). Anything that fails *after* it starts is the child's own
    verdict, and lands in the result file rather than here.
    """
    outputs.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        '-m',
        'convoy',
        'run',
        str(series_file),
        '--workspace',
        str(workspace),
        '--run-id',
        run_id,
        '--json',
    ]
    if not config_isolation:
        command.append('--no-config-isolation')
    if fresh:
        command.append('--fresh')
    if resume:
        command.append('--resume')

    result = result_path(outputs, run_id)
    log = log_path(outputs, run_id)
    with (
        result.open('w', encoding=TEXT_ENCODING) as result_stream,
        log.open('w', encoding=TEXT_ENCODING) as log_stream,
    ):
        child = subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=result_stream,
            stderr=log_stream,
            **_detach_kwargs(),
        )
    return Launch(run_id=run_id, pid=child.pid, result_path=result, log_path=log)
