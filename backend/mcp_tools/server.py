"""MCP v2 server exposing selected grounded tools without replacing local nodes."""
from mcp.server import MCPServer

from backend.mcp_tools.tools import search_pois, weather_forecast

mcp = MCPServer(
    "travel-grounded-tools",
    description="Read-only grounded travel data tools backed by the existing providers.",
)
mcp.tool()(search_pois)
mcp.tool()(weather_forecast)


if __name__ == "__main__":
    mcp.run()

