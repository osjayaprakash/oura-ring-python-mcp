"""Hits the real Oura API. Run with: uv run pytest -m live"""

import os

import pytest
from mcp import Client

from oura_ring_mcp import server
from oura_ring_mcp.config import load_settings
from oura_ring_mcp.service import OuraService

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("OURA_ACCESS_TOKEN"), reason="needs OURA_ACCESS_TOKEN"),
]


async def test_live_personal_info_and_daily_sleep():
    settings = load_settings()
    server.set_service(OuraService(server.build_client(settings)))
    try:
        async with Client(server.mcp) as mcp_client:
            info = await mcp_client.call_tool("get_personal_info", {})
            assert not info.is_error, info.content
            assert info.structured_content["id"]
            for tool in (
                "get_daily_sleep",
                "get_sleep_periods",
                "get_daily_readiness",
                "get_daily_activity",
                "get_heart_rate",
            ):
                result = await mcp_client.call_tool(tool, {})
                assert not result.is_error, (tool, result.content)
                assert result.structured_content["count"] >= 0
    finally:
        server.set_service(None)
