"""高德餐厅推荐：按每日景点坐标返回附近的真实餐饮 POI。"""
from __future__ import annotations

import concurrent.futures as futures
import logging
from functools import lru_cache

import httpx

from backend.config import settings
from backend.models.trip import DayPlan, Location, Meal

logger = logging.getLogger("trip-planner")
_AROUND_URL = "https://restapi.amap.com/v3/place/around"


@lru_cache(maxsize=256)
def _search_near(longitude: float, latitude: float) -> tuple[Meal, ...]:
    """检索坐标 5 公里内的餐厅，优先返回有真实人均消费的结果。"""
    if not settings.use_real_amap:
        return ()
    response = httpx.get(
        _AROUND_URL,
        params={
            "key": settings.amap_api_key,
            "location": f"{longitude},{latitude}",
            "types": "050000",
            "radius": "5000",
            "sortrule": "distance",
            "offset": "20",
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "1":
        raise RuntimeError(f"高德餐厅检索失败：{data.get('info') or '未知错误'}")

    meals: list[Meal] = []
    for poi in data.get("pois") or []:
        raw_location = poi.get("location", "")
        if "," not in raw_location:
            continue
        try:
            lng, lat = (float(value) for value in raw_location.split(","))
        except (TypeError, ValueError):
            continue
        raw_cost = (poi.get("biz_ext") or {}).get("cost")
        try:
            cost = int(float(raw_cost)) if raw_cost not in (None, "", []) else 0
        except (TypeError, ValueError):
            cost = 0
        categories = [item for item in str(poi.get("type") or "").split(";") if item]
        cuisine = categories[-1] if categories else "餐饮"
        meals.append(Meal(
            source_id=poi.get("id") or None,
            name=poi.get("name") or "附近餐厅",
            location=Location(
                longitude=lng,
                latitude=lat,
                address=poi.get("address") or None,
            ),
            price=cost,
            cuisine=cuisine,
            price_source=("高德 POI 人均消费" if cost else "高德未提供人均消费"),
            price_is_estimated=False,
        ))
    meals.sort(key=lambda meal: (meal.price <= 0,))
    return tuple(meals)


def recommend_restaurants(days: list[DayPlan]) -> dict[int, Meal]:
    """为有景点的每天推荐一家附近真实餐厅，跨天不重复；失败日由调用方保留原建议。"""
    anchors = [
        (day.day, day.attractions[len(day.attractions) // 2].location)
        for day in days
        if day.attractions
    ]
    if not anchors:
        return {}

    def fetch(item: tuple[int, Location]) -> tuple[int, tuple[Meal, ...]]:
        day_number, location = item
        try:
            return day_number, _search_near(
                round(location.longitude, 6), round(location.latitude, 6)
            )
        except Exception as exc:  # noqa: BLE001  餐厅是可降级的辅助信息
            logger.warning("Day%d 高德餐厅检索失败，保留模型餐饮建议：%s", day_number, exc)
            return day_number, ()

    with futures.ThreadPoolExecutor(max_workers=min(4, len(anchors))) as executor:
        results = list(executor.map(fetch, anchors))

    recommendations: dict[int, Meal] = {}
    used_ids: set[str] = set()
    used_names: set[str] = set()
    for day_number, candidates in results:
        chosen = next(
            (
                candidate for candidate in candidates
                if (not candidate.source_id or candidate.source_id not in used_ids)
                and candidate.name not in used_names
            ),
            None,
        )
        if chosen is None:
            continue
        recommendations[day_number] = chosen.model_copy(deep=True)
        if chosen.source_id:
            used_ids.add(chosen.source_id)
        used_names.add(chosen.name)
    return recommendations
