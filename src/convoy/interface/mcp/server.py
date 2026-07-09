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
import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from convoy.core.governance import GovernanceError
from convoy.core.spec import SpecError, load_series
from convoy.interface.drivers.headless import RunOutcome, make_run_id
from convoy.interface.git import GitError
from convoy.interface.preflight_probe import preflight
from convoy.interface.run_service import PreflightError, run_series_headless
from convoy.interface.scaffold import ScaffoldError, scaffold
from convoy.interface.workspace_lock import WorkspaceBusyError

_SERVER_NAME = 'convoy'

# Cap the per-PR list projected inline; the full trace always stays on disk (§ telemetry_path).
_PR_CAP = 50


def summarize_run(
    telemetry_path: Path,
    *,
    run_id: str,
    series_id: str,
    outcome: RunOutcome,
    pr_cap: int = _PR_CAP,
) -> dict[str, Any]:
    """Fold this run's telemetry lines into an agent-facing summary.

    Reads ``telemetry_path`` (convoy's append-only ``spawns.jsonl``), keeps only the lines
    tagged with ``run_id``, and aggregates them into economy totals and a per-PR view
    (spawn count, the latest gate verdict, any skip reason). The complete per-line trace
    stays on disk at ``telemetry_path`` — referenced here, never inlined. The per-PR list
    is capped at ``pr_cap`` with a ``truncated`` report.
    """
    economy = {
        'total_cost_usd': 0.0,
        'cost_estimated': False,
        'input_tokens': 0,
        'output_tokens': 0,
        'num_turns': 0,
        'spawn_count': 0,
    }
    prs: dict[str, dict[str, Any]] = {}

    def _pr(pr_id: str) -> dict[str, Any]:
        return prs.setdefault(
            pr_id,
            {'pr_id': pr_id, 'spawns': 0, 'gate': None, 'skipped': False, 'skip_reason': None},
        )

    if telemetry_path.exists():
        for line in telemetry_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get('run_id') != run_id:
                continue
            event = entry.get('event')
            if event == 'spawn_complete':
                economy['total_cost_usd'] += entry['cost_usd']
                economy['input_tokens'] += entry['input_tokens']
                economy['output_tokens'] += entry['output_tokens']
                economy['num_turns'] += entry['num_turns']
                economy['spawn_count'] += 1
                economy['cost_estimated'] = economy['cost_estimated'] or entry.get(
                    'cost_estimated', False
                )
                _pr(entry['pr_id'])['spawns'] += 1
            elif event == 'gate_complete':
                _pr(entry['pr_id'])['gate'] = {
                    'attempt': entry['attempt'],
                    'blocking_red': entry['blocking_red'],
                    'independent_red': entry['independent_red'],
                    'failing_checks': [
                        c['name'] for c in entry['checks'] if not c['passed'] and c['blocking']
                    ],
                }
            elif event == 'pr_skipped':
                pr = _pr(entry['pr_id'])
                pr['skipped'] = True
                pr['skip_reason'] = entry['reason']

    pr_list = list(prs.values())
    return {
        'ok': outcome.outcome == 'completed',
        'outcome': outcome.outcome,
        'integrated': outcome.integrated,
        'exit_code': outcome.exit_code,
        'run_id': run_id,
        'series_id': series_id,
        'economy': economy,
        'prs': pr_list[:pr_cap],
        'telemetry_path': str(telemetry_path),
        'truncated': {'any': len(pr_list) > pr_cap, 'prs': max(0, len(pr_list) - pr_cap)},
    }


def _error_kind(exc: Exception) -> str:
    """Classify a could-not-start failure so an agent can branch on it, not parse a string.

    One of ``spec`` (invalid, malformed, or undecodable series), ``governance``
    (unresolvable model/tier at runtime), ``git`` (a git operation failed), ``busy``
    (another run holds the workspace lock), or ``filesystem`` (any other ``OSError``).
    """
    if isinstance(exc, SpecError | UnicodeDecodeError):
        return 'spec'
    if isinstance(exc, GovernanceError):
        return 'governance'
    if isinstance(exc, GitError):
        return 'git'
    if isinstance(exc, WorkspaceBusyError):
        return 'busy'
    return 'filesystem'


def _run_impl(
    series_file: str, workspace: str, dry_run: bool, config_isolation: bool, reset: bool
) -> dict[str, Any]:
    """Load, (dry-run) pre-flight or run the series, and shape a structured result (sync)."""
    try:
        series = load_series(Path(series_file).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, SpecError) as exc:
        return {'ok': False, 'outcome': 'usage', 'error_kind': _error_kind(exc), 'error': str(exc)}

    ws = Path(workspace)
    if dry_run:
        problems = preflight(series, ws)
        return {
            'ok': not problems,
            'outcome': 'validated' if not problems else 'usage',
            'series_id': series.id,
            'problems': [asdict(p) for p in problems],
        }

    run_id = make_run_id()
    try:
        outcome = run_series_headless(
            series, ws, run_id=run_id, config_isolation=config_isolation, fresh=reset
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
            'error_kind': _error_kind(exc),
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
) -> dict[str, Any]:
    """Run a governed multi-PR series to an integrated branch; return an economy + gate summary.

    Drives a coding agent (subprocess ``claude -p``) through each PR in the series'
    dependency order: implement under a per-phase budget, gate the result against the
    series' ``[[checks]]``, repair on a blocking-red gate (bounded by ``max_fix_attempts``),
    and merge a green PR onto the integration branch before the next PR branches from it. A
    blocking red that is never repaired halts the series; later PRs are skipped, not run.

    Returns the run ``outcome`` (``completed`` | ``blocked`` | ``infrastructure`` |
    ``budget`` for an executed run; ``validated`` | ``usage`` for a ``dry_run`` or a spec /
    pre-flight failure), the ``exit_code``, per-spawn ``economy`` totals, and a per-PR
    ``gate`` view. The full append-only per-spawn trace stays on disk at the returned
    ``telemetry_path`` — read it for per-line detail. See the convoy skill for the full
    result envelope and the series.toml schema.

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
    """
    return await asyncio.to_thread(
        _run_impl, series_file, workspace, dry_run, config_isolation, reset
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


def build_server() -> FastMCP:
    """Construct the MCP server with the ``convoy_run`` and ``convoy_init`` tools registered."""
    server = FastMCP(_SERVER_NAME)
    server.tool()(convoy_run)
    server.tool()(convoy_init)
    return server
