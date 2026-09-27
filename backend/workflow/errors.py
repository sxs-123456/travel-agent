"""Error classification used by node retry and fallback policies."""
from __future__ import annotations

from backend.models.agent import ErrorKind, ToolError


def classify_error(exc: BaseException, *, provider: str | None = None) -> ToolError:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    status = getattr(exc, "status_code", None)
    if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
        return ToolError(
            kind=ErrorKind.TIMEOUT, code="tool_timeout", message=text[:300],
            retryable=True, provider=provider,
        )
    if status == 429 or "rate limit" in lowered or "频控" in text:
        return ToolError(
            kind=ErrorKind.RATE_LIMIT, code="rate_limited", message=text[:300],
            retryable=True, provider=provider,
        )
    if status in {401, 403} or "api_key" in lowered or "unauthorized" in lowered:
        return ToolError(
            kind=ErrorKind.AUTH, code="provider_auth", message=text[:300],
            retryable=False, provider=provider,
        )
    if isinstance(exc, (ValueError, TypeError)):
        return ToolError(
            kind=ErrorKind.VALIDATION, code="invalid_tool_result", message=text[:300],
            retryable=False, provider=provider,
        )
    return ToolError(
        kind=ErrorKind.PROVIDER, code="provider_failure", message=text[:300],
        retryable=True, provider=provider,
    )
