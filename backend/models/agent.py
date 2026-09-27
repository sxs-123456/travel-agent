"""Strongly typed contracts shared by workflow nodes and evaluation."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class ToolStatus(str, Enum):
    SUCCESS = "success"
    FALLBACK = "fallback"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ErrorKind(str, Enum):
    VALIDATION = "validation"
    PROVIDER = "provider"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    INTERNAL = "internal"


class ToolError(BaseModel):
    kind: ErrorKind
    code: str
    message: str
    retryable: bool = False
    provider: str | None = None


class TraceSpan(BaseModel):
    trace_id: str
    node: str
    status: ToolStatus
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = Field(ge=0)
    attempt: int = Field(ge=1)
    fallback_used: bool = False
    error_code: str | None = None


T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    """One result envelope for every local tool, remote tool and MCP adapter."""

    tool: str
    status: ToolStatus
    value: T | None = None
    error: ToolError | None = None
    latency_ms: float = Field(ge=0)
    attempts: int = Field(ge=1)
    fallback_used: bool = False
    source_ids: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {ToolStatus.SUCCESS, ToolStatus.FALLBACK}


class ConstraintSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class ConstraintViolation(BaseModel):
    code: str
    message: str
    severity: ConstraintSeverity = ConstraintSeverity.ERROR
    deterministic: bool = True
    retryable: bool = True
    path: str | None = None


class ConstraintReport(BaseModel):
    passed: bool
    violations: list[ConstraintViolation] = Field(default_factory=list)
    grounded_poi_rate: float = Field(ge=0, le=1)
    constraint_satisfaction_rate: float = Field(ge=0, le=1)
    duplicate_rate: float = Field(ge=0, le=1)
    hallucination_rate: float = Field(ge=0, le=1)

    @property
    def retryable_messages(self) -> list[str]:
        return [
            violation.message
            for violation in self.violations
            if violation.severity == ConstraintSeverity.ERROR and violation.retryable
        ]


class WorkflowMetrics(BaseModel):
    trace_id: str
    status: str
    loop_count: int = Field(ge=0)
    replan_count: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tool_successes: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    total_latency_ms: float = Field(ge=0)
    constraint_report: ConstraintReport | None = None
    traces: list[TraceSpan] = Field(default_factory=list)

