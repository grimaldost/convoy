"""Entry point: ``python -m convoy.interface.mcp``.

Starts the stdio MCP server so a Claude Code plugin (or any MCP client) can register the
``convoy_run`` / ``convoy_init`` tools. In-process Python — never a blocked ``.exe`` shim.
"""

from __future__ import annotations

from convoy.interface.mcp.server import build_server
from convoy.interface.streams import harden_std_streams


def main() -> None:
    """Run the MCP server over stdio."""
    harden_std_streams()
    build_server().run(transport='stdio')


if __name__ == '__main__':
    main()
