"""高德地图工具：文本搜索（POI）、天气查询、酒店检索（v5）。

本项目仅支持真实 HTTP 模式，无任何 Mock / 演示数据；缺失密钥或接口异常会抛出清晰错误。
"""
from __future__ import annotations

import logging

import httpx

from backend.config import settings
from backend.models.trip import Location, WeatherInfo

logger = logging.getLogger("trip-planner")

AMAP_V3 = "https://restapi.amap.com/v3"
AMAP_V5 = "https://restapi.amap.com/v5"


# ---------------------------------------------------------------------------
# 真实 API 解析
# ---------------------------------------------------------------------------
def _parse_pois(data: dict) -> list[dict]:
    """解析高德 v3/place/text 返回的 POI（名称/坐标/地址/类型/人均）。"""
    results = []
    for poi in data.get("pois", [])[:20]:
        loc = poi.get("location", "")
        if not loc or "," not in loc:
            continue
        try:
            lon, lat = (float(x) for x in loc.split(","))
        except ValueError:
            continue
        biz = poi.get("biz_ext") or {}
        image_url = _first_poi_photo(poi)
        cost = 0
        if biz.get("cost"):
            try:
                cost = int(float(biz["cost"]))
            except (ValueError, TypeError):
                cost = 0
        results.append({
            "source_id": poi.get("id") or "",
            "name": poi.get("name", ""),
            "location": Location(
                longitude=lon, latitude=lat,
                address=poi.get("address", ""),
            ),
            "ticket_price": cost,
            "description": poi.get("type", "") or poi.get("address", ""),
            "image_url": image_url,
            "image_source": "高德 POI" if image_url else None,
        })
    return results


def _first_poi_photo(poi: dict) -> str | None:
    """读取 POI 接口附带的实景照片；没有照片时由图库搜索补充。"""
    photos = poi.get("photos") or []
    if isinstance(photos, dict):
        photos = [photos]
    if not isinstance(photos, list):
        return None
    for photo in photos:
        if isinstance(photo, str):
            url = photo
        elif isinstance(photo, dict):
            url = photo.get("url") or photo.get("photo_url")
        else:
            continue
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def _parse_weather(data: dict, days: int) -> list[WeatherInfo]:
    """解析高德 v3/weather/weatherInfo?extensions=all 的多天预报。"""
    forecasts = data.get("forecasts") or []
    if not forecasts:
        raise ValueError("高德天气接口未返回 forecasts 数据")
    casts = forecasts[0].get("casts", [])
    if not casts:
        raise ValueError("高德天气接口未返回 casts 数据")
    out = []
    for cast in casts[: max(1, days)]:
        date = cast.get("date", "")
        condition = cast.get("dayweather") or cast.get("nightweather") or "未知"
        temp_raw = cast.get("daytemp_float") or cast.get("daytemp") or "20"
        try:
            temp = int(float(temp_raw))
        except (ValueError, TypeError):
            temp = 20
        out.append(WeatherInfo(date=date, condition=condition, temperature=temp))
    return out


