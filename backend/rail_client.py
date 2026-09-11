"""12306 铁路票价客户端：直连 12306 官方接口（真实、免费、免 key、免 npx）。

薄封装层：对 planner 提供 `available` / `search_with_prices` / `recommend`
等高层接口；底层实现在 `backend/tools/train.py` 的 `TrainTicketProvider`。
由 `USE_RAIL_MCP`（默认 false）开关；查询失败时上层回退到估算。
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

from backend.config import settings
from backend.tools.train import TrainTicketProvider


class RailClient:
    """12306 火车票客户端（直连官方，同步外观）。"""

    def __init__(self) -> None:
        self._provider = TrainTicketProvider()

    def available(self) -> bool:
        """直连 12306 无需 npx/Node，开启 USE_RAIL_MCP 即视为可用。
        实际的网络/风控问题在查询时抛出，由 planner 捕获并回退估算。
        """
        return settings.use_rail_mcp

    def search_with_prices(
        self, from_city: str, to_city: str, date: str,
        preferred_seat: str | None = None, max_trains: int = 10,
    ) -> list[dict]:
        """查询车次列表并为每班车附上真实票价（供前端车次选择展示）。"""
        if not settings.use_rail_mcp:
            raise RuntimeError("未启用 12306 真实票价（USE_RAIL_MCP=false），交通将使用估算值。")
        seat = preferred_seat or settings.rail_mcp_seat_class
        return self._provider.search_with_prices(
            from_city, to_city, date, preferred_seat=seat, max_trains=max_trains
        )

    def recommend(self, from_city: str, to_city: str, date: str,
                  trains: list[dict] | None = None) -> tuple[dict | None, str]:
        """查询车次列表并推荐最合适的一班，返回 (推荐车次, 推荐理由)。

        trains 可传入已查询的车次列表复用（调用方已 search_with_prices 时，
        避免对 12306 重复发起车次+票价请求，降低风控风险与端到端延迟）；
        为 None 时内部自动查询一次。
        """
        seat = settings.rail_mcp_seat_class
        if trains is None:
            trains = self.search_with_prices(from_city, to_city, date, preferred_seat=seat)
        best, reason = self._provider.recommend_train(trains, seat)
        return best, reason


# 模块级单例，供 agents/planner.py 调用。
rail_client = RailClient()