"""景点搜索 Agent：根据用户偏好，借助高德 POI 搜索挑选景点并结构化。

门票（真实数据，免费来源）
-----------------------------
- 门票：百度百科词条卡片 API（免费、免 key），如故宫「60元旺季/40元淡季」；
  查不到的景点如实标注「门票以景区现场公告为准」，绝不臆造。
- 封面图：统一由 planner._enrich_images 用 Pexels/Openverse 补，本 Agent 不处理图片。

多天行程防重复
-------------
- 按行程天数让 LLM 甄选足够多的**不同景区**（每天 2-3 个）；
- prompt 明确要求：同一景区的子景点（如故宫的太和门/乾清宫）只保留一个代表，
  不同天安排不同景区，避免三天都在同一景区打转。
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

from backend.models.trip import Attraction
from backend.tools.amap import text_search
from backend.tools.ticket import query_baike_card
from backend.agents.base import get_llm, structured_chain


class AttractionList(BaseModel):
    """LLM 结构化输出的包装模型（列表需嵌套字段）。"""

    items: list[Attraction] = Field(default_factory=list)


class AttractionSearchAgent:
    name = "AttractionSearchAgent"

    def run(self, request) -> list[Attraction]:
        # 真实模式：先调用高德获取真实 POI，再让 LLM 甄选并补全结构化信息。
        raw = text_search(f"{request.preferences} 景点", request.city)

        # 行程天数（决定甄选多少个不同景区：每天 2-3 个）。
        try:
            total_days = request.total_days()
        except Exception:  # noqa: BLE001  日期解析失败按 1 天处理
            total_days = 1

        ctx = "\n".join(
            f"- {r['name']}（坐标 {r['location'].longitude},{r['location'].latitude}）：{r.get('description','')}"
            for r in raw
        )
        prompt = (
            f"你是景点搜索专家。城市：{request.city}，偏好：{request.preferences}，"
            f"行程共 {total_days} 天。\n"
            f"高德搜索结果：\n{ctx}\n\n"
            f"请甄选 {min(2 * total_days, 8)} 个左右**互不重复**的景点，要求：\n"
            f"1. 同一景区的内部子景点（如『故宫博物院-太和门』『故宫博物院-乾清宫』"
            f"属于同一景区）只保留 1 个代表，不得同时选入；\n"
            f"2. 景点之间应是**不同的景区**，保证 {total_days} 天行程每天都能去不同的地方；\n"
            f"3. 坐标沿用搜索结果，推荐游玩时长 1-4 小时，description 用一句话。\n"
            f"注意：ticket_price 填 0、ticket_price_note 置 null（真实门票价格由系统查询）；"
            f"image_url 字段请勿填写（封面图由系统统一获取），置为 null。"
        )
        llm = get_llm()
        result: AttractionList = structured_chain(llm, AttractionList).invoke(prompt)

        # 真实门票：百度百科卡片（免费、免 key）。封面图由 planner 统一用 Pexels/Openverse 补。
        for item in result.items:
            price, note = query_baike_card(item.name)
            if price is not None:
                item.ticket_price = price
            item.ticket_price_note = note
        return result.items
