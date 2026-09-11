"""酒店搜索 Agent：基于高德 v5 真实 POI 检索，返回真实酒店 + 参考估算价。

价格说明（诚实标注）
-------------------
高德免费接口（v3 与 v5，已实测）不再返回酒店房价，因此本项目与旧项目
（A2A 出行助手）一致：返回「真实酒店（名称/坐标/官方档次/评分）」，
价格按「城市系数 × 档次基准/评分档位」给出参考估算价，并明确标注
price_is_estimated=True 与 price_source，绝不冒充官方报价。
封面图由 planner 统一用 Pexels/Openverse 补，本 Agent 不处理图片。
如需 100% 真实房价，需接入携程/同程/美团开放平台（商业 key），本代码留好扩展点。
"""
from __future__ import annotations

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

from pydantic import BaseModel, Field

from backend.models.trip import Hotel
from backend.tools.amap import hotel_search, infer_hotel_tier
from backend.agents.base import get_llm, structured_chain


class HotelList(BaseModel):
    items: list[Hotel] = Field(default_factory=list)


def _norm_name(name: str) -> str:
    """归一化名称用于回贴候选数据映射（去掉空格与常见标点）。"""
    return "".join(ch for ch in name if ch.isalnum())


class HotelAgent:
    name = "HotelAgent"

    def run(self, request) -> list[Hotel]:
        # 酒店档次完全由预算等级决定（不再单独维护『住宿偏好』字段），
        # 据此换用高德有效检索词并按 level 过滤，确保「选豪华预算就推荐豪华酒店」。
        tier = infer_hotel_tier(request.budget_level)
        raw = hotel_search(
            request.city,
            keywords="酒店",
            tier=tier,
        )

        ctx = "\n".join(
            f"- {r['name']}（{r['level'] or '档次未知'}，评分 {r['rating'] or '暂无'}，"
            f"参考价 ¥{r['price_estimate'] or '未知'}/晚，坐标 "
            f"{r['location'].longitude},{r['location'].latitude}）"
            for r in raw
        )
        prompt = (
            f"你是酒店搜索专家。城市：{request.city}，预算等级：{request.budget_level}"
            f"（推断档次：{tier or '未指定'}）。\n"
            f"以下是高德检索到的真实酒店（档次/评分/参考价均为官方或估算数据）：\n{ctx}\n\n"
            f"请从中挑选 2-3 家与预算等级最匹配的酒店，逐项补全：\n"
            f"- 优先挑选档次与『{tier or '预算等级'}』一致的酒店，不要降档（如豪华预算就只选豪华型）；\n"
            f"- name/location/star_rating/level：直接使用候选数据，不要改名改坐标；\n"
            f"- price_per_night：使用候选数据的参考价（即上方『参考价 ¥xx』的数值），不要自行编造；\n"
            f"- price_source：填写『参考估算（免费接口无真实房价，以携程/美团实际为准）』；\n"
            f"- price_is_estimated：填 true（诚实标注为估算）；\n"
            f"- image_url 字段请勿填写（封面图由系统统一获取），置为 null。\n"
            f"注意：若候选不足 3 家则按实际数量返回，禁止虚构不存在的酒店。"
        )
        llm = get_llm()
        result: HotelList = structured_chain(llm, HotelList).invoke(prompt)

        # 封面图由 planner._enrich_images 统一补（Pexels/Openverse）。
        # 兜底：若 LLM 遗漏了 price_source/level，用候选数据补齐，确保前端标注完整。
        for item in result.items:
            src = next((r for r in raw if _norm_name(r["name"]) == _norm_name(item.name)), None)
            if src:
                if not item.level and src.get("level"):
                    item.level = src["level"]
                if src.get("price_estimate") is not None and item.price_per_night in (0, None):
                    item.price_per_night = src["price_estimate"]
                if not item.price_source:
                    item.price_source = src.get("price_source")
            item.price_is_estimated = True
        return result.items
