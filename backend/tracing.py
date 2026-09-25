"""Request context shared by HTTP handling and synchronous planner execution."""
from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
