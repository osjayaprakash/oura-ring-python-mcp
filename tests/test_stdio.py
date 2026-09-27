"""Run the real entry point as a subprocess: proves nothing but MCP frames reach stdout."""

import sys

from mcp import Client, StdioServerParameters

ENV = {"OURA_ACCESS_TOKEN": "unused", "PATH": ""}


async def test_stdio_server_starts_and_lists_tools():
    params = StdioServerParameters(command=sys.executable, args=["-m", "oura_ring_mcp"], env=ENV)
    async with Client(params) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools.tools}
    assert len(names) == 11
    assert {"get_personal_info", "get_daily_sleep", "get_heart_rate"} <= names
