"""Pydantic 数据模型：自底向上构建旅行计划的数据结构。

层级关系：
  Location → Attraction / Meal / Hotel
  Attraction / Meal / Hotel + WeatherInfo → DayPlan
  DayPlan[] + WeatherInfo[] + Budget → TripPlan
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 基础原子模型
# ---------------------------------------------------------------------------
class Location(BaseModel):
    """地理坐标。"""

    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")
    address: Optional[str] = Field(None, description="详细地址")

    @field_validator("longitude")
    @classmethod
    def check_longitude(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("经度必须在 [-180, 180] 之间")
        return v

    @field_validator("latitude")
    @classmethod
    def check_latitude(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("纬度必须在 [-90, 90] 之间")
        return v

    @field_validator("address", mode="before")
    @classmethod
    def coerce_address(cls, v):
        """LLM 偶发把 address 生成成 list / dict / 其他类型；统一转成字符串或 None。

        避免 'Input should be a valid string' 校验错误导致整个行程规划 502。
        """
        if v is None or v == "":
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, (list, tuple)):
            parts = [str(x) for x in v if x not in (None, "")]
            return " ".join(parts) or None
        if isinstance(v, dict):
            parts = [f"{k}:{val}" for k, val in v.items() if val not in (None, "")]
            return " ".join(parts) or None
        return str(v)


class WeatherInfo(BaseModel):
    """某一天的天气信息。"""

    date: str = Field(..., description="日期，格式 YYYY-MM-DD")
    temperature: int = Field(..., description="温度（摄氏度）")
    condition: str = Field(..., description="天气状况，如 晴/多云/小雨")

    @field_validator("temperature", mode="before")
    @classmethod
    def parse_temperature(cls, v):
        """兼容 "23℃" / "23°C" / 23 / 23.5（LLM 偶发小数）等多种输入。"""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            v = v.replace("°C", "").replace("℃", "").strip()
            if v == "":
                return 0
            try:
                return int(float(v))
            except ValueError:
                return 0
        if isinstance(v, float):
            return int(v)
        return v


# ---------------------------------------------------------------------------
# 行程条目模型
# ---------------------------------------------------------------------------
class Attraction(BaseModel):
    """景点。"""

    source_id: Optional[str] = Field(None, description="数据源中的稳定 POI ID")
    name: str = Field(..., description="景点名称")
    location: Location = Field(..., description="坐标")
    ticket_price: int = Field(0, ge=0, description="门票价格（元），0 表示免费或未知")
    ticket_price_note: Optional[str] = Field(
        None, description="门票说明（如『60元旺季/40元淡季』）；None 表示未查到"
    )
    description: str = Field("", description="简介")
    recommended_duration: int = Field(2, ge=1, description="建议游玩时长（小时）")
    image_url: Optional[str] = Field(None, description="封面图（Unsplash）")


class Meal(BaseModel):
    """餐饮推荐。"""

    source_id: Optional[str] = Field(None, description="餐厅数据源中的稳定 POI ID")
    name: str = Field(..., description="餐厅/美食名称")
    location: Optional[Location] = Field(
        None, description="坐标；模型建议且未经地图核实时为空"
    )
    price: int = Field(0, ge=0, description="人均消费（元）")
    cuisine: str = Field("", description="菜系，如 川菜/本地小吃")
    price_source: Optional[str] = Field(None, description="人均消费的数据来源")
    price_is_estimated: bool = Field(True, description="价格是否为模型建议或估算")


class Hotel(BaseModel):
    """酒店。"""

    name: str = Field(..., description="酒店名称")
    location: Location = Field(..., description="坐标")
    price_per_night: int = Field(0, ge=0, description="每晚价格（元）")
    star_rating: float = Field(3.0, ge=0, le=5, description="星级")
    image_url: Optional[str] = Field(None, description="封面图")
    level: Optional[str] = Field(None, description="酒店档次（经济型/舒适型/高档型/豪华型）")
    price_source: Optional[str] = Field(None, description="价格来源说明")
    price_is_estimated: bool = Field(
        True, description="价格是否为估算（免费接口无真实房价，按档次/评分参考估算）"
    )


# ---------------------------------------------------------------------------
# 聚合模型
# ---------------------------------------------------------------------------
class DayPlan(BaseModel):
    """单日行程计划。"""

    day: int = Field(..., ge=1, description="第几天")
    date: str = Field(..., description="日期 YYYY-MM-DD")
    attractions: List[Attraction] = Field(default_factory=list, description="当日景点")
    meals: List[Meal] = Field(default_factory=list, description="当日餐饮")
    hotel: Optional[Hotel] = Field(None, description="入住酒店")
    route_distance_km: Optional[float] = Field(
        None, ge=0, description="按实际游览顺序计算的路线距离（公里）"
    )
    route_duration_min: Optional[float] = Field(
        None, ge=0, description="高德驾车路线预计时长（分钟）"
    )
    route_distance_source: str = Field(
        "straight_line", description="距离来源：amap_driving 或 straight_line"
    )
    notes: str = Field("", description="当日备注/路线提示")


class Budget(BaseModel):
    """全程预算明细。"""

    ticket_total: int = Field(0, ge=0, description="门票合计")
    hotel_total: int = Field(0, ge=0, description="酒店合计")
    meal_total: int = Field(0, ge=0, description="餐饮合计")
    transport_total: int = Field(0, ge=0, description="交通合计（= 城际 + 市内）")
    # 城际交通（火车票往返）；未启用 12306 时为 0。
    rail_total: int = Field(0, ge=0, description="城际交通（火车票）")
    # 市内交通（打车/短驳）；未启用百度打车时为按天估算值。
    taxi_total: int = Field(0, ge=0, description="市内交通（打车/短驳）")
    rail_is_estimated: bool = Field(
        True, description="城际交通是否为估算（true=估算；false=来自 12306 真实票价）"
    )
    taxi_is_estimated: bool = Field(
        True, description="市内交通是否为估算（true=按天估算；false=来自百度真实距离/时长）"
    )
    transport_is_estimated: bool = Field(
        True, description="交通整体是否含估算（向后兼容：任一分项估算即为 true）"
    )
    total: int = Field(0, ge=0, description="总计")
    travelers: int = Field(
        1, ge=1, description="出行人数（门票/餐饮按人头计，前端编辑行程后可据此本地重算）"
    )
    rooms: int = Field(
        1, ge=1, description="酒店房间数（标准每间 2 人，4 人出游开 2 间；酒店合计已按间数计）"
    )

    @property
    def breakdown(self) -> dict:
        return {
            "门票": self.ticket_total,
            "酒店": self.hotel_total,
            "餐饮": self.meal_total,
            "交通": self.transport_total,
            "总计": self.total,
        }


# ---------------------------------------------------------------------------
# 火车票（12306 真实车次选择）模型
# ---------------------------------------------------------------------------
class TrainSeat(BaseModel):
    """某车次的一个席别（余票与真实票价）。"""

    type: str = Field(..., description="席别名，如 二等座/一等座/商务座")
    remain: str = Field("", description="余票：有/无/数字")
    price: Optional[int] = Field(None, description="真实票价（元）；接口未返回时为 None")


class TrainOption(BaseModel):
    """候选车次（12306 真实数据）。"""

    train_no: str = Field(..., description="车次号，如 G1")
    train_type: str = Field("", description="车型：高铁/动车/城际/快速…")
    from_station: str = Field("", description="出发站")
    to_station: str = Field("", description="到达站")
    depart_time: str = Field("", description="出发时间 HH:MM")
    arrive_time: str = Field("", description="到达时间 HH:MM")
    duration: str = Field("", description="历时，如 04:28")
    seats: List[TrainSeat] = Field(default_factory=list, description="席别余票与票价")
    min_price: Optional[int] = Field(None, description="可订席别最低真实票价（元）")
    currency: str = Field("CNY", description="币种")
    source_note: str = Field("12306 官方实时车次/票价", description="数据来源")


class TrainRecommendation(BaseModel):
    """车次选择推荐：推荐班次 + 理由 + 候选列表（供前端展示「哪班车合适」）。"""

    direction: str = Field(..., description="方向，如 去程：上海→北京")
    date: str = Field(..., description="乘车日期")
    recommended: Optional[TrainOption] = Field(None, description="推荐车次")
    reason: str = Field("", description="推荐理由（基于出发时间/票价/耗时/余票）")
    candidates: List[TrainOption] = Field(
        default_factory=list, description="候选车次列表（含余票与票价）"
    )
    price_per_person: Optional[int] = Field(
        None, description="推荐车次单人票价（按偏好席别，未命中取最低价）"
    )


class GenerationMetrics(BaseModel):
    """一次行程生成所消耗的大模型资源。"""

    model: str
    calls: int = Field(0, ge=0)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    estimated_cost_usd: Optional[float] = Field(None, ge=0)
    usage_available: bool = False


class TripPlan(BaseModel):
    """完整旅行计划（顶层模型）。"""

    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="出发日期 YYYY-MM-DD")
    end_date: str = Field(..., description="返程日期 YYYY-MM-DD")
    days: List[DayPlan] = Field(default_factory=list, description="逐日行程")
    weather_info: List[WeatherInfo] = Field(default_factory=list, description="天气信息")
    budget: Optional[Budget] = Field(None, description="预算明细")
    train_info: Optional[List[TrainRecommendation]] = Field(
        None, description="车次选择推荐列表（去程/返程各一条；未启用 12306 时为 None）"
    )
    train_note: Optional[str] = Field(
        None,
        description="车票功能状态说明：未填写出发城市 / 未启用 / 查询失败等原因；None 表示正常返回了车次",
    )
    generation_metrics: Optional[GenerationMetrics] = Field(
        None, description="LLM 调用次数、token 与按配置单价估算的费用"
    )

    def summary(self) -> str:
        lines = [
            f"📍 {self.city}  {self.start_date} ~ {self.end_date}（共 {len(self.days)} 天）",
        ]
        if self.budget:
            lines.append(f"💰 预算总计 ¥{self.budget.total}")
        for d in self.days:
            spots = "、".join(a.name for a in d.attractions) or "（自由活动）"
            lines.append(f"  Day{d.day} {d.date}: {spots}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class TripPlanRequest(BaseModel):
    """用户发起行程规划的请求。"""

    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="出发日期 YYYY-MM-DD")
    end_date: str = Field(..., description="返程日期 YYYY-MM-DD")
    preferences: str = Field("自然风光、历史文化", description="景点偏好")
    budget_level: str = Field("中等", description="预算等级：经济/中等/豪华（决定酒店档次）")
    travelers: int = Field(1, ge=1, description="出行人数")
    origin_city: str = Field("", description="出发城市（用于 12306 真实票价，留空则用估算）")

    @field_validator("city")
    @classmethod
    def check_city(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("目的地城市不能为空")
        return v.strip()

    @field_validator("start_date", "end_date")
    @classmethod
    def check_calendar_date(cls, v: str) -> str:
        from datetime import date

        try:
            parsed = date.fromisoformat(v)
        except ValueError:
            raise ValueError("日期必须是有效的 YYYY-MM-DD 日期") from None
        if parsed.isoformat() != v:
            raise ValueError("日期必须使用 YYYY-MM-DD 格式")
        return v

    @field_validator("end_date")
    @classmethod
    def check_date_order(cls, v: str, info):
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("返程日期不能早于出发日期")
        return v

    def total_days(self) -> int:
        from datetime import date

        s = date.fromisoformat(self.start_date)
        e = date.fromisoformat(self.end_date)
        return max(1, (e - s).days + 1)