# ---------------------------------------------------------------------------
# 对外接口（仅真实模式）
# ---------------------------------------------------------------------------
def text_search(keywords: str, city: str) -> list[dict]:
    """高德 POI 关键词搜索，返回统一结构的 dict 列表。

    缺失高德密钥或接口返回错误时抛出清晰异常，不返回任何虚假数据。
    """
    if not settings.use_real_amap:
        raise RuntimeError(
            "未配置 AMAP_API_KEY，无法在真实模式下进行 POI 搜索。"
            "请在 .env 中填入高德 Web 服务 Key 后重试。"
        )

    params = {
        "key": settings.amap_api_key,
        "keywords": keywords,
        "city": city,
        "citylimit": "true",
        "offset": "20",
    }
    resp = httpx.get(f"{AMAP_V3}/place/text", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        raise RuntimeError(
            f"高德 POI 搜索失败：{data.get('info')}（status={data.get('status')}）。"
            "请检查 AMAP_API_KEY 是否有效及 key 的服务权限。"
        )
    results = _parse_pois(data)
    if not results:
        raise RuntimeError(
            f"高德未返回「{city}」的 POI 结果，请确认城市名称或放宽关键词。"
        )
    return results


def weather(city: str, days: int = 1) -> list[WeatherInfo]:
    """查询城市天气，支持多天预报（高德 extensions=all）。"""
    if not settings.use_real_amap:
        raise RuntimeError(
            "未配置 AMAP_API_KEY，无法在真实模式下查询天气。"
            "请在 .env 中填入高德 Web 服务 Key 后重试。"
        )

    params = {"key": settings.amap_api_key, "city": city, "extensions": "all"}
    resp = httpx.get(f"{AMAP_V3}/weather/weatherInfo", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        raise RuntimeError(
            f"高德天气查询失败：{data.get('info')}（status={data.get('status')}）。"
            "请检查 AMAP_API_KEY 是否有效。"
        )
    out = _parse_weather(data, days)
    if len(out) < days:
        logger.info(
            "高德仅返回 %d 天预报，已覆盖请求的 %d 天（多天预报上限为 4 天）。",
            len(out), days,
        )
    return out


def driving_route(origin: Location, destination: Location) -> dict[str, float | str]:
    """查询两个高德坐标之间的真实驾车距离与预计时长。"""
    if not settings.use_real_amap:
        raise RuntimeError("未配置 AMAP_API_KEY，无法查询驾车路线。")

    params = {
        "key": settings.amap_api_key,
        "origin": f"{origin.longitude},{origin.latitude}",
        "destination": f"{destination.longitude},{destination.latitude}",
        "strategy": "0",
        "extensions": "base",
    }
    resp = httpx.get(f"{AMAP_V3}/direction/driving", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    paths = (data.get("route") or {}).get("paths") or []
    if data.get("status") != "1" or not paths:
        raise RuntimeError(
            f"高德驾车路线查询失败：{data.get('info') or '未返回可用路径'}"
        )
    try:
        distance_km = float(paths[0]["distance"]) / 1000
        duration_min = float(paths[0]["duration"]) / 60
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("高德驾车路线返回了无效的距离或时长") from exc
    return {
        "distance_km": round(distance_km, 1),
        "duration_min": round(duration_min, 1),
        "source": "amap_driving",
    }


def transit_route(
    origin: Location, destination: Location, city: str
) -> dict[str, float | list[str] | str]:
    """Query AMap public transit directions and return a compact route summary."""
    if not settings.use_real_amap:
        raise RuntimeError("AMAP_API_KEY is required for transit directions")

    params = {
        "key": settings.amap_api_key,
        "origin": f"{origin.longitude},{origin.latitude}",
        "destination": f"{destination.longitude},{destination.latitude}",
        "city": city,
        "cityd": city,
        "strategy": "0",
        "nightflag": "0",
        "extensions": "base",
    }
    resp = httpx.get(f"{AMAP_V3}/direction/transit/integrated", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    transits = (data.get("route") or {}).get("transits") or []
    if data.get("status") != "1" or not transits:
        raise RuntimeError("AMap did not return a usable transit route")

    route = transits[0]
    lines: list[str] = []
    for segment in route.get("segments") or []:
        buslines = ((segment.get("bus") or {}).get("buslines") or [])
        for busline in buslines:
            name = str(busline.get("name") or "").split("(", 1)[0].strip()
            departure = str((busline.get("departure_stop") or {}).get("name") or "").strip()
            arrival = str((busline.get("arrival_stop") or {}).get("name") or "").strip()
            if name:
                detail = name
                if departure and arrival:
                    detail += f" ({departure}->{arrival})"
                if detail not in lines:
                    lines.append(detail)
        railway = segment.get("railway") or {}
        railway_name = str(railway.get("name") or "").strip()
        if railway_name and railway_name not in lines:
            lines.append(railway_name)

    try:
        duration_min = round(float(route.get("duration") or 0) / 60)
        walking_km = round(float(route.get("walking_distance") or 0) / 1000, 1)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("AMap returned invalid transit duration data") from exc
    return {
        "duration_min": duration_min,
        "walking_km": walking_km,
        "lines": lines,
        "source": "amap_transit",
    }


# ---------------------------------------------------------------------------
# 酒店检索（高德 v5：真实酒店 + 官方档次/评分）
# ---------------------------------------------------------------------------
# 城市系数（用于酒店参考估算，非官方报价；与旧项目 A2A 出行助手口径一致）
_CITY_COEFF: dict[str, float] = {
    "北京": 1.3, "上海": 1.3, "广州": 1.15, "深圳": 1.25, "杭州": 1.1,
    "成都": 1.0, "武汉": 0.95, "西安": 0.95, "南京": 1.05, "重庆": 0.95,
    "苏州": 1.05, "天津": 1.0, "长沙": 0.95, "青岛": 1.0, "厦门": 1.1,
}
# 酒店档次 -> 每晚基准价（元），再乘城市系数
_LEVEL_BASE: dict[str, float] = {
    "经济型": 180.0, "舒适型": 320.0, "高档型": 520.0, "豪华型": 880.0,
}

# 住宿档次 -> (高德有效检索词, 结果 level 需命中的关键字)
# 说明：高德 v5 对「豪华型酒店」「舒适型酒店」等字面词不敏感，直接当关键词会返回
# 大量经济型/青年旅舍/旅馆等无关结果（实测「豪华型酒店」返回的全是经济型）。
# 必须换成高德能命中的词（如「五星级酒店」→ level=豪华型），再按返回的
# level 字段（biz.keytag/rectag，实测主要为 经济型/豪华型/商务酒店/青年旅舍/旅馆）
# 二次过滤，才能做到「选什么档次就推荐什么档次」。
_HOTEL_TIERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "豪华": ("五星级酒店", ("豪华", "五星", "度假", "国际")),
    "高档": ("四星级酒店", ("高档", "四星", "豪华")),
    "舒适": ("三星级酒店", ("舒适", "三星", "商务")),
    "经济": ("快捷酒店", ("经济", "快捷", "便捷", "旅馆", "青年", "青旅")),
    "青年": ("青年旅舍", ("青年", "青旅", "旅舍")),
}


def infer_hotel_tier(budget_level: str) -> str | None:
    """从预算等级推断酒店档次：豪华/高档/舒适/经济/青年；无法推断返回 None。

    酒店档次完全由预算等级决定（已移除独立的『住宿偏好』选项）：
    - 豪华 → 豪华档（五星级）
    - 中等 → 舒适档（三星级）
    - 经济 → 经济档（快捷/便捷）
    """
    if not budget_level:
        return None
    mapping = {"豪华": "豪华", "中等": "舒适", "经济": "经济"}
    return mapping.get(budget_level)


def estimate_hotel_price(level: str | None, rating: float | None, city: str) -> float | None:
    """按酒店档次（优先）或评分粗算每晚参考价；返回 None 表示无法估算。

    明确为「参考估算」：免费接口（高德 v3/v5 实测）均不再返回酒店房价，
    该估算按城市档次 + 官方标注的酒店档次/评分粗算，仅用于预算参考，
    最终以携程/同程/美团实际报价为准。
    """
    base: float | None = None
    if level:
        for k, v in _LEVEL_BASE.items():
            if k in level:
                base = v
                break
    if base is None and rating is not None:
        if rating >= 4.7:
            base = 360.0
        elif rating >= 4.3:
            base = 260.0
        elif rating >= 4.0:
            base = 200.0
        else:
            base = 160.0
    if base is None:
        return None
    coeff = 1.0
    for c, k in _CITY_COEFF.items():
        if c in (city or ""):
            coeff = k
            break
    return round(base * coeff / 10) * 10


def hotel_search(city: str, keywords: str = "酒店", limit: int = 10, tier: str | None = None) -> list[dict]:
    """高德 v5 POI 酒店检索：返回真实酒店（名称/坐标/地址/官方档次/评分）。

    返回结构（与 text_search 对齐）：
      {name, location(Location), address, level(档次), rating(评分),
       price_estimate(参考估算价), price_source}
    若 POI 返回 photos 字段则保留照片 URL，缺图时由 planner 统一补充。

    tier（可选）：住宿档次（豪华/高档/舒适/经济/青年）。传入后：
      1. 用高德能命中的检索词替换字面关键词（避免「豪华型酒店」搜出经济型）；
      2. 按返回的 level 字段过滤，只保留命中目标档次的酒店（不足 2 家则保留全部，
         避免过滤过严导致无候选）。
    免费接口不返回房价（v3 的 biz_ext.cost 与 v5 的 business 均无价格字段，实测确认），
    价格一律用 estimate_hotel_price 参考估算并明确标注。
    """
    if not settings.use_real_amap:
        raise RuntimeError(
            "未配置 AMAP_API_KEY，无法在真实模式下检索酒店。"
            "请在 .env 中填入高德 Web 服务 Key 后重试。"
        )

    # 档次过滤：按偏好档次换用高德有效检索词，并对结果按 level 二次过滤。
    filter_levels: tuple[str, ...] | None = None
    if tier and tier in _HOTEL_TIERS:
        keywords, filter_levels = _HOTEL_TIERS[tier]

    params = {
        "key": settings.amap_api_key,
        "keywords": keywords,
        "region": city,
        "types": "100000",  # 住宿服务大类
        "page_size": str(limit),
        "show_fields": "business,photos",
    }
    resp = httpx.get(
        "https://restapi.amap.com/v5/place/text", params=params, timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        raise RuntimeError(
            f"高德酒店检索失败：{data.get('info')}（status={data.get('status')}）。"
            "请检查 AMAP_API_KEY 是否有效及 key 的服务权限。"
        )
    results: list[dict] = []
    for poi in data.get("pois", []):
        loc = poi.get("location", "")
        if not loc or "," not in loc:
            continue
        try:
            lon, lat = (float(x) for x in loc.split(","))
        except ValueError:
            continue
        biz = poi.get("business") or {}
        rating_raw = biz.get("rating")
        try:
            rating = float(rating_raw) if rating_raw not in (None, "") else None
        except (TypeError, ValueError):
            rating = None
        level = biz.get("keytag") or biz.get("rectag") or None
        price = estimate_hotel_price(level, rating, city)
        image_url = _first_poi_photo(poi)
        results.append({
            "name": poi.get("name", ""),
            "location": Location(
                longitude=lon, latitude=lat,
                address=poi.get("address", ""),
            ),
            "level": level,
            "rating": rating,
            "price_estimate": price,
            "price_source": "参考估算（免费接口无真实房价，按档次/评分粗算，以携程/美团实际为准）",
            "image_url": image_url,
            "image_source": "高德 POI" if image_url else None,
        })

    # 按档次过滤：仅保留 level 命中目标档次关键字的酒店；命中不足 2 家则保留全部原始结果。
    if filter_levels:
        matched = [
            r for r in results
            if r.get("level") and any(k in (r["level"] or "") for k in filter_levels)
        ]
        if len(matched) >= 2:
            results = matched

    if not results:
        raise RuntimeError(
            f"高德未在「{city}」检索到酒店，请确认城市名称或调整住宿偏好。"
        )
    return results
