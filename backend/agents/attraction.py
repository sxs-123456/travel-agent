"""景点搜索 Agent：根据用户偏好，借助高德 POI 搜索挑选景点并结构化。

门票（真实数据，免费来源）
-----------------------------
- 门票：百度百科词条卡片 API（免费、免 key），如故宫「60元旺季/40元淡季」；
  查不到的景点如实标注「门票以景区现场公告为准」，绝不臆造。
- 图片：优先使用高德 POI 附带照片；缺图时由 planner 用 Pexels/Openverse 补充。

多天行程防重复
-------------
- 按行程天数让 LLM 甄选足够多的**不同景区**（每天 2-3 个）；
- prompt 明确要求：同一景区的子景点（如故宫的太和门/乾清宫）只保留一个代表，
  不同天安排不同景区，避免三天都在同一景区打转。
"""
from __future__ import annotations

import concurrent.futures as futures

from pydantic import BaseModel, Field

from backend.models.trip import Attraction
from backend.tools.amap import text_search
from backend.tools.ticket import query_baike_card
from backend.agents.base import get_llm, structured_chain


class AttractionSelection(BaseModel):
    """LLM 只选择候选 ID；景点事实字段由代码从高德结果恢复。"""

    source_ids: list[str] = Field(default_factory=list)


class AttractionSearchAgent:
    name = "AttractionSearchAgent"

    def run(self, request) -> list[Attraction]:
        # 真实模式：先调用高德获取真实 POI，再让 LLM 只选择候选 ID。
        raw = text_search(f"{request.preferences} 景点", request.city)

        try:
            total_days = request.total_days()
        except Exception:  # noqa: BLE001  日期解析失败按 1 天处理
            total_days = 1

        # 三天及以上的窄偏好检索常只返回同一景区的内部点；合并一次通用景点检索，
        # 给跨天规划提供更广的真实 POI 候选。
        if total_days >= 3:
            try:
                general = text_search("热门景点", request.city)
                seen_keys = {
                    str(item.get("source_id") or item.get("name") or "") for item in raw
                }
                for item in general:
                    key = str(item.get("source_id") or item.get("name") or "")
                    if key and key not in seen_keys:
                        raw.append(item)
                        seen_keys.add(key)
                    if len(raw) >= 30:
                        break
            except Exception:  # noqa: BLE001  通用补查失败仍可使用首轮候选
                pass

        # 高德真实响应包含 POI id。对测试桩或兼容数据分配一次请求内 ID，
        # 让后续模型始终通过 ID 选择，而不是依赖容易出现别名的文本名称。
        for index, poi in enumerate(raw, 1):
            poi["source_id"] = str(poi.get("source_id") or f"candidate-{index:02d}")

        ctx = "\n".join(
            f"- [{r['source_id']}] {r['name']}（坐标 "
            f"{r['location'].longitude},{r['location'].latitude}）：{r.get('description','')}"
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
            f"3. 只返回候选列表方括号中的 source_id，不返回名称、坐标、价格或说明；\n"
            f"4. source_id 不得重复，也不得生成候选列表之外的 ID。"
        )
        llm = get_llm()
        selection: AttractionSelection = structured_chain(
            llm, AttractionSelection
        ).invoke(prompt)

        by_id = {poi["source_id"]: poi for poi in raw}
        verified: list[Attraction] = []
        seen_ids: set[str] = set()

        def materialize(source: dict) -> Attraction:
            return Attraction(
                source_id=source["source_id"],
                name=source["name"],
                location=source["location"].model_copy(deep=True),
                ticket_price=0,
                description=source.get("description", ""),
                image_url=source.get("image_url"),
                image_source=source.get("image_source"),
            )

        for source_id in selection.source_ids:
            source = by_id.get(source_id)
            if source is None or source_id in seen_ids:
                continue
            seen_ids.add(source_id)
            verified.append(materialize(source))
        if not verified:
            raise RuntimeError("景点结果无法匹配高德候选，请调整目的地或偏好后重试。")

        # LLM 有时只选择同一景区的多个子点，跨天去重后候选不足。
        # 将剩余高德真实 POI 确定性补入候选池，保证后处理有足够的不同景点可用。
        target_count = min(len(raw), max(total_days, min(2 * total_days, 8)))
        for source in raw:
            if len(verified) >= target_count:
                break
            source_id = source["source_id"]
            if source_id in seen_ids:
                continue
            normalized = "".join(ch for ch in source["name"] if ch.isalnum())
            existing_names = [
                "".join(ch for ch in item.name if ch.isalnum()) for item in verified
            ]
            if any(
                normalized == existing
                or (min(len(normalized), len(existing)) >= 4
                    and (normalized in existing or existing in normalized))
                for existing in existing_names
            ):
                continue
            seen_ids.add(source_id)
            verified.append(materialize(source))

        # 极窄目的地可能没有足够的不同景区；仍保留未使用的真实子景点作为最后补位，
        # 空行程比同一大景区内游览不同点更不可用。
        for source in raw:
            if len(verified) >= target_count:
                break
            source_id = source["source_id"]
            if source_id not in seen_ids:
                seen_ids.add(source_id)
                verified.append(materialize(source))

        # 真实门票：百度百科卡片（免费、免 key）；地点照片来自 POI，后续缺图再补。
        def enrich_ticket(item: Attraction) -> Attraction:
            price, note = query_baike_card(item.name)
            if price is not None:
                item.ticket_price = price
            item.ticket_price_note = note
            return item

        with futures.ThreadPoolExecutor(max_workers=min(8, len(verified))) as executor:
            verified = list(executor.map(enrich_ticket, verified))
        return verified
