"""Run the real entry point as a subprocess: proves nothing but MCP frames reach stdout."""

import sys

from mcp import Client, StdioServerParameters

from oura_ring_mcp.core.oauth import TokenSet
from oura_ring_mcp.core.tokens import TokenStore


async def test_stdio_server_starts_and_lists_tools(tmp_path):
    token_file = tmp_path / "tokens.json"
    TokenStore(token_file).save(
        TokenSet(access_token="unused", refresh_token="unused", expires_at="2099-01-01T00:00:00Z")
    )
    env = {
        "OURA_CLIENT_ID": "cid",
        "OURA_CLIENT_SECRET": "csecret",
        "OURA_TOKEN_FILE": str(token_file),
        "PATH": "",
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "oura_ring_mcp"], env=env)
    async with Client(params) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools.tools}
    assert len(names) == 11
    assert {"get_personal_info", "get_daily_sleep", "get_heart_rate"} <= names
