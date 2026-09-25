"""打车（用车）估算供应商：地图驾车路线规划（真实距离 / 时长）+ 参考价估算。

融合自 Agent2Agent 出行助手（D:/develop/PythonProject/agent/taxi.py）。
国内网约车「真实叫车下单」需企业合作，个人无公开 API；但「真实距离 / 时长」
可通过地图路径规划 Web 服务获取，再按出租车计价规则给出参考价（不叫车、不下单）。

当前使用百度地图（BAIDU_MAP_AK）驾车路线规划。旅行助手场景里景点/酒店已含
经纬度（来自高德 POI），故提供 `estimate_ride_by_coords` 直接以坐标规划路线，
无需地理编码。仅真实模式：缺失 key 或接口异常抛出 TaxiApiError，由上层回退估算。
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from backend.config import settings


class TaxiApiError(RuntimeError):
    """打车估算无法返回可信真实结果时抛出（用于友好报错，不造假）。"""


def estimate_fare(
    start: str,
    end: str,
    distance_m: float,
    duration_s: float,
    city: str = "",
    to_label: str = "",
) -> dict[str, Any]:
    """根据距离(米)和时长(秒)估算打车参考价：起步价 + 里程费 + 低速等候费。"""
    km = distance_m / 1000.0
    mins = duration_s / 60.0
    base = float(os.getenv("TAXI_BASE_FARE", "14"))
    first_km = float(os.getenv("TAXI_BASE_KM", "3"))
    per_km = float(os.getenv("TAXI_PER_KM", "2.6"))
    per_min = float(os.getenv("TAXI_PER_MIN", "0.5"))
    fare = base + max(km - first_km, 0) * per_km + mins * per_min
    return {
        "from": start, "to": to_label or end, "city": city or None,
        "distance_km": round(km, 2), "duration_min": round(mins, 1),
        "estimated_fare": round(fare, 2), "currency": "CNY",
        "fare_note": "参考价（起步价+里程+低速等候），实际网约车价以平台为准",
    }


class BaiduRideProvider:
    """百度地图驾车路线规划：以坐标查询真实距离 / 时长，套计价规则给参考价。"""

    name = "百度地图-驾车路线规划(真实距离/时长)"
    DRIVE_URL = "https://api.map.baidu.com/direction/v2/driving"

    def __init__(self) -> None:
        self.ak = settings.baidu_map_ak
        self.timeout = int(os.getenv("TRAVEL_API_TIMEOUT_SECONDS", "15"))

    def _require(self) -> None:
        if not self.ak:
            raise TaxiApiError(
                "未配置 BAIDU_MAP_AK，无法估算真实市内交通。请到 https://lbsyun.baidu.com/ "
                "申请「服务端」AK（启用 路线规划），并写入 .env。"
            )

    def estimate_ride_by_coords(
        self,
        s_lat: float, s_lng: float,
        e_lat: float, e_lng: float,
        start_label: str = "起点", end_label: str = "终点",
    ) -> dict[str, Any]:
        """以起终点经纬度估算驾车参考价（真实距离/时长）。"""
        self._require()
        try:
            resp = httpx.get(
                self.DRIVE_URL,
                params={
                    "origin": f"{s_lat},{s_lng}",
                    "destination": f"{e_lat},{e_lng}",
                    "ak": self.ak,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TaxiApiError(f"百度路径规划请求失败：{exc}") from exc

        if data.get("status") != 0 or not (data.get("result") or {}).get("routes"):
            raise TaxiApiError(f"百度路径规划失败：{data.get('message') or data}")
        route = data["result"]["routes"][0]
        return estimate_fare(
            start_label, end_label,
            float(route.get("distance", 0)),
            float(route.get("duration", 0)),
            "", end_label,
        )
