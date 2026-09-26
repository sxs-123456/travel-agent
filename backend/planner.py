"""多智能体编排器：串联四个专属 Agent 完成一次完整行程规划。

仅真实模式：所有外部依赖（LLM / 高德）均需配置密钥；缺失时抛出清晰错误。
"""
from __future__ import annotations

import concurrent.futures as _futures
import logging
from time import perf_counter
from uuid import uuid4

from backend.agents import (
    AttractionSearchAgent,
    HotelAgent,
    PlannerAgent,
    WeatherQueryAgent,
)
from backend.config import settings
from backend.models.trip import GenerationMetrics, TripPlan, TripPlanRequest
from backend.observability import LlmUsageTracker, current_llm_usage_tracker
from backend.tools.images import search_image
from backend.quality import evaluate_plan
from backend.tracing import request_id as current_request_id

logger = logging.getLogger("trip-planner")


class TripPlannerAgent:
    """顶层 Agent：协调景点/天气/酒店/规划四个子 Agent。"""

    def __init__(self) -> None:
        self.attraction_agent = AttractionSearchAgent()
        self.weather_agent = WeatherQueryAgent()
        self.hotel_agent = HotelAgent()
        self.planner_agent = PlannerAgent()

    def plan_trip(self, request: TripPlanRequest) -> TripPlan:
        # 启动期校验：真实模式必须配置关键密钥，缺失即给出明确提示。
        self._require_real_mode()

        trace_id = current_request_id.get() or uuid4().hex
        usage_tracker = LlmUsageTracker()

        def run_stage(name, fn, *args):
            started = perf_counter()
            status = "ok"
            try:
                token = current_llm_usage_tracker.set(usage_tracker)
                return fn(*args)
            except Exception:
                status = "error"
                raise
            finally:
                current_llm_usage_tracker.reset(token)
                logger.info("agent_stage trace_id=%s stage=%s status=%s duration_ms=%.2f",
                            trace_id, name, status, (perf_counter() - started) * 1000)

        # 三个子 Agent 互不依赖，并行执行以缩短端到端耗时。
        with _futures.ThreadPoolExecutor(max_workers=3) as ex:
            f_attr = ex.submit(run_stage, "attractions", self.attraction_agent.run, request)
            f_weather = ex.submit(run_stage, "weather", self.weather_agent.run, request)
            f_hotels = ex.submit(run_stage, "hotels", self.hotel_agent.run, request)
            attractions = f_attr.result()
            weather = f_weather.result()
            hotels = f_hotels.result()

        # 整合为完整行程 + 预算（预算与天气均基于真实数据，不依赖 LLM 臆造）。
        plan = run_stage("planning", self.planner_agent.run, request, attractions, weather, hotels)

        # 用真实天气覆盖 LLM 可能「重新生成」的 weather_info，确保仅真实数据。
        plan.weather_info = list(weather)

        # 高德多天预报上限为 4 天，超出部分已由 Open-Meteo 尽力补充；
        # 若补充源也失败，则在逐日备注中如实提示。
        forecast_dates = {w.date for w in weather}
        for d in plan.days:
            if d.date not in forecast_dates:
                suffix = "（该日暂无天气预报，未提供）"
                d.notes = (d.notes + "；" if d.notes else "") + suffix

        # 优先保留 POI 实景图；缺图时并发检索、缓存和去重（Pexels → Openverse）。
        run_stage("images", self._enrich_images, plan)
        plan.generation_metrics = GenerationMetrics(**usage_tracker.snapshot(
            model=settings.llm_model,
            input_cost_per_1m_usd=settings.llm_input_cost_per_1m_usd,
            output_cost_per_1m_usd=settings.llm_output_cost_per_1m_usd,
        ))
        report = evaluate_plan(request, plan)
        logger.info(
            "plan_quality trace_id=%s report=%s llm_usage=%s",
            trace_id, report, plan.generation_metrics.model_dump(),
        )
        return plan

    @staticmethod
    def _require_real_mode() -> None:
        missing = []
        if not settings.use_real_llm:
            missing.append("LLM_API_KEY")
        if not settings.use_real_amap:
            missing.append("AMAP_API_KEY")
        if missing:
            raise RuntimeError(
                "当前为真实模式，但缺少必要密钥：" + "、".join(missing) +
                "。请在 .env 中配置后重试（参考 .env.example）。"
            )

    @staticmethod
    def _enrich_images(plan: TripPlan) -> None:
        # 优先保留 POI 数据源附带的地点照片；缺图时再查 Pexels/Openverse。
        # LLM 输出不会直接成为照片来源。外部检索使用「城市 + 景点/酒店名」减少同名误配。
        jobs: list[tuple[object, str, str]] = []  # (obj, search query, group key)
        grouped: dict[str, list[object]] = {}
        for day in plan.days:
            for a in day.attractions:
                grouped.setdefault(a.name, []).append(a)
            if day.hotel:
                grouped.setdefault(day.hotel.name, []).append(day.hotel)

        used_urls: set[str] = set()
        for keyword, items in grouped.items():
            poi_photo = next((
                item for item in items
                if getattr(item, "image_source", None) == "高德 POI" and item.image_url
            ), None)
            if poi_photo:
                for target in items:
                    target.image_url = poi_photo.image_url
                    target.image_source = "高德 POI"
                used_urls.add(poi_photo.image_url.split("?")[0])
            else:
                query = f"{plan.city} {keyword}".strip()
                jobs.append((items[0], query, keyword))

        if not jobs:
            return

        def _fetch(item: tuple[object, str, str]) -> tuple[object, str, str, str | None]:
            obj, query, group_key = item
            try:
                return obj, query, group_key, search_image(query)
            except Exception:  # noqa: BLE001  图片为辅助信息，单张失败不影响整体
                logger.warning("封面图检索失败：%s", query)
                return obj, query, group_key, None

        with _futures.ThreadPoolExecutor(max_workers=min(8, len(jobs))) as ex:
            results = list(ex.map(_fetch, jobs))

        for obj, query, group_key, url in results:
            base = (url or "").split("?")[0]
            if url and base not in used_urls:
                used_urls.add(base)
                obj.image_url = url
                obj.image_source = "Pexels" if "pexels.com" in url.lower() else "Openverse"
                continue
            # 撞图 / 检索失败：带已用图集合补查一次（并发下极少发生，串行兜底）
            try:
                url2 = search_image(query, exclude=used_urls)
            except Exception:  # noqa: BLE001
                url2 = None
            if url2:
                used_urls.add(url2.split("?")[0])
                obj.image_url = url2
                obj.image_source = "Pexels" if "pexels.com" in url2.lower() else "Openverse"
            else:
                obj.image_url = None
                obj.image_source = None

        for obj, _query, keyword in jobs:
            for target in grouped[keyword]:
                target.image_url = obj.image_url
                target.image_source = obj.image_source
