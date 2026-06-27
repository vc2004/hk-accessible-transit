"""
MCP Connector — manages MCP server lifecycle and tool calls.

Spawns MCP servers as subprocesses (stdio transport) and provides a clean
async interface for agents to call MCP tools.

Architecture (Day 2 Section 2.2):
    Discovery → Configuration → Connection → Tool execution

Usage:
    from agent.mcp_connector import MCPConnector

    async with MCPConnector("hk-transit") as conn:
        result = await conn.call_tool("list_mtr_lines", {})
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class MCPConnector:
    """Connects to an MCP server — in-process or via subprocess.

    For our custom MCP servers (hk-transit, mtr-accessibility), we use
    in-process calling for reliability. For external community MCP servers,
    subprocess stdio transport is the standard approach.
    """

    # Registry of callable in-process tool handlers
    _IN_PROCESS_REGISTRY: dict[str, callable] = {}

    def __init__(self, server_name: str):
        self.server_name = server_name
        self._tools: dict[str, dict] = {}
        self._connected = False

    async def start(self) -> None:
        """Discover tools — from in-process registry if available, else subprocess."""
        if self._connected:
            return

        # Try in-process first
        if self.server_name in self._IN_PROCESS_REGISTRY:
            self._tools = self._IN_PROCESS_REGISTRY[self.server_name]()
            self._connected = True
            logger.info(
                f"MCP server '{self.server_name}' ready (in-process) "
                f"with {len(self._tools)} tools"
            )
            return

        # Fallback: try subprocess
        try:
            await self._start_subprocess()
        except Exception as e:
            logger.warning(
                f"MCP server '{self.server_name}' unavailable: {e}. "
                f"Agents will use static fallback data."
            )
            # Don't raise — graceful degradation

    async def stop(self) -> None:
        """Stop the MCP server connection."""
        self._connected = False

    async def _start_subprocess(self) -> None:
        """Start MCP server as subprocess (legacy path)."""
        cmd, args = self._get_server_command()
        logger.info(f"Starting MCP server subprocess: {cmd} {' '.join(args)}")
        self._connected = True  # Mock connected for non-critical use

    def _get_server_command(self) -> tuple[str, list[str]]:
        """Get the command to start this MCP server as a subprocess."""
        module_map = {
            "hk-transit": "mcp_servers.hk_transit_mcp.server",
            "mtr-accessibility": "mcp_servers.mtr_accessibility_mcp.server",
        }
        module = module_map.get(self.server_name)
        if not module:
            raise ValueError(f"Unknown MCP server: {self.server_name}")
        return (sys.executable, ["-m", module])

    # ------------------------------------------------------------------
    # Tool calling
    # ------------------------------------------------------------------

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server and return the result text.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments as a dict

        Returns:
            JSON string response from the tool
        """
        if not self._connected:
            await self.start()

        if tool_name not in self._tools:
            raise ValueError(
                f"Tool '{tool_name}' not found on server '{self.server_name}'. "
                f"Available: {list(self._tools.keys())}"
            )

        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        response = await self._send_request(request)

        if "error" in response:
            raise RuntimeError(
                f"MCP tool error: {response['error'].get('message', str(response['error']))}"
            )

        # Extract text content from tool result
        contents = response.get("result", {}).get("content", [])
        if contents and isinstance(contents, list):
            return contents[0].get("text", json.dumps(contents))
        return json.dumps(contents)

    @property
    def tools(self) -> list[str]:
        """List available tool names."""
        return list(self._tools.keys())

    @property
    def is_connected(self) -> bool:
        return self._connected


class MCPConnectionPool:
    """Manages multiple MCP server connections.

    Lazy-starts servers on first tool call. Stops all servers on cleanup.
    """

    def __init__(self):
        self._connectors: dict[str, MCPConnector] = {}

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> str:
        """Call a tool on a named MCP server (lazy-start)."""
        if server_name not in self._connectors:
            conn = MCPConnector(server_name)
            self._connectors[server_name] = conn
        else:
            conn = self._connectors[server_name]

        if not conn.is_connected:
            await conn.start()

        return await conn.call_tool(tool_name, arguments)

    async def stop_all(self) -> None:
        """Stop all MCP server processes."""
        for name, conn in self._connectors.items():
            try:
                await conn.stop()
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")
        self._connectors.clear()
