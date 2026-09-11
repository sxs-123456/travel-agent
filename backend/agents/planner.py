"""行程编排 Agent：整合景点/天气/酒店，生成逐日行程与预算。"""
from __future__ import annotations

import logging
import sys
from datetime import date as _date
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

from backend.models.trip import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    TrainOption,
    TrainRecommendation,
    TrainSeat,
    TripPlan,
    TripPlanRequest,
    WeatherInfo,
)
from backend.agents.base import get_llm, structured_chain
from backend.config import settings
from backend.rail_client import rail_client
logger = logging.getLogger("trip-planner")

_TRANSPORT_PER_DAY = {"经济": 50, "中等": 100, "豪华": 200}


def _norm_name(name: str) -> str:
    """归一化名称（去空格与标点），用于把上游高德照片映射回 LLM 重生成的同名项。"""
    return "".join(ch for ch in name if ch.isalnum())


def _same_scenic_area(a: str, b: str) -> bool:
    """判断两个景点名是否属于同一景区（防「三天都在故宫」的重复体验）。

    规则（保守，宁漏勿错）：
    - 归一化后完全同名 → 同景区；
    - 互为包含且短名 >= 4 字（如『故宫博物院』⊂『故宫博物院-太和门』）→ 同景区；
      短名 < 4 字的包含（如『天坛』⊂『天坛公园』不算）不处理，避免误杀。
    """
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb or na == nb:
        return na == nb
    if len(na) >= 4 and (na in nb or nb in na):
        return True
    return False


