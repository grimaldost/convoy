"""MCP stdio server exposing ``convoy_run``, ``convoy_gate``, ``convoy_init`` and ``convoy_status``.

The agent-facing surface: four tools an agent discovers and calls to drive a governed
multi-PR series — or to run the deterministic gate standalone over externally produced
work — mirroring the ``convoy run`` / ``convoy gate`` / ``convoy init`` / ``convoy status``
CLI verbs but returning structured dicts instead of exit codes and console text.

Local-first: ``convoy_run`` spawns a subprocess ``claude -p`` per PR, so run it co-located
with an authenticated ``claude`` CLI seat. The tools offload their blocking work via
``asyncio.to_thread`` and write nothing to stdout — the stdio server owns stdout for the
JSON-RPC stream, and all convoy progress narration goes to stderr.

Pinned ``mcp`` SDK API:

- ``from mcp.server.fastmcp import FastMCP``; ``FastMCP(name)``.
- ``@server.tool()`` registers a tool; the function's ``Annotated[T, Field(description=...)]``
  hints become the input schema each parameter's description reaches the agent through.
- ``server.run(transport='stdio')`` serves over stdio.
- ``await server.list_tools()`` is the tool-introspection API used by the schema tests.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from convoy.core.gate import GateUsageError
from convoy.core.governance import GovernanceError
from convoy.core.spec import Series, SpecError, load_series
from convoy.interface.detached import launch_detached
from convoy.interface.drivers.headless import make_run_id
from convoy.interface.gate_service import (
    gate_brief_envelope,
    gate_envelope,
    gate_usage_envelope,
    load_gate_spec_file,
    resolve_gate_spec,
    run_gate,
)
from convoy.interface.git import GitError
from convoy.interface.preflight_probe import preflight
from convoy.interface.run_service import PreflightError, run_series_headless, start_report
from convoy.interface.run_summary import error_kind, status_of, summarize_run
from convoy.interface.scaffold import ScaffoldError, scaffold
from convoy.interface.workspace_lock import WorkspaceBusyError

_SERVER_NAME = 'convoy'


def _detached_impl(
    series: Series,
    series_file: str,
    workspace: Path,
    *,
    run_id: str,
    config_isolation: bool,
    reset: bool,
    resume: bool,
) -> dict[str, Any]:
    """Start the run as a detached child and return its handle, not its result (sync).

    The free pre-flight still runs **here**, in the calling process, so a malformed series
    is answered immediately rather than discovered by polling — detaching is about not
    waiting for the run, not about deferring what can be known now. What genuinely needs
    the running process (the seat probe, the workspace lock, git) is left to the child, and
    lands in its result file; see :func:`~convoy.interface.run_summary.detached_result`.
    """
    # Only the blocking half gates a launch; the child re-runs pre-flight and records the
    # advisories on its own run_start line, so reporting them here too would double them.
    problems = start_report(series, workspace, run_id=run_id, fresh=reset, resume=resume).problems
    if problems:
        return {
            'ok': False,
            'outcome': 'usage',
            'series_id': series.id,
            'problems': [asdict(problem) for problem in problems],
        }
    outputs = Path(series.paths.outputs)
    try:
        launch = launch_detached(
            Path(series_file),
            workspace,
            outputs,
            run_id=run_id,
            config_isolation=config_isolation,
            fresh=reset,
            resume=resume,
        )
    except OSError as exc:
        return {
            'ok': False,
            'outcome': 'usage',
            'series_id': series.id,
            'error_kind': error_kind(exc),
            'error': str(exc),
        }
    return {
        # ``ok`` reports the operation, and the operation was a launch: the run itself has
        # no verdict yet. ``state`` is the same vocabulary convoy_status answers in, so a
        # caller can hand this envelope and that one to the same branch.
        'ok': True,
        'outcome': 'started',
        'state': 'running',
        'run_id': launch.run_id,
        'series_id': series.id,
        'pid': launch.pid,
        'telemetry_path': str(outputs / 'spawns.jsonl'),
        'result_path': str(launch.result_path),
        'log_path': str(launch.log_path),
        'next': (
            f'poll convoy_status with series_file={series_file} and '
            f'run_id={launch.run_id} until state is "finished"'
        ),
    }


def _run_impl(
    series_file: str,
    workspace: str,
    dry_run: bool,
    config_isolation: bool,
    reset: bool,
    resume: bool,
    detach: bool,
) -> dict[str, Any]:
    """Load, (dry-run) pre-flight, detach, or run the series, and shape a result (sync)."""
    try:
        series = load_series(Path(series_file).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, SpecError) as exc:
        return {'ok': False, 'outcome': 'usage', 'error_kind': error_kind(exc), 'error': str(exc)}

    ws = Path(workspace)
    if dry_run:
        # ``advisories`` is always present (empty when there is nothing to say) so a
        # consumer can read the key unconditionally. It never affects ``ok``/``outcome``:
        # advice describes an unusual series, not an invalid one.
        report = preflight(series, ws)
        return {
            'ok': report.clean,
            'outcome': 'validated' if report.clean else 'usage',
            'series_id': series.id,
            'problems': [asdict(p) for p in report.problems],
            'advisories': [asdict(a) for a in report.advisories],
        }

    run_id = make_run_id()
    if detach:
        return _detached_impl(
            series,
            series_file,
            ws,
            run_id=run_id,
            config_isolation=config_isolation,
            reset=reset,
            resume=resume,
        )

    try:
        outcome = run_series_headless(
            series,
            ws,
            run_id=run_id,
            config_isolation=config_isolation,
            fresh=reset,
            resume=resume,
        )
    except PreflightError as exc:
        return {
            'ok': False,
            'outcome': 'usage',
            'series_id': series.id,
            'problems': [asdict(p) for p in exc.problems],
        }
    except (GovernanceError, GitError, WorkspaceBusyError, OSError) as exc:
        return {
            'ok': False,
            'outcome': 'usage',
            'series_id': series.id,
            'error_kind': error_kind(exc),
            'error': str(exc),
        }

    return summarize_run(
        Path(series.paths.outputs) / 'spawns.jsonl',
        run_id=run_id,
        series_id=series.id,
        outcome=outcome,
    )


def _init_impl(directory: str) -> dict[str, Any]:
    """Scaffold a starter series and name the paths to hand to ``convoy_run`` (sync)."""
    try:
        written = scaffold(Path(directory))
    except (OSError, ScaffoldError) as exc:
        return {'ok': False, 'error': str(exc)}
    root = Path(directory)
    return {
        'ok': True,
        'created': [str(p) for p in written],
        'series_file': str(root / 'series.toml'),
        'workspace': str(root / 'workspace'),
        'next': (
            f'call convoy_run with series_file={root / "series.toml"} '
            f'and workspace={root / "workspace"} (add dry_run=true first for a free check)'
        ),
    }


async def convoy_run(
    series_file: Annotated[
        str,
        Field(
            description=(
                'Absolute path to the convoy series.toml to run. A relative path resolves '
                "against the server's working directory (not the caller's), so prefer absolute."
            )
        ),
    ],
    workspace: Annotated[
        str,
        Field(
            description=(
                'Absolute path to the git repository to operate in (the scored tree). The '
                "series is staged on its base branch here; each PR's branch and the "
                'integration branch are created in this repo. A relative path resolves against '
                "the server's working directory, so prefer absolute."
            )
        ),
    ],
    dry_run: Annotated[
        bool,
        Field(
            description=(
                'When true, only pre-flight the series (structure, paths, gate isolation) and '
                'return {ok, outcome, problems}: no git mutation, no agent spawn, no spend. '
                'Do this before a real run.'
            )
        ),
    ] = False,
    config_isolation: Annotated[
        bool,
        Field(
            description=(
                'When true (default), the scored agent runs under a credential-only '
                'CLAUDE_CONFIG_DIR so the operator settings, hooks, plugins, and memory never '
                'leak into the run. Turn off only to deliberately run under the operator config.'
            )
        ),
    ] = True,
    reset: Annotated[
        bool,
        Field(
            description=(
                'DESTRUCTIVE. Restore the workspace to base before running — discard '
                'uncommitted changes to tracked files, delete untracked files, then delete '
                'the prior integration and PR branches — so a completed or halted run can be '
                're-run cleanly. These are the same steps `convoy clean` performs; a budget '
                'or infrastructure halt leaves uncommitted work that branch deletion alone '
                'cannot clear. Off by default: a leftover branch then fails loud exactly as '
                'without this flag, and nothing in the tree is touched.'
            )
        ),
    ] = False,
    resume: Annotated[
        bool,
        Field(
            description=(
                'Continue the existing integration branch instead of creating one, skipping '
                'every PR whose work it already contains, so a halted run does not re-spend '
                'on PRs that already gated green. Mutually exclusive with reset; resuming '
                'when no integration branch exists is a pre-flight problem.'
            )
        ),
    ] = False,
    detach: Annotated[
        bool,
        Field(
            description=(
                'Start the run as a detached child process and return a handle immediately '
                '({outcome: "started", run_id, telemetry_path, result_path, log_path}) '
                'instead of blocking for the whole series. Follow it with convoy_status '
                'using the returned run_id. The run survives this server exiting. Pre-flight '
                'still runs here, so a malformed series is refused immediately.'
            )
        ),
    ] = False,
) -> dict[str, Any]:
    """Run a governed multi-PR series to an integrated branch; return an economy + gate summary.

    Drives a coding agent (subprocess ``claude -p``) through each PR in the series'
    dependency order: implement under a per-phase budget, gate the result against the
    series' ``[[checks]]``, repair on a blocking-red gate (bounded by ``max_fix_attempts``),
    and merge a green PR onto the integration branch before the next PR branches from it. A
    blocking red that is never repaired halts the series; later PRs are skipped, not run.

    Returns the run ``outcome`` (``completed`` | ``blocked`` | ``infrastructure`` |
    ``budget`` for an executed run; ``validated`` | ``usage`` for a ``dry_run`` or a spec /
    pre-flight failure), the ``exit_code``, per-spawn ``economy`` totals, and a per-PR view
    carrying the ``effective_model`` the PR's implementation spawn ran under (``null`` if it
    never spawned) alongside its ``gate`` verdict. The full append-only per-spawn trace stays
    on disk at the returned ``telemetry_path`` — read it for per-line detail. See the convoy
    skill for the full result envelope and the series.toml schema.

    COST & LATENCY: a real run SPENDS real model budget and takes minutes to hours — it
    spawns one or more nested agents per PR. Pass ``dry_run=True`` first for a free,
    side-effect-free pre-flight. Pass ``detach=True`` to start the run and get a handle
    back at once rather than holding this call open for the whole series; then poll
    ``convoy_status`` with the returned ``run_id``.

    REQUIREMENTS: ``series_file`` is a convoy series.toml (use ``convoy_init`` for a runnable
    example); ``workspace`` is an existing git repo whose base branch the series names; the
    series' ``[paths]`` must be absolute and its ``outputs`` dir out-of-tree. Run co-located
    with an authenticated ``claude`` CLI seat.

    Parameters:
      - ``series_file`` — absolute path to the series.toml to run.
      - ``workspace`` — absolute path to the git repo to operate in (the scored tree).
      - ``dry_run`` — pre-flight only, no spend, no mutation. Do this first.
      - ``config_isolation`` — run the scored agent under an isolated credential-only config
        dir (default true).
      - ``reset`` — reset the workspace to base and delete prior integration/PR branches
        before running, so a completed or halted run can be re-run cleanly (default false).
      - ``resume`` — continue the existing integration branch, skipping every PR already
        merged into it, so a halted run does not re-spend on its green PRs (default false).
        Each skipped PR is recorded with a ``pr_skipped`` reason distinct from the halt
        reasons. Mutually exclusive with ``reset``.
      - ``detach`` — start the run and return at once with ``outcome: "started"`` plus the
        ``run_id`` to poll, the ``telemetry_path``, and the ``result_path`` / ``log_path``
        the detached run writes (default false). The run outlives this server. ``dry_run``
        takes precedence: a pre-flight is free and instant, so there is nothing to detach.
    """
    return await asyncio.to_thread(
        _run_impl, series_file, workspace, dry_run, config_isolation, reset, resume, detach
    )


def _gate_impl(
    workspace: str, series_file: str | None, phases: list[str], brief: bool
) -> dict[str, Any]:
    """Resolve and load the gate spec, run the checks once, shape a result (sync).

    Every failure returns a usage envelope, never raises: an exception escaping here
    becomes a protocol-level tool error with no ``outcome`` to branch on. ``OSError``
    around ``run_gate`` is the workspace-shaped one — a path that is missing or a file
    surfaces from ``Popen(cwd=...)``, and it is the single most likely caller mistake.
    With no ``series_file`` the project spec is discovered from the workspace (the
    tool has no meaningful cwd of its own), the same rule as ``convoy gate``.
    """
    try:
        explicit = None if series_file is None else Path(series_file)
        spec_path = resolve_gate_spec(explicit, Path(workspace), os.environ)
        spec = load_gate_spec_file(spec_path, os.environ)
    except (OSError, UnicodeDecodeError, SpecError) as exc:
        return gate_usage_envelope(exc, error_kind=error_kind(exc))
    try:
        outcome = run_gate(spec, Path(workspace), tuple(phases))
    except (GateUsageError, OSError) as exc:
        return gate_usage_envelope(exc, error_kind=error_kind(exc), series_id=spec.id)
    if brief:
        return gate_brief_envelope(outcome)
    return gate_envelope(spec, Path(workspace), outcome)


async def convoy_gate(
    workspace: Annotated[
        str,
        Field(
            description=(
                'Absolute path to the tree to gate — the workspace the check commands run '
                'in. Convoy writes nothing, creates no branch and takes no lock, but the '
                'check commands themselves run in the tree and may write (caches, build '
                'output) — so never gate a workspace a convoy_run is actively driving: '
                'its commit step stages the whole tree and can commit gate artifacts '
                'into a scored branch.'
            )
        ),
    ],
    series_file: Annotated[
        str | None,
        Field(
            description=(
                'Optional absolute path to the file holding the [[checks]] to run: a full '
                'convoy series.toml, or a minimal file carrying only [series] id and '
                '[[checks]]. Omitted, the project gate spec is used — '
                '$CLAUDE_PROJECT_DIR/.convoy/gate.toml, then .convoy/gate.toml in the '
                'workspace and its parents; none found is a usage result. A relative '
                'path resolves against the server working directory, so prefer absolute.'
            )
        ),
    ] = None,
    phases: Annotated[
        list[str] | None,
        Field(
            description=(
                'Optional phase tags. Empty runs the whole gate; tags run exactly the '
                'checks a PR carrying them would be gated on (the unscoped checks plus '
                'the ones scoped to a named tag). A tag no check declares is refused as '
                'a usage error, not silently narrowed to a green.'
            )
        ),
    ] = None,
    brief: Annotated[
        bool,
        Field(
            description=(
                'Return the compact envelope {ok, outcome, repair_brief, convoy_version} '
                'instead of the full one — for reading the verdict inside a model turn '
                'with nothing else in it. Usage results are unchanged.'
            )
        ),
    ] = False,
) -> dict[str, Any]:
    """Run a series' ``[[checks]]`` against a workspace once — the gate without the run.

    The deterministic gate standalone, for verifying work produced OUTSIDE convoy — an
    externally orchestrated implementation, a hand-written branch — with the same check
    commands, the same fail-closed independence guard, and the same verdict rules a
    governed run applies after every PR. No agent spawns, no git mutation, no telemetry,
    no spend beyond the check commands themselves.

    Returns the gate envelope: ``ok``, ``outcome`` (``completed`` | ``blocked`` |
    ``usage``), ``series_id``, ``workspace``, ``phases``, per-check verdicts with a
    failure ``detail`` a repair can be briefed with, ``blocking_red`` /
    ``independent_red``, ``repair_brief`` (the ready-to-append failing-checks section,
    the same text convoy briefs its own fix spawn with; ``''`` when green), ``counts``,
    the CLI-equivalent ``exit_code`` (0 green — a non-blocking red advises without
    blocking — 1 blocking red), and ``convoy_version``. The CLI twin is ``convoy gate``;
    both emit this same envelope. With ``brief=true`` only ``ok``, ``outcome``,
    ``repair_brief`` and ``convoy_version`` come back. With no ``series_file`` the
    project's ``.convoy/gate.toml`` is discovered from the workspace.
    """
    return await asyncio.to_thread(_gate_impl, workspace, series_file, phases or [], brief)


async def convoy_init(
    directory: Annotated[
        str,
        Field(
            description=(
                'Directory to scaffold the starter series into; may be relative or absolute '
                "(a relative path resolves against the server's working directory), and is "
                'created (with parent dirs) if absent. Must not already contain the starter '
                'files (series.toml, prompts/, oracles/, workspace/) — it refuses to overwrite '
                'rather than clobber. Scaffolds <directory>/{series.toml, prompts/, oracles/, '
                'workspace/}.'
            )
        ),
    ],
) -> dict[str, Any]:
    """Scaffold a runnable starter convoy series in a directory; return the created paths.

    Writes a self-contained example: a ``series.toml``, a prompt, an out-of-tree oracle for a
    blocking *independent* check (the ``asset`` field in action), and a git-initialized
    ``workspace/`` committed on the base branch. The result names the ``series_file`` and
    ``workspace`` to hand straight to ``convoy_run``. Use it to get a correct, copyable series
    to adapt, or to smoke-test the tools end to end (``convoy_init`` then ``convoy_run`` with
    ``dry_run=true``).

    Returns ``{ ok, created, series_file, workspace, next }``: ``created`` is the list of
    paths written, and ``next`` is a suggested follow-up ``convoy_run`` call.

    Parameters:
      - ``directory`` — where to scaffold (relative or absolute, created if absent); must not
        already contain the starter files.
    """
    return await asyncio.to_thread(_init_impl, directory)


def _status_impl(series_file: str, run_id: str, workspace: str) -> dict[str, Any]:
    """Load the series and read its ledger for the run's state (sync).

    An empty ``workspace`` is not guessed at: the server's working directory is not the
    caller's, so a cwd fallback would read a lock belonging to some other tree. Without one,
    the answer is what it always was — a run with no terminal record reads ``running``.
    """
    try:
        series = load_series(Path(series_file).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, SpecError) as exc:
        return {'ok': False, 'outcome': 'usage', 'error_kind': error_kind(exc), 'error': str(exc)}
    return status_of(series, run_id=run_id, workspace=Path(workspace) if workspace else None)


async def convoy_status(
    series_file: Annotated[
        str,
        Field(
            description=(
                'Absolute path to the series.toml whose run you want the state of. Its '
                '[paths].outputs is where convoy wrote the ledger, which is the only thing '
                'this reads.'
            )
        ),
    ],
    run_id: Annotated[
        str,
        Field(
            description=(
                'Which run to report. Defaults to the most recent run recorded in the '
                'ledger, which is usually what a poller means; pass an explicit id to '
                'follow one particular run in an outputs dir that accumulates several.'
            )
        ),
    ] = '',
    workspace: Annotated[
        str,
        Field(
            description=(
                'Absolute path to the git repository the run operates on. Optional, and read '
                'for exactly one thing: the run lock there names its owner process, which is '
                'what separates a run still going from one whose driver died. Nothing is '
                'written. Omit it and a run with no terminal record reads "running", as '
                'before — so pass it whenever you want "dead" to be answerable.'
            )
        ),
    ] = '',
) -> dict[str, Any]:
    """Report a convoy run's state and economy so far — including one still in progress.

    Reads the append-only ledger, so it works for a run **this server never started**:
    the supported long-run pattern is ``convoy run`` in a background shell, and this is how
    you ask that run how it is doing. It spends nothing, holds no state between calls, and
    writes nothing, so polling is cheap and safe.

    Returns the same envelope ``convoy_run`` does, plus a **``state``** to branch on first:

      - ``running`` — no ``run_complete`` line yet. ``outcome`` / ``integrated`` /
        ``exit_code`` are ``null`` and the ``economy`` is a partial running total (what it
        has spent so far), which is the useful thing to watch.
      - ``dead`` — no ``run_complete`` line and the process that would have written one is
        gone (the workspace lock names a pid that no longer exists). The terminal fields are
        ``null`` and will stay that way; the economy is final, not partial. Only reachable
        when ``workspace`` is passed. ``message`` says how to recover.
      - ``finished`` — the terminal fields are meaningful, exactly as from ``convoy_run``,
        including ``halt`` on a non-completed run.
      - ``unknown`` — nothing recorded under that id (or an empty/absent ledger). Not an
        error: a run that has not written its first line yet is a legitimate state.

    Parameters:
      - ``series_file`` — absolute path to the series.toml whose outputs hold the ledger.
      - ``run_id`` — the run to report; defaults to the most recent one recorded.
      - ``workspace`` — absolute path to the run's git repo; pass it to make ``dead``
        answerable. Optional, read-only, never guessed.
    """
    return await asyncio.to_thread(_status_impl, series_file, run_id, workspace)


def build_server() -> FastMCP:
    """Construct the server with the ``run`` / ``gate`` / ``init`` / ``status`` tools registered."""
    server = FastMCP(_SERVER_NAME)
    server.tool()(convoy_run)
    server.tool()(convoy_gate)
    server.tool()(convoy_init)
    server.tool()(convoy_status)
    return server
