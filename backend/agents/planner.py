"""行程编排 Agent：整合景点/天气/酒店，生成逐日行程与预算。"""
from __future__ import annotations

import logging
import concurrent.futures as futures
from datetime import date as _date
from datetime import timedelta as _timedelta
from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel, Field

from backend.models.trip import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Meal,
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
from backend.tools.amap import driving_route
from backend.tools.restaurants import recommend_restaurants
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


class MealDraft(BaseModel):
    """模型可建议餐饮文本与参考人均，不生成未经地图核实的坐标。"""

    name: str
    price: int = Field(0, ge=0)
    cuisine: str = ""


class DayPlanDraft(BaseModel):
    """LLM 输出的最小单日草稿；事实字段由后端恢复。"""

    attraction_ids: list[str] = Field(default_factory=list)
    meals: list[MealDraft] = Field(default_factory=list)
    notes: str = ""


class ItineraryDraft(BaseModel):
    """规划模型接口：只表达逐日选择与建议，不重复生成事实字段。"""

    days: list[DayPlanDraft] = Field(default_factory=list)


class PlannerAgent:
    name = "PlannerAgent"

    @staticmethod
    def _materialize_draft(
        request: TripPlanRequest,
        draft: ItineraryDraft,
        attractions: list[Attraction],
        hotels: list[Hotel],
    ) -> tuple[TripPlan, int]:
        """把 ID 草稿恢复为完整行程，并返回被拒绝的未知 ID 数量。"""
        by_id = {a.source_id: a for a in attractions if a.source_id}
        rejected = 0
        days: list[DayPlan] = []
        start = _date.fromisoformat(request.start_date)
        for index in range(request.total_days()):
            draft_day = draft.days[index] if index < len(draft.days) else DayPlanDraft()
            selected: list[Attraction] = []
            seen_ids: set[str] = set()
            for source_id in draft_day.attraction_ids:
                source = by_id.get(source_id)
                if source is None or source_id in seen_ids:
                    rejected += 1
                    continue
                seen_ids.add(source_id)
                selected.append(source.model_copy(deep=True))
            current_date = (start + _timedelta(days=index)).isoformat()
            hotel = (
                hotels[0].model_copy(deep=True)
                if hotels and current_date < request.end_date else None
            )
            days.append(DayPlan(
                day=index + 1,
                date=current_date,
                attractions=selected,
                meals=[Meal(
                    name=meal.name,
                    location=None,
                    price=meal.price,
                    cuisine=meal.cuisine,
                ) for meal in draft_day.meals],
                hotel=hotel,
                notes=draft_day.notes,
            ))
        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
        ), rejected

    @staticmethod
    def _repairable_draft_issues(
        request: TripPlanRequest,
        draft: ItineraryDraft,
        plan: TripPlan,
        rejected: int,
    ) -> list[str]:
        """返回值得让模型重做一次的结构问题。"""
        issues = []
        if len(draft.days) != request.total_days():
            issues.append("day_count")
        if rejected:
            issues.append("unknown_or_duplicate_attraction_id")
        if any(not day.attractions for day in plan.days):
            issues.append("empty_day")
        ids = [a.source_id for day in plan.days for a in day.attractions if a.source_id]
        if len(ids) != len(set(ids)):
            issues.append("duplicate_attraction_across_days")
        return issues

    @staticmethod
    def _haversine_km(a, b) -> float:
        """计算两点球面直线距离，避免为基础排序额外调用地图接口。"""
        lon1, lat1, lon2, lat2 = map(radians, (
            a.longitude, a.latitude, b.longitude, b.latitude,
        ))
        dlon, dlat = lon2 - lon1, lat2 - lat1
        h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 2 * 6371.0088 * asin(sqrt(h))

    @classmethod
    def _optimize_routes(cls, plan: TripPlan) -> None:
        """按最近邻排序每日景点，并记录可解释的直线距离基线。"""
        for day in plan.days:
            if not day.attractions:
                day.route_distance_km = 0.0
                continue
            remaining = list(day.attractions)
            ordered: list[Attraction] = []
            if day.hotel:
                current = day.hotel.location
            else:
                first = remaining.pop(0)
                ordered.append(first)
                current = first.location
            total = 0.0
            while remaining:
                next_attr = min(
                    remaining,
                    key=lambda item: cls._haversine_km(current, item.location),
                )
                total += cls._haversine_km(current, next_attr.location)
                ordered.append(next_attr)
                remaining.remove(next_attr)
                current = next_attr.location
            if day.hotel and ordered:
                total += cls._haversine_km(current, day.hotel.location)
            day.attractions = ordered
            day.route_distance_km = round(total, 1)

    @staticmethod
    def _enrich_driving_routes(plan: TripPlan) -> None:
        """用高德驾车路线替换直线距离；接口失败时保留可解释的直线距离。"""
        for day in plan.days:
            locations = [a.location for a in day.attractions]
            if day.hotel and locations:
                locations = [day.hotel.location, *locations, day.hotel.location]

            if settings.use_amap_driving_route and len(locations) >= 2:
                try:
                    pairs = list(zip(locations, locations[1:]))
                    with futures.ThreadPoolExecutor(max_workers=min(4, len(pairs))) as executor:
                        legs = list(executor.map(lambda pair: driving_route(*pair), pairs))
                    day.route_distance_km = round(
                        sum(float(leg["distance_km"]) for leg in legs), 1
                    )
                    day.route_duration_min = round(
                        sum(float(leg["duration_min"]) for leg in legs), 1
                    )
                    day.route_distance_source = "amap_driving"
                except Exception as exc:  # noqa: BLE001  单日路线失败可降级
                    logger.warning("Day%d 高德驾车路线失败，回退直线距离：%s", day.day, exc)

            if day.route_distance_source == "amap_driving":
                route_note = (
                    f"景点已按地理距离排序；高德驾车路线约 "
                    f"{day.route_distance_km:.1f} 公里 / {day.route_duration_min:.0f} 分钟"
                )
            else:
                route_note = (
                    f"景点已按地理距离排序，直线距离约 {day.route_distance_km or 0:.1f} 公里"
                    "（实际路程以地图导航为准）"
                )
            day.notes = (day.notes + "；" if day.notes else "") + route_note

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
    def _fill_empty_days(plan: TripPlan, candidates: list[Attraction]) -> None:
        """去重造成空日时，用尚未使用的真实候选 POI 确定性补位。"""
        used_ids = {
            attraction.source_id
            for day in plan.days
            for attraction in day.attractions
            if attraction.source_id
        }
        used_names = [
            _norm_name(attraction.name)
            for day in plan.days
            for attraction in day.attractions
        ]
        for day in plan.days:
            if day.attractions:
                continue
            available = [
                candidate for candidate in candidates
                if candidate.source_id not in used_ids
            ]
            diverse = [
                candidate for candidate in available
                if not any(
                    _same_scenic_area(_norm_name(candidate.name), used)
                    for used in used_names
                )
            ]
            for candidate in (diverse or available):
                normalized = _norm_name(candidate.name)
                day.attractions.append(candidate.model_copy(deep=True))
                if candidate.source_id:
                    used_ids.add(candidate.source_id)
                used_names.append(normalized)
                day.notes = (
                    (day.notes + "；" if day.notes else "")
                    + "模型去重后由系统从已验证 POI 候选中补充景点"
                )
                break

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
            f"  - [{a.source_id}] {a.name}（门票¥{a.ticket_price}，坐标 "
            f"{a.location.longitude},{a.location.latitude}）"
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
            f"你是资深旅行规划师。请生成最小行程草稿。\n"
            f"请求：{request.model_dump_json()}\n"
            f"候选景点（共 {len(attractions)} 个，均为不同景区）：\n{attr_text}\n"
            f"候选酒店：\n{hotel_text}\n"
            f"天气：\n{w_text}\n\n"
            f"要求：\n"
            f"1. days 必须恰好有 {max(total_days, 1)} 项，每项代表连续一天；\n"
            f"2. 每天安排 2-3 个景点，只把候选方括号中的 ID 填入 attraction_ids；\n"
            f"3. 【防重复】每天必须去**不同的景区**，任何景点（含同一景区的子景点）"
            f"在整个行程中只能出现一次——严禁把同一景区排进多天；\n"
            f"4. 每天含午餐建议；把相邻/顺路的景点排到同一天；\n"
            f"5. 不输出城市、日期、酒店、坐标、门票、预算或天气，这些由系统补全。"
        )
        llm = get_llm(temperature=0.2)
        chain = structured_chain(llm, ItineraryDraft)
        draft: ItineraryDraft = chain.invoke(prompt)
        plan, rejected = self._materialize_draft(request, draft, attractions, hotels)
        issues = self._repairable_draft_issues(request, draft, plan, rejected)
        if issues:
            logger.info("规划草稿触发一次受控修复：%s", issues)
            repair_prompt = (
                prompt
                + "\n上一次草稿存在这些问题："
                + "、".join(issues)
                + "。请重新生成完整草稿；这是唯一一次修复机会。"
            )
            draft = chain.invoke(repair_prompt)
            plan, rejected = self._materialize_draft(request, draft, attractions, hotels)
            remaining = self._repairable_draft_issues(request, draft, plan, rejected)
            if remaining:
                logger.warning("规划草稿修复后仍有问题：%s", remaining)

        # 后处理：跨天景点去重（LLM 偶发违规，同名或同一景区子景点视为重复，
        # 只保留首次出现，保证「每天不同景区」的体验）。
        self._dedupe_attractions_across_days(plan)
        self._fill_empty_days(plan, attractions)

        # 后处理：酒店只出现在「过夜的晚上」。N 天行程 = N-1 晚，返程当天不住店；
        # 把返程日（及之后）的 hotel 置空，避免时间轴显示「多订一晚」。
        self._strip_return_day_hotel(plan, request)

        # 酒店：多晚住同一家（hotels[0] 已是高德真实候选 + 参考价 + 档次/评分），
        # 统一替换所有过夜日的 hotel，并覆盖 LLM 可能臆造/改写的名称与价格。
        hotel = self._apply_single_hotel(plan, hotels)

        # 最近邻排序后用高德驾车路线补充真实道路距离与时长；接口失败自动回退直线距离。
        self._optimize_routes(plan)
        self._enrich_driving_routes(plan)

        # 用每日中段景点附近的高德真实餐厅覆盖模型餐饮建议；查询失败时保留原建议。
        for day_number, meal in recommend_restaurants(plan.days).items():
            day = next((item for item in plan.days if item.day == day_number), None)
            if day is not None:
                day.meals = [meal]

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
            display_trains = PlannerAgent._pick_display_trains(trains, best, _MAX_DISPLAY, date=date)
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
    def _pick_display_trains(trains: list[dict], best: dict, max_display: int = 10, date: str = "") -> list[dict]:
        """从 trains 里选最多 max_display 条展示，保证推荐车次在第 1 位。

        - 若 best 已在前 max_display 条：移到首位，其余候选保持顺序；
        - 若不在：单独给 best 补一次真实票价（否则前 10 都没补到 best，价格空缺），
          并把 best 插入第 1 位，整体仍保持 max_display 条。

        返回新列表（不会就地修改原 trains）。
        """
        display = list(trains[:max_display])
        if any(t.get("train_no") == best.get("train_no") for t in display):
            return [best] + [t for t in display if t.get("train_no") != best.get("train_no")]
        best_with_prices = PlannerAgent._ensure_train_prices(best, date)
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
        active_days = [day for day in days if day.attractions]
        if not active_days:
            return None

        def estimate(day: DayPlan) -> float:
            first = day.attractions[0]
            result = provider.estimate_ride_by_coords(
                hotel.location.latitude, hotel.location.longitude,
                first.location.latitude, first.location.longitude,
                start_label="酒店", end_label=first.name,
            )
            return float(result["estimated_fare"]) * 2

        try:
            with futures.ThreadPoolExecutor(max_workers=min(4, len(active_days))) as executor:
                fares = list(executor.map(estimate, active_days))
            total = sum(fares)
        except Exception as e:
            logger.warning("市内打车估算失败，回退按天估算：%s", e)
            return None
        return int(total) if total > 0 else None
