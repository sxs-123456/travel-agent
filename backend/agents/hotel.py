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

from backend.models.trip import Hotel
from backend.tools.amap import hotel_search, infer_hotel_tier


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

        # 档次已由高德检索层过滤；这里按评分稳定排序，直接恢复事实字段。
        # 酒店选择无需再调用 LLM，减少延迟、token 与字段被改写的风险。
        ranked = sorted(
            raw,
            key=lambda item: (-(item.get("rating") or 0), item.get("price_estimate") or 10**9),
        )[:3]
        return [Hotel(
            name=item["name"],
            location=item["location"].model_copy(deep=True),
            price_per_night=int(item.get("price_estimate") or 0),
            star_rating=float(item.get("rating") or 3.0),
            level=item.get("level"),
            price_source=item.get("price_source"),
            price_is_estimated=True,
            image_url=None,
        ) for item in ranked]
