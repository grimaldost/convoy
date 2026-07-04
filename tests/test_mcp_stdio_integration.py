"""Integration test: the MCP tools return over a REAL stdio server subprocess.

This is the regression guard for the 0.1.1 blocker. ``convoy_init`` (and any tool that
shells out to git) must not hang the client: under a stdio MCP server, a git subprocess
that leaves a background daemon or inherits the server's JSON-RPC pipe keeps ``subprocess``
from ever seeing EOF, so the tool response never returns. The unit tests in
``test_mcp_server.py`` call the tool coroutines directly (no transport, no
subprocess-under-stdio), so they cannot catch this; this test drives an actual
``python -m convoy.interface.mcp`` server over stdio and asserts the calls come back.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _drive(demo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    params = StdioServerParameters(command=sys.executable, args=['-m', 'convoy.interface.mcp'])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        init = await session.call_tool('convoy_init', {'directory': str(demo)})
        run = await session.call_tool(
            'convoy_run',
            {
                'series_file': init.structuredContent['series_file'],
                'workspace': init.structuredContent['workspace'],
                'dry_run': True,
            },
        )
        return init.structuredContent, run.structuredContent


def test_git_shelling_tool_returns_over_a_real_stdio_server(tmp_path: Path) -> None:
    # Pre-0.1.1 this hung forever: convoy_init scaffolds a git repo, and the git subprocess
    # under the stdio server never let the response return. The timeout turns a regression
    # into a test failure instead of a hung suite.
    demo = tmp_path / 'demo'
    init, run = asyncio.run(asyncio.wait_for(_drive(demo), timeout=90))

    assert init['ok'] is True
    assert (demo / 'series.toml').is_file()
    assert (demo / 'workspace').is_dir()
    # And the git-free dry_run on the scaffolded series validates through the same server.
    assert run['ok'] is True
    assert run['outcome'] == 'validated'
