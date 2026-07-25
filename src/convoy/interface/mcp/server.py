"""MCP stdio server exposing convoy's ``convoy_run`` and ``convoy_init`` tools.

The agent-facing surface: two tools an agent discovers and calls to drive a governed
multi-PR series, mirroring the ``convoy run`` / ``convoy init`` CLI verbs but returning
structured dicts instead of exit codes and console text.

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
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from convoy.core.governance import GovernanceError
from convoy.core.spec import SpecError, load_series
from convoy.interface.drivers.headless import make_run_id
from convoy.interface.git import GitError
from convoy.interface.preflight_probe import preflight
from convoy.interface.run_service import PreflightError, run_series_headless
from convoy.interface.run_summary import error_kind, status_of, summarize_run
from convoy.interface.scaffold import ScaffoldError, scaffold
from convoy.interface.workspace_lock import WorkspaceBusyError

_SERVER_NAME = 'convoy'


def _run_impl(
    series_file: str,
    workspace: str,
    dry_run: bool,
    config_isolation: bool,
    reset: bool,
    resume: bool,
) -> dict[str, Any]:
    """Load, (dry-run) pre-flight or run the series, and shape a structured result (sync)."""
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
                'Reset the workspace to base and delete prior integration/PR branches before '
                'running, so a completed or halted run can be re-run cleanly. Off by default: '
                'a leftover branch still fails loud exactly as without this flag.'
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
    side-effect-free pre-flight.

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
    """
    return await asyncio.to_thread(
        _run_impl, series_file, workspace, dry_run, config_isolation, reset, resume
    )


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


def _status_impl(series_file: str, run_id: str) -> dict[str, Any]:
    """Load the series and read its ledger for the run's state (sync)."""
    try:
        series = load_series(Path(series_file).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, SpecError) as exc:
        return {'ok': False, 'outcome': 'usage', 'error_kind': error_kind(exc), 'error': str(exc)}
    return status_of(series, run_id=run_id)


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
) -> dict[str, Any]:
    """Report a convoy run's state and economy so far — including one still in progress.

    Reads only the append-only ledger, so it works for a run **this server never started**:
    the supported long-run pattern is ``convoy run`` in a background shell, and this is how
    you ask that run how it is doing. It spends nothing, holds no state between calls, and
    never touches the workspace, so polling is cheap and safe.

    Returns the same envelope ``convoy_run`` does, plus a **``state``** to branch on first:

      - ``running`` — no ``run_complete`` line yet. ``outcome`` / ``integrated`` /
        ``exit_code`` are ``null`` and the ``economy`` is a partial running total (what it
        has spent so far), which is the useful thing to watch.
      - ``finished`` — the terminal fields are meaningful, exactly as from ``convoy_run``,
        including ``halt`` on a non-completed run.
      - ``unknown`` — nothing recorded under that id (or an empty/absent ledger). Not an
        error: a run that has not written its first line yet is a legitimate state.

    Parameters:
      - ``series_file`` — absolute path to the series.toml whose outputs hold the ledger.
      - ``run_id`` — the run to report; defaults to the most recent one recorded.
    """
    return await asyncio.to_thread(_status_impl, series_file, run_id)


def build_server() -> FastMCP:
    """Construct the MCP server with convoy's ``run`` / ``init`` / ``status`` tools registered."""
    server = FastMCP(_SERVER_NAME)
    server.tool()(convoy_run)
    server.tool()(convoy_init)
    server.tool()(convoy_status)
    return server