class PlannerAgent:
    name = "PlannerAgent"

    @staticmethod
    def _dedupe_attractions_across_days(plan: TripPlan) -> None:
        """跨天景点去重：同名/同一景区的子景点只保留首次出现。

        LLM 偶发把同一景区（或其子景点）排进多天，导致「三天都在故宫」；
        这里做后处理兜底，保证每天去的都是不同景区。
        """
        seen: list[str] = []  # 已出现景点的归一化名
        for day in plan.days:
            kept = []
            for attr in day.attractions:
                name = _norm_name(attr.name)
                if any(_same_scenic_area(name, s) for s in seen):
                    logger.info("跨天去重：移除重复景区 %s（Day%d）", attr.name, day.day)
                    continue
                kept.append(attr)
                seen.append(name)
            day.attractions = kept

    @staticmethod
    def _strip_return_day_hotel(plan: TripPlan, request: TripPlanRequest) -> None:
        """返程当天不住店：把返程日（及之后）的 hotel 置空。

        N 天行程 = N-1 晚（23 号去 25 号返 = 2 晚），LLM 常把酒店填满每一天，
        这里按日期排序后，把第 nights 天之后（即返程日及以后）的 hotel 置空，
        让时间轴不再显示「多订一晚」（预算本身已按间夜数正确计算）。
        """
        try:
            nights = max(0, (_date.fromisoformat(request.end_date)
                            - _date.fromisoformat(request.start_date)).days)
        except (ValueError, TypeError):
            nights = max(0, len(plan.days) - 1)
        plan.days.sort(key=lambda d: d.date)
        for d in plan.days[nights:]:
            d.hotel = None

    @staticmethod
    def _apply_single_hotel(plan: TripPlan, hotels: list[Hotel]) -> Hotel | None:
        """多晚住同一家：把所有过夜日的 hotel 统一替换为首选酒店，返回该酒店。

        常规订房习惯是整段行程住同一家酒店；LLM 偶发给不同天选不同酒店，
        这里统一用 HotelAgent 的首选（hotels[0]，已是高德真实候选 + 参考价），
        既保证一致，也顺带覆盖 LLM 可能臆造/改写的名称与价格。
        """
        single = hotels[0] if hotels else None
        for d in plan.days:
            if d.hotel is not None:
                d.hotel = single
        return single

    def run(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
        weather: list[WeatherInfo],
        hotels: list[Hotel],
    ) -> TripPlan:
        # 真实模式：由 LLM 基于真实候选数据生成逐日行程；
        # 预算与天气另行用真实数据覆盖，确保「仅真实数据、不保留任何 Mock」。
        return self._build_with_llm(request, attractions, weather, hotels)

    @staticmethod
    def _compute_budget(request, days, hotel, rail=None, taxi=None,
                        rail_is_estimated=True, taxi_is_estimated=True) -> Budget:
        # 预算完全由真实数据计算得到，不依赖 LLM 生成。
        # 门票/餐饮按人头计；酒店按间夜计（一间房可多人入住，不乘人数）；
        # 交通分「城际(rail，火车票往返)」与「市内(taxi，打车/短驳)」两部分：
        #   - rail 传真实票价(12306)则用真实值，否则为 0（未启用城际）；
        #   - taxi 传真实打车估算(百度)则用真实值，否则按「档位 × 天数 × 人数」估算。
        ticket = sum(a.ticket_price for d in days for a in d.attractions) * request.travelers
        meal = sum(m.price for d in days for m in d.meals) * request.travelers
        # 酒店间夜数 = 行程天数 - 1（23 号出发、25 号返程 = 2 晚，不是 3 晚）；
        # 同日往返不计酒店。用日期差而不是 len(days)，避免 LLM 生成的 DayPlan
        # 数量与日期范围不一致时再次出错。
        try:
            nights = max(0, (_date.fromisoformat(request.end_date)
                            - _date.fromisoformat(request.start_date)).days)
        except (ValueError, TypeError):
            nights = len(days)
        # 酒店按「间/晚」计：标准每间住 2 人，4 人出游开 2 间、5 人开 3 间。
        rooms = max(1, (request.travelers + 1) // 2)
        hotel_total = (hotel.price_per_night if hotel else 0) * nights * rooms
        if rail is None:
            rail = 0
        if taxi is None:
            taxi = _TRANSPORT_PER_DAY.get(request.budget_level, 100) * len(days) * request.travelers
            taxi_is_estimated = True
        transport = rail + taxi
        transport_is_estimated = rail_is_estimated or taxi_is_estimated
        total = ticket + meal + hotel_total + transport
        return Budget(
            ticket_total=ticket,
            hotel_total=hotel_total,
            meal_total=meal,
            transport_total=transport,
            rail_total=rail,
            taxi_total=taxi,
            rail_is_estimated=rail_is_estimated,
            taxi_is_estimated=taxi_is_estimated,
            transport_is_estimated=transport_is_estimated,
            total=total,
            travelers=request.travelers,
            rooms=rooms,
        )

    # ----- 真实模式：LLM 结构化生成 -----
    def _build_with_llm(self, request, attractions, weather, hotels) -> TripPlan:
        attr_text = "\n".join(
            f"  - {a.name}（门票¥{a.ticket_price}，坐标 {a.location.longitude},{a.location.latitude}）"
            for a in attractions
        )
        hotel_text = "\n".join(
            f"  - {h.name}（¥{h.price_per_night}/晚，{h.star_rating}星）" for h in hotels
        )
        # 天气文本保留日期，使 LLM 能感知「哪天下雨」，从而把室外景点避开雨天。
        w_text = "\n".join(f"  - {w.date} {w.condition} {w.temperature}℃" for w in weather)
        try:
            total_days = (
                _date.fromisoformat(request.end_date)
                - _date.fromisoformat(request.start_date)
            ).days + 1
        except ValueError:
            total_days = 1
        prompt = (
            f"你是资深旅行规划师。请为以下信息生成逐日行程与预算。\n"
            f"请求：{request.model_dump_json()}\n"
            f"候选景点（共 {len(attractions)} 个，均为不同景区）：\n{attr_text}\n"
            f"候选酒店：\n{hotel_text}\n"
            f"天气：\n{w_text}\n\n"
            f"要求：\n"
            f"1. 共 {max(total_days, 1)} 天，每天安排 2-3 个景点；\n"
            f"2. 【防重复】每天必须去**不同的景区**，任何景点（含同一景区的子景点）"
            f"在整个行程中只能出现一次——严禁把同一景区排进多天；\n"
            f"3. 每天含午餐；把相邻/顺路的景点排到同一天；\n"
            f"4. 酒店只填在需要过夜的晚上：{max(total_days, 1)} 天行程 = "
            f"{max(total_days - 1, 0)} 晚，所有晚上住**同一家**酒店，"
            f"**最后一天（返程日）不填 hotel（置 null）**；\n"
            f"5. 输出严格符合 TripPlan 结构（无需填写 budget 与 weather_info，"
            f"系统将用真实数据补全）。"
        )
        llm = get_llm(temperature=0.2)
        plan = structured_chain(llm, TripPlan).invoke(prompt)

        # 后处理：跨天景点去重（LLM 偶发违规，同名或同一景区子景点视为重复，
        # 只保留首次出现，保证「每天不同景区」的体验）。
        self._dedupe_attractions_across_days(plan)

        # 后处理：酒店只出现在「过夜的晚上」。N 天行程 = N-1 晚，返程当天不住店；
        # 把返程日（及之后）的 hotel 置空，避免时间轴显示「多订一晚」。
        self._strip_return_day_hotel(plan, request)

        # 酒店：多晚住同一家（hotels[0] 已是高德真实候选 + 参考价 + 档次/评分），
        # 统一替换所有过夜日的 hotel，并覆盖 LLM 可能臆造/改写的名称与价格。
        hotel = self._apply_single_hotel(plan, hotels)

        # 城际交通：USE_RAIL_MCP 且提供出发城市时，用 12306 官方直连的真实往返票价，
        # 并生成「车次选择推荐」（候选车次列表 + 推荐班次 + 推荐理由）。
        # 任一前置条件不满足 / 查询失败时，用 train_note 说明原因，避免前端「静默无车票面板」。
        rail = 0
        rail_is_estimated = True
        train_info: list[TrainRecommendation] | None = None
        train_note: str | None = None
        if settings.use_rail_mcp and request.origin_city and rail_client.available():
            try:
                train_info = self._build_train_recommendations(request)
                # 预算采用「去程推荐 + 返程推荐」的真实票价（单程价 × 出行人数 × 2 方向）
                go_price = train_info[0].price_per_person
                back_price = train_info[1].price_per_person
                if go_price is not None and back_price is not None:
                    rail = (go_price + back_price) * request.travelers
                    rail_is_estimated = False
            except Exception as e:
                logger.warning("12306 真实票价获取失败，城际交通回退为估算：%s", e)
                train_info = None
                train_note = f"12306 车次查询失败，城际交通已回退估算（{e}）。"
        elif not settings.use_rail_mcp:
            train_note = "未启用 12306 真实车票（USE_RAIL_MCP=false），城际交通为估算值。"
        elif not request.origin_city:
            train_note = "未填写出发城市，故未查询 12306 车次；填写出发城市后可获得真实往返票价与车次推荐。"

        # 市内交通：配 BAIDU_MAP_AK 时用真实打车估算（酒店↔景点往返），否则按天估算。
        taxi = self._estimate_city_taxi(plan.days, hotel)
        taxi_is_estimated = taxi is None

        plan.budget = self._compute_budget(
            request, plan.days, hotel,
            rail=rail, taxi=taxi,
            rail_is_estimated=rail_is_estimated, taxi_is_estimated=taxi_is_estimated,
        )
        plan.train_info = train_info
        plan.train_note = train_note
        return plan

    @staticmethod
    def _build_train_recommendations(request: TripPlanRequest) -> list[TrainRecommendation]:
        """查询 12306 去程/返程车次列表，推荐最合适班次，返回结构化推荐信息。

        返回两条 TrainRecommendation（[去程, 返程]）；任一方查询失败会整体抛错，
        由上层回退为估算（保证不出现「半程有价、半程无价」的割裂预算）。

        候选展示策略：只展示前 10 班车次（避免列表过长、降低 12306 票价 API 调用）；
        推荐车次总是置顶：若 best 已在前 10 则直接用，若不在则单独给它补一次票价后
        插入 candidates 第 1 位（保证推荐车次始终有真实票价，前端可见）。
        """
        _MAX_DISPLAY = 10
        recs: list[TrainRecommendation] = []
        for direction, frm, to, date in (
            (f"去程：{request.origin_city}→{request.city}", request.origin_city, request.city, request.start_date),
            (f"返程：{request.city}→{request.origin_city}", request.city, request.origin_city, request.end_date),
        ):
            trains = rail_client.search_with_prices(frm, to, date)
            # 复用已查询的 trains，避免 recommend 内部再查一次 12306（风控/延迟）
            best, reason = rail_client.recommend(frm, to, date, trains=trains)
            if best is None:
                raise RuntimeError(f"12306 未返回{direction}的可用车次")
            # 候选只取前 _MAX_DISPLAY 条（12306 返回的车次通常很多，前端没必要全展示）；
            # 若推荐车次不在前 _MAX_DISPLAY 内，单独给它补一次票价并插到第 1 位。
            display_trains = PlannerAgent._pick_display_trains(trains, best, _MAX_DISPLAY)
            # 候选车次统一裁剪字段，避免把内部字段（train_code 等）透传给前端。
            candidates: list[TrainOption] = []
            for t in display_trains:
                seats = [
                    TrainSeat(type=s["type"], remain=s.get("remain", ""), price=s.get("price"))
                    for s in t.get("seats", [])
                    if s.get("type")
                ]
                candidates.append(TrainOption(
                    train_no=t.get("train_no", ""),
                    train_type=t.get("train_type", ""),
                    from_station=t.get("from_station", ""),
                    to_station=t.get("to_station", ""),
                    depart_time=t.get("depart_time", ""),
                    arrive_time=t.get("arrive_time", ""),
                    duration=t.get("duration", ""),
                    seats=seats,
                    min_price=t.get("min_price"),
                ))
            # 推荐车次（保证与 candidates[0] 一致：上面 best 已在第 1 位）
            rec_train = candidates[0] if candidates else None
            # 单人票价：优先偏好席别真实价，未命中则取可订最低价（与预算口径一致）
            price_per_person = None
            if rec_train:
                pref = settings.rail_mcp_seat_class
                pref_price = next(
                    (s.price for s in rec_train.seats if s.type == pref and s.price is not None),
                    None,
                )
                price_per_person = pref_price if pref_price is not None else rec_train.min_price
            recs.append(TrainRecommendation(
                direction=direction,
                date=date,
                recommended=rec_train,
                reason=reason,
                candidates=candidates,
                price_per_person=price_per_person,
            ))
        return recs

    @staticmethod
    def _pick_display_trains(trains: list[dict], best: dict, max_display: int = 10) -> list[dict]:
        """从 trains 里选最多 max_display 条展示，保证推荐车次在第 1 位。

        - 若 best 已在前 max_display 条：直接返回前 max_display 条；
        - 若不在：单独给 best 补一次真实票价（否则前 10 都没补到 best，价格空缺），
          并把 best 插入第 1 位，整体仍保持 max_display 条。

        返回新列表（不会就地修改原 trains）。
        """
        display = list(trains[:max_display])
        if any(t.get("train_no") == best.get("train_no") for t in display):
            return display
        best_with_prices = PlannerAgent._ensure_train_prices(best, "")
        # 原 best 已在 trains 里（recommend 从全集选），用更新过票价的版本替换
        merged = [best_with_prices] + display[: max_display - 1]
        return merged

    @staticmethod
    def _ensure_train_prices(train: dict, date: str) -> dict:
        """对单班车次单独补一次真实票价（用于「推荐车次不在展示前 N 条内」的兜底）。

        在调用方负责不修改原 trains 列表（dict 是引用传递，会就地写入 seats[i].price）。
        返回同一个 train dict，便于调用方链式使用。
        """
        prices = rail_client._provider.get_prices(
            train["train_code"], train["from_station_no"], train["to_station_no"],
            train.get("seat_types", "O"), date,
        )
        for s in train.get("seats", []):
            if s["type"] in prices:
                s["price"] = prices[s["type"]]
        priced = [
            s["price"] for s in train.get("seats", [])
            if s.get("price") is not None and s.get("remain") not in ("无", "", None)
        ]
        train["min_price"] = min(priced) if priced else None
        return train

    @staticmethod
    def _estimate_city_taxi(days: list[DayPlan], hotel: Hotel | None) -> int | None:
        """市内打车估算：每天「酒店 ↔ 当天首个景点」往返（单程 × 2），按车计价。

        未配置 BAIDU_MAP_AK / 无酒店 / 任一天估算失败时返回 None，由调用方回退按天估算。
        """
        if not settings.baidu_map_ak or not hotel:
            return None
        from backend.tools.taxi import BaiduRideProvider

        provider = BaiduRideProvider()
        total = 0.0
        for day in days:
            if not day.attractions:
                continue
            first = day.attractions[0]
            try:
                fare = provider.estimate_ride_by_coords(
                    hotel.location.latitude, hotel.location.longitude,
                    first.location.latitude, first.location.longitude,
                    start_label="酒店", end_label=first.name,
                )["estimated_fare"]
                total += float(fare) * 2  # 往返
            except Exception as e:
                logger.warning("市内打车估算失败，回退按天估算：%s", e)
                return None
        return int(total) if total > 0 else None
