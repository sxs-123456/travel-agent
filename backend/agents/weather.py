"""天气查询 Agent：查询目的地天气，构造 WeatherInfo 列表。

天气来自高德真实接口（已解析为 WeatherInfo），无需 LLM 再生成，直接返回真实结果。
高德免费接口多天预报最多 4 天；行程超过 4 天时，用 Open-Meteo（免费、无 key、
最多 16 天）补充剩余天数。补充失败时保持高德 4 天，由 planner 对缺失日加备注。
"""
from __future__ import annotations

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

from backend.tools.amap import weather
from backend.tools.weather_extra import open_meteo_daily


class WeatherQueryAgent:
    name = "WeatherQueryAgent"

    def run(self, request) -> list:
        """返回行程日期范围内的逐日真实天气。

        预报总是「从今天起」：高德取前 4 天（官方上限），第 5 天及以后用
        Open-Meteo 补充（免费 16 天）；按日期合并、高德优先；最后过滤到
        [出发日, 返程日] 区间。补充失败则只返回高德 4 天内落在行程区间的部分。
        """
        try:
            start = _date.fromisoformat(request.start_date)
            end = _date.fromisoformat(request.end_date)
            # 从今天到行程结束需要多少天预报（至少 1 天）
            span = max((end - _date.today()).days + 1, 1)
        except (ValueError, TypeError):
            start = end = None
            span = request.total_days()

        out = weather(request.city, span)  # 高德：最多 4 天（今天起）
        if len(out) < span:
            extra = open_meteo_daily(request.city, span)
            if extra:
                by_date = {w.date: w for w in out}
                for w in extra:
                    by_date.setdefault(w.date, w)  # 高德日期优先，不覆盖
                out = sorted(by_date.values(), key=lambda w: w.date)

        if start is not None and end is not None:
            out = [w for w in out
                   if start <= _date.fromisoformat(w.date) <= end]
        return out
