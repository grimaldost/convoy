"""Integration test: the MCP tools return over a REAL stdio server subprocess.

This is the regression guard for the 0.1.1 blocker. ``convoy_init`` (and any tool that
shells out to git) must not hang the client: under a stdio MCP server, a git subprocess
that leaves a background daemon or inherits the server's JSON-RPC pipe keeps ``subprocess``
from ever seeing EOF, so the tool response never returns. The unit tests in
``test_mcp_server.py`` call the tool coroutines directly (no transport, no
subprocess-under-stdio), so they cannot catch this; this test drives an actual
``python -m convoy.interface.mcp`` server over stdio and asserts the calls come back.

It is also the guard for the *registration* half of the serving surface, which the unit
tests likewise bypass: every tool is discovered by name and called over the wire, and the
two envelope facts a consumer branches on — ``convoy_version`` and ``convoy_status``'s
``state`` — are read back off the transport rather than off a coroutine's return value. An
SDK upgrade that quietly stops registering a tool, or that reshapes what reaches the
client, fails here instead of in a caller months later.

``convoy_run`` is exercised on its ``dry_run`` branch only: a real run spawns agents and
spends, which a test suite must not do.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from convoy import __version__

# A gate-only spec: [series] id plus one always-green check. TOML literal strings (single
# quotes) keep a Windows interpreter path from being read as escape sequences.
_GATE_SPEC = """\
[series]
id = "stdio-gate"

[[checks]]
name = "noop"
run = '"{python}" -c pass'
blocking = true
independent = false
"""


async def _drive(demo: Path, gate_spec: Path) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """Discover and call all four tools over one stdio session; return names and envelopes."""
    params = StdioServerParameters(command=sys.executable, args=['-m', 'convoy.interface.mcp'])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        advertised = {tool.name for tool in (await session.list_tools()).tools}

        init = await session.call_tool('convoy_init', {'directory': str(demo)})
        series_file = init.structured_content['series_file']
        run = await session.call_tool(
            'convoy_run',
            {
                'series_file': series_file,
                'workspace': init.structured_content['workspace'],
                'dry_run': True,
            },
        )
        gate = await session.call_tool(
            'convoy_gate',
            {'workspace': init.structured_content['workspace'], 'series_file': str(gate_spec)},
        )
        status = await session.call_tool('convoy_status', {'series_file': series_file})
        envelopes = {
            'convoy_init': init.structured_content,
            'convoy_run': run.structured_content,
            'convoy_gate': gate.structured_content,
            'convoy_status': status.structured_content,
        }
        return advertised, envelopes


def test_every_tool_answers_over_a_real_stdio_server(tmp_path: Path) -> None:
    # Pre-0.1.1 this hung forever: convoy_init scaffolds a git repo, and the git subprocess
    # under the stdio server never let the response return. The timeout turns a regression
    # into a test failure instead of a hung suite.
    demo = tmp_path / 'demo'
    gate_spec = tmp_path / 'gate.toml'
    gate_spec.write_text(_GATE_SPEC.format(python=Path(sys.executable).as_posix()), 'utf-8')

    advertised, envelopes = asyncio.run(asyncio.wait_for(_drive(demo, gate_spec), timeout=90))

    assert advertised == {'convoy_run', 'convoy_gate', 'convoy_init', 'convoy_status'}

    init = envelopes['convoy_init']
    assert init['ok'] is True
    assert (demo / 'series.toml').is_file()
    assert (demo / 'workspace').is_dir()

    # And the git-free dry_run on the scaffolded series validates through the same server.
    run = envelopes['convoy_run']
    assert run['ok'] is True
    assert run['outcome'] == 'validated'

    # The gate shells out too, and does it under the stdio server — the same hang class as
    # convoy_init's git, on the surface an external orchestrator calls most.
    gate = envelopes['convoy_gate']
    assert gate['ok'] is True
    assert gate['outcome'] == 'completed'
    assert gate['convoy_version'] == __version__

    # Nothing has run in this outputs dir, which is a state and not an error.
    status = envelopes['convoy_status']
    assert status['state'] == 'unknown'
    assert status['convoy_version'] == __version__
