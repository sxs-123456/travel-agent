"""天气补充源：Open-Meteo（免费、无 key、最多 16 天逐日预报）。

背景：高德免费接口（extensions=all）多天预报最多 4 天（当天 + 3 天），
行程超过 4 天时，用 Open-Meteo 补充第 5 天及以后的数据。

Open-Meteo：
- 基于 ECMWF 全球预报，提供最多 16 天逐日天气（气温/天气代码）；
- 免费、无需 key、结构化 JSON，内置 geocoding 支持中文城市名；
- 定位为「补充源」：失败时返回 None，由上层保持高德 4 天并给出提示，绝不造假。
"""
from __future__ import annotations

import logging

import httpx

from backend.models.trip import WeatherInfo

logger = logging.getLogger("trip-planner")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_MAX_DAYS = 16  # Open-Meteo 免费接口单次预报上限

# WMO 天气代码 -> 中文（与高德 condition 口径一致：晴/多云/小雨…）
_WMO_CODE_TO_ZH: dict[int, str] = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹",
}


def _condition(code: int) -> str:
    return _WMO_CODE_TO_ZH.get(code, "未知")


def open_meteo_daily(city: str, days: int = 16) -> list[WeatherInfo] | None:
    """查询 Open-Meteo 逐日天气（最多 16 天），返回 [{date, temperature, condition}]。

    失败（城市未识别 / 网络 / 接口异常）返回 None，不抛错，由上层回退到高德 4 天。
    """
    if not city or days <= 0:
        return None
    try:
        geo = httpx.get(
            GEOCODING_URL,
            params={"name": city, "count": 1, "language": "zh"},
            timeout=10,
        )
        geo.raise_for_status()
        results = (geo.json().get("results") or [])
        if not results:
            logger.warning("Open-Meteo 未识别城市：%s", city)
            return None
        lat = results[0]["latitude"]
        lon = results[0]["longitude"]

        resp = httpx.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "Asia/Shanghai",
                "forecast_days": min(max(days, 1), _MAX_DAYS),
            },
            timeout=12,
        )
        resp.raise_for_status()
        daily = resp.json().get("daily") or {}
        times = daily.get("time") or []
        codes = daily.get("weather_code") or []
        tmax = daily.get("temperature_2m_max") or []
        if not times:
            return None

        out = []
        for i, date in enumerate(times):
            code = codes[i] if i < len(codes) else 0
            temp = tmax[i] if i < len(tmax) else 0
            try:
                temperature = int(round(float(temp)))
            except (TypeError, ValueError):
                temperature = 0
            out.append(WeatherInfo(
                date=date,
                temperature=temperature,
                condition=_condition(code),
            ))
        return out
    except Exception as exc:  # noqa: BLE001  补充源失败不影响主流程
        logger.warning("Open-Meteo 天气补充失败（%s）：%s", city, exc)
        return None
