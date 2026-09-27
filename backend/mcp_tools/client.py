"""Optional MCP client adapter returning the workflow's standard ToolResult."""
from __future__ import annotations

from time import perf_counter
from typing import Any

from mcp import Client

from backend.models.agent import ErrorKind, ToolError, ToolResult, ToolStatus


class TravelMcpClient:
    def __init__(self, server: str, timeout_seconds: float = 20) -> None:
        self.server = server
        self.timeout_seconds = timeout_seconds

    async def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult[Any]:
        started = perf_counter()
        try:
            async with Client(self.server, read_timeout_seconds=self.timeout_seconds) as client:
                response = await client.call_tool(
                    tool, arguments, read_timeout_seconds=self.timeout_seconds
                )
            value = response.structured_content
            status = ToolStatus.SUCCESS
            error = None
            if response.is_error:
                status = ToolStatus.FAILED
                value = None
                error = ToolError(
                    kind=ErrorKind.PROVIDER, code="mcp_tool_error",
                    message="MCP 工具返回错误", retryable=True, provider="mcp",
                )
        except Exception as exc:
            status, value = ToolStatus.FAILED, None
            error = ToolError(
                kind=ErrorKind.PROVIDER, code="mcp_client_error",
                message=str(exc)[:300], retryable=True, provider="mcp",
            )
        return ToolResult(
            tool=f"mcp.{tool}", status=status, value=value, error=error,
            latency_ms=round((perf_counter() - started) * 1000, 2), attempts=1,
        )
