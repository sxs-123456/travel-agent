"""Agent 层公共能力：共享 LLM 实例与结构化输出工具。

仅真实模式：langchain 必须可用且需配置 LLM_API_KEY，否则抛出清晰错误。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 允许以脚本方式直接运行本模块
_ROOT_MARKERS = ("backend", "requirements.txt")
_PROJECT_ROOT = Path(__file__).resolve().parent
while (
    not any((_PROJECT_ROOT / m).exists() for m in _ROOT_MARKERS)
    and _PROJECT_ROOT.parent != _PROJECT_ROOT
):
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.config import settings


def get_llm(temperature: float = 0.3):
    """获取一个 OpenAI 兼容的 ChatModel 实例（惰性导入 langchain）。

    未配置 LLM_API_KEY 时抛出清晰异常，提示用户先配置密钥。
    """
    if not settings.use_real_llm:
        raise RuntimeError(
            "未配置 LLM_API_KEY，无法在真实模式下调用大模型。"
            "请在 .env 中填入 LLM_API_KEY（及 LLM_BASE_URL / LLM_MODEL）后重试。"
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=temperature,
    )


def _ensure_json_word(prompt):
    """json_mode（response_format=json_object）要求 prompt 中出现 'json' 字样。

    部分兼容端点（DeepSeek / OpenAI）会严格校验，缺失则报 400
    'Prompt must contain the word json'。推理模型走 json_mode 降级时自动补一句。
    """
    if isinstance(prompt, str):
        return prompt if "json" in prompt.lower() else prompt + "\n请以 JSON 格式输出。"
    text = " ".join(str(getattr(m, "content", m)).lower() for m in prompt)
    if "json" in text:
        return prompt
    from langchain_core.messages import HumanMessage

    return list(prompt) + [HumanMessage(content="请以 JSON 格式输出。")]


def _extract_missing_fields(exc) -> list[str]:
    """从 Pydantic ValidationError / langchain wrap 过的异常里提取缺失字段路径。

    用于兜底重试时精准点名 LLM 必须补回的字段（如 days.2.hotel.location）。
    """
    # Pydantic v2 ValidationError：直接读 e.errors()
    try:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            return [str(err.get("loc", "")).strip("()") for err in exc.errors()
                    if err.get("type") == "missing"]
    except Exception:  # noqa: BLE001
        pass
    # 兜底：regex 匹配 wrap 后的异常字符串 "X\n  Field required [type=missing"
    return re.findall(r"([\w\.\[\]0-9]+)\s*\n\s*Field required \[type=missing", str(exc))


def _strengthen_prompt(prompt, missing: list[str] | None = None):
    """json_mode 重试时强化 prompt：明确点名必填字段。

    missing 为空时给通用提示；非空时把缺失字段列出来让 LLM 补回。
    """
    if missing:
        suffix = (
            "\n【重要】上一次输出缺少以下必填字段，必须补全："
            + "、".join(missing)
            + "。请重新生成完整 JSON，不要遗漏。"
        )
    else:
        suffix = (
            "\n【重要】请确保输出包含所有必填字段（city / start_date / end_date / "
            "days / weather_info / budget 等），一个都不能少。"
        )
    if isinstance(prompt, str):
        return prompt + suffix
    from langchain_core.messages import HumanMessage
    return list(prompt) + [HumanMessage(content=suffix)]


def _recover_json_mode(schema, exc):
    """json_mode 兜底：从解析异常里提取原始 JSON，尽力修复最常见偏差（裸 list）。

    推理模型走 json_mode 时可能直接返回 [...]，而 schema 是 {"items": [...]}；
    这里把裸 list 包成 {"items": [...]} 再校验。字段名不匹配等更深问题无法在此修复，
    此时应改用支持 function_calling 的模型（见 structured_chain 说明）。
    """
    import json

    m = re.search(r"completion \[(.*)\]\. Got:", str(exc), re.DOTALL)
    if not m:
        raise exc
    try:
        data = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        raise exc
    if isinstance(data, list):
        data = {"items": data}
    return schema.model_validate(data)


def structured_chain(llm, schema):
    """以最高兼容性获取结构化输出链，并在工具不支持时自动降级。

    - 优先 function_calling（支持工具调用的模型最稳定，如 gpt-4o-mini / deepseek-chat / 通义千问）。
      此模式会用工具 schema 强制字段结构，能精确匹配 Pydantic 模型。
    - 若接口报"不支持 tool_choice / thinking mode"（典型为 deepseek-reasoner 等
      推理模型）或任何可恢复错误（ValidationError / 模型输出空），自动回退到
      json_mode（response_format=json_object）并精准强化 prompt 补缺失字段，
      重试一次；仍失败则抛出清晰错误，绝不静默返回不合法对象。
    """
    fc = llm.with_structured_output(schema, method="function_calling")
    jm = llm.with_structured_output(schema, method="json_mode")

    class _Chain:
        def _fallback_json(self, prompt, *, retried=False, **kwargs):
            try:
                out = jm.invoke(_ensure_json_word(prompt), **kwargs)
            except Exception as exc:  # noqa: BLE001
                # 优先：裸 list 等结构问题 → 包 {items: [...]} 修复
                try:
                    return _recover_json_mode(schema, exc)
                except Exception:  # noqa: BLE001
                    # 仍失败：从异常提取缺失字段，重试时精准点名
                    if retried:
                        raise
                    missing = _extract_missing_fields(exc)
                    return self._fallback_json(
                        _strengthen_prompt(prompt, missing or None),
                        retried=True, **kwargs,
                    )
            if out is None:
                if retried:
                    raise RuntimeError(
                        "LLM 结构化输出返回空结果（json_mode 兜底亦为空），请稍后重试，"
                        "或换用更稳定的模型（如 deepseek-chat / gpt-4o-mini）。"
                    )
                return self._fallback_json(
                    _strengthen_prompt(prompt), retried=True, **kwargs
                )
            return out

        def invoke(self, prompt, *args, **kwargs):
            try:
                out = fc.invoke(prompt, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                # LLM 在 function_calling 下偶发返回末尾带多余字符的 JSON
                # （典型 DeepSeek：JSONDecodeError / "are not valid JSON" /
                #  OutputParserException）。json_mode 兜底**不能**解决此问题——
                # json_mode 下 LLM 会自创字段名（coordinate/lat/lng 等），
                # 反而触发 Pydantic ValidationError，502 更糟。
                # 因此这里选择**同模式重试一次**（function_calling 本身是稳的，
                # 偶发问题通常第二次就成功）。
                if ("not valid json" in msg or "jsondecode" in msg
                        or "output parser" in msg or "output parsing" in msg):
                    out = fc.invoke(
                        _strengthen_prompt(
                            prompt,
                            ["arguments 必须是完整可解析的 JSON 对象，不要追加任何额外字符"],
                        ),
                        *args, **kwargs,
                    )
                # tool_choice / thinking 不支持（推理模型）→ 必须用 json_mode
                elif "tool_choice" in msg or "thinking" in msg:
                    return self._fallback_json(prompt, **kwargs)
                # Pydantic ValidationError（漏字段/字段拼错）→ 降级 json_mode
                # 重试一次（精准补字段），仅在 Pydantic 校验层失败时有效。
                elif ("validation" in msg or "field required" in msg
                      or "missing" in msg):
                    return self._fallback_json(prompt, **kwargs)
                else:
                    raise
            # function_calling 偶发返回 None（工具未被触发）或非 schema 实例
            # （漏字段/校验失败被静默吞掉）：用 json_mode 兜底重试一次
            if out is None or not isinstance(out, schema):
                return self._fallback_json(prompt, **kwargs)
            return out

    return _Chain()
