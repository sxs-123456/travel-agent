"""LLM 调用用量统计：按一次行程请求聚合 token 与估算费用。"""
from __future__ import annotations

from contextvars import ContextVar
from threading import Lock
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


class LlmUsageTracker(BaseCallbackHandler):
    """兼容 OpenAI 风格与 LangChain usage_metadata 的用量回调。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0

    @staticmethod
    def _usage_from_response(response: Any) -> dict[str, Any]:
        llm_output = getattr(response, "llm_output", None) or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage")
        if usage:
            return usage

        for generation_list in getattr(response, "generations", []) or []:
            for generation in generation_list or []:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None)
                if usage:
                    return usage
        return {}

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: ARG002
        usage = self._usage_from_response(response)
        input_tokens = int(
            usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        )
        output_tokens = int(
            usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        )
        total_tokens = int(usage.get("total_tokens", 0) or 0)
        if not total_tokens:
            total_tokens = input_tokens + output_tokens

        with self._lock:
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.total_tokens += total_tokens

    def snapshot(
        self,
        *,
        model: str,
        input_cost_per_1m_usd: float,
        output_cost_per_1m_usd: float,
    ) -> dict[str, Any]:
        with self._lock:
            cost = None
            if input_cost_per_1m_usd or output_cost_per_1m_usd:
                cost = round(
                    self.input_tokens / 1_000_000 * input_cost_per_1m_usd
                    + self.output_tokens / 1_000_000 * output_cost_per_1m_usd,
                    6,
                )
            return {
                "model": model,
                "calls": self.calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "estimated_cost_usd": cost,
                "usage_available": self.total_tokens > 0,
            }


current_llm_usage_tracker: ContextVar[LlmUsageTracker | None] = ContextVar(
    "llm_usage_tracker", default=None
)
