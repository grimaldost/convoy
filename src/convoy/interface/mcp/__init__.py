"""The convoy MCP server package — the agent-facing surface (stdio).

Exposes convoy's actions as MCP tools so a Claude Code plugin (or any MCP client) can
discover and drive a governed series without shelling out. Start it with
``python -m convoy.interface.mcp``; the tools are built in :mod:`convoy.interface.mcp.server`.
"""
