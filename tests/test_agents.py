"""四个专属 Agent 的真实路径测试。

Agent 内部通过 `from backend.xxx import y` 绑定了名称，因此 monkeypatch 需打到
各 agent 模块自身的命名空间；LLM 与高德网络均用桩对象替换，覆盖真实代码路径。
"""
import pytest
from pydantic import BaseModel, Field

from backend.models.trip import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Location,
    Meal,
    TripPlan,
    TripPlanRequest,
    WeatherInfo,
)
from backend.agents.attraction import AttractionSearchAgent, AttractionSelection
from backend.agents.hotel import HotelAgent
from backend.agents.weather import WeatherQueryAgent
from backend.agents.planner import DayPlanDraft, ItineraryDraft, PlannerAgent
from backend.agents.base import structured_chain

import backend.agents.attraction as m_attr
import backend.agents.hotel as m_hotel
import backend.agents.weather as m_weather
import backend.agents.planner as m_planner


class _AttractionList(BaseModel):
    """测试 structured_chain 对嵌套列表 schema 的通用兼容性。"""

    items: list[Attraction] = Field(default_factory=list)


# ----- 桩：高德工具 --------------------------------------------------------
def _fake_text_search(keywords, city):
    return [
        {"name": "西湖", "location": Location(longitude=120.1, latitude=30.2),
         "ticket_price": 0, "description": "世界文化遗产"},
        {"name": "灵隐寺", "location": Location(longitude=120.1, latitude=30.2),
         "ticket_price": 75, "description": "千年古刹"},
    ]


def _fake_hotel_search(city, keywords="酒店", limit=10, tier=None):
    """酒店检索桩：与 backend.tools.amap.hotel_search 返回结构一致。"""
    return [
        {"name": "杭州某酒店", "location": Location(longitude=120.1, latitude=30.2),
         "level": "舒适型", "rating": 4.6,
         "price_estimate": 360,
         "price_source": "参考估算（免费接口无真实房价，按档次/评分粗算，以携程/美团实际为准）"},
        {"name": "杭州青年旅舍", "location": Location(longitude=120.1, latitude=30.2),
         "level": "经济型", "rating": 4.2,
         "price_estimate": 180,
         "price_source": "参考估算（免费接口无真实房价，按档次/评分粗算，以携程/美团实际为准）"},
    ]


def _fake_weather(city, days=1):
    return [WeatherInfo(date="2026-10-01", condition="晴", temperature=25)]


# ----- 桩：LLM -------------------------------------------------------------
def _sample_plan() -> TripPlan:
    loc = Location(longitude=120.1, latitude=30.2)
    return TripPlan(
        city="杭州",
        start_date="2026-10-01",
        end_date="2026-10-02",
        days=[DayPlan(
            day=1, date="2026-10-01",
            attractions=[Attraction(name="西湖", location=loc)],
            meals=[Meal(name="楼外楼", location=loc, price=150, cuisine="杭帮菜")],
            hotel=Hotel(name="杭州某酒店", location=loc, price_per_night=300, star_rating=4.0),
            notes="第一天",
        )],
        weather_info=[WeatherInfo(date="2026-10-01", condition="晴", temperature=25)],
        budget=Budget(total=1000),
    )


class FakeStructured:
    def __init__(self, model_cls):
        self.model_cls = model_cls

    def invoke(self, prompt):
        name = self.model_cls.__name__
        if name == "_AttractionList":
            return _AttractionList(items=[
                Attraction(name="西湖", location=Location(longitude=120.1, latitude=30.2),
                           ticket_price=0, description="世界文化遗产"),
                Attraction(name="灵隐寺", location=Location(longitude=120.1, latitude=30.2),
                           ticket_price=75, description="千年古刹"),
            ])
        if name == "AttractionSelection":
            return AttractionSelection(source_ids=["candidate-01", "candidate-02"])
        if name == "TripPlan":
            return _sample_plan()
        if name == "ItineraryDraft":
            return ItineraryDraft(days=[
                DayPlanDraft(attraction_ids=["candidate-01"]),
                DayPlanDraft(attraction_ids=["candidate-02"]),
            ])
        raise AssertionError(f"未预期的模型：{name}")


class FakeLLM:
    def with_structured_output(self, model_cls, **kwargs):
        return FakeStructured(model_cls)


@pytest.fixture
def patched(monkeypatch):
    # 打到各 agent 模块自身的命名空间（应对 from-import 绑定）
    monkeypatch.setattr(m_attr, "text_search", _fake_text_search)
    monkeypatch.setattr(m_attr, "get_llm", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(
        m_attr, "query_baike_card",
        lambda name: (60, "60元旺季/40元淡季"),
    )
    monkeypatch.setattr(m_hotel, "hotel_search", _fake_hotel_search)
    monkeypatch.setattr(m_weather, "weather", _fake_weather)
    monkeypatch.setattr(m_planner, "get_llm", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(m_planner, "recommend_restaurants", lambda days: {})


def _req() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date="2026-10-01",
        end_date="2026-10-02",
        preferences="自然风光",
        budget_level="经济",
        travelers=1,
    )


def test_attraction_agent(patched):
    out = AttractionSearchAgent().run(_req())
    assert isinstance(out, list) and out
    assert out[0].name == "西湖"
    # 真实门票价格（百度百科）已回填
    assert out[0].ticket_price == 60
    assert out[0].ticket_price_note == "60元旺季/40元淡季"
    # 封面图不再由本 Agent 填充，统一由 planner._enrich_images 用 Pexels/Openverse 补
    assert all(a.image_url is None for a in out)


def test_attraction_agent_augments_narrow_llm_selection(monkeypatch):
    raw = [
        {"source_id": f"poi-{index}", "name": name,
         "location": Location(longitude=120 + index / 100, latitude=30),
         "description": "景点"}
        for index, name in enumerate(["西湖", "灵隐寺", "西溪湿地", "良渚古城"], 1)
    ]
    monkeypatch.setattr(m_attr, "text_search", lambda *args: raw)
    monkeypatch.setattr(m_attr, "get_llm", lambda *args, **kwargs: FakeLLM())
    monkeypatch.setattr(
        m_attr,
        "structured_chain",
        lambda *args: type("Chain", (), {
            "invoke": lambda self, prompt: AttractionSelection(source_ids=["poi-1"])
        })(),
    )
    monkeypatch.setattr(m_attr, "query_baike_card", lambda name: (None, None))
    result = AttractionSearchAgent().run(_req())
    assert len(result) == 4
    assert {item.source_id for item in result} == {"poi-1", "poi-2", "poi-3", "poi-4"}


def test_weather_agent(patched):
    out = WeatherQueryAgent().run(_req())
    assert isinstance(out, list) and out
    assert out[0].condition == "晴"
    assert out[0].temperature == 25


def test_hotel_agent(patched):
    out = HotelAgent().run(_req())
    assert isinstance(out, list) and out
    assert out[0].name == "杭州某酒店"
    assert out[0].price_per_night == 360
    # 酒店价格为按档次/评分参考估算（免费接口无真实房价），需如实标注
    assert out[0].price_is_estimated is True
    assert out[0].price_source  # 必须有价格来源标注
    # 封面图不再由本 Agent 填充，统一由 planner._enrich_images 补
    assert all(h.image_url is None for h in out)


def test_planner_agent(patched):
    req = _req()
    attrs = AttractionSearchAgent().run(req)
    weather_list = WeatherQueryAgent().run(req)
    hotels = HotelAgent().run(req)
    plan = PlannerAgent().run(req, attrs, weather_list, hotels)
    assert plan.city == "杭州"
    assert isinstance(plan, TripPlan)
    assert plan.budget is not None


# ----- structured_chain 降级逻辑（推理模型不支持 tool_choice 时回退 json_mode）-----
class _RaiseToolChoice:
    def invoke(self, prompt, *a, **k):
        raise RuntimeError("Thinking mode does not support this tool_choice")


class _JsonModeOK:
    def __init__(self, model_cls):
        self.model_cls = model_cls

    def invoke(self, prompt, *a, **k):
        assert "json" in str(prompt).lower(), "json_mode 降级必须在 prompt 中补入 'json' 字样"
        return FakeStructured(self.model_cls).invoke(prompt)


class _FallbackLLM:
    def with_structured_output(self, model_cls, method="function_calling", **kwargs):
        if method == "function_calling":
            return _RaiseToolChoice()
        return _JsonModeOK(model_cls)


def test_structured_chain_fallback_to_json_mode():
    chain = structured_chain(_FallbackLLM(), _AttractionList)
    out = chain.invoke("忽略此提示")
    assert isinstance(out, _AttractionList)
    assert out.items


def test_structured_chain_retries_on_missing_required_field():
    """function_calling 偶发返回缺必填字段的对象 → 自动用 json_mode 重试一次。"""
    class _MissingField:
        """对象缺 name 必填字段，Pydantic 校验失败。"""

    class _FcMissing:
        def invoke(self, prompt, *a, **k):
            return _MissingField()

    class _JmOK:
        def __init__(self, model_cls):
            self.model_cls = model_cls

        def invoke(self, prompt, *a, **k):
            assert "重要" in str(prompt), "重试必须带必填字段强调"
            return FakeStructured(self.model_cls).invoke(prompt)

    class _RetryingLLM:
        def with_structured_output(self, schema, method="function_calling", **kw):
            if method == "function_calling":
                return _FcMissing()
            return _JmOK(schema)

    chain = structured_chain(_RetryingLLM(), _AttractionList)
    out = chain.invoke("生成景点")
    assert isinstance(out, _AttractionList)
    assert out.items


# ----- 预算由真实数据计算（门票/餐饮按人头，酒店按间夜，交通按人×天）-----
def test_compute_budget_real():
    req = TripPlanRequest(
        city="杭州",
        start_date="2026-10-01",
        end_date="2026-10-02",
        preferences="自然风光",
        budget_level="中等",
        travelers=2,
    )
    loc = Location(longitude=120.1, latitude=30.2)
    days = [DayPlan(
        day=1, date="2026-10-01",
        attractions=[
            Attraction(name="西湖", location=loc, ticket_price=80),
            Attraction(name="灵隐寺", location=loc, ticket_price=75),
        ],
        meals=[Meal(name="楼外楼", location=loc, price=200)],
        hotel=Hotel(name="H", location=loc, price_per_night=900),
    )]
    b = PlannerAgent._compute_budget(req, days, days[0].hotel)
    # 门票 (80+75)*2=310，餐饮 200*2=400，酒店 900*1晚=900（2 天行程 = 1 晚）；
    # 交通：城际 0 + 市内估算 100*1天*2人=200，总计 1810
    assert b.ticket_total == 310
    assert b.meal_total == 400
    assert b.hotel_total == 900
    assert b.transport_total == 200
    assert b.rail_total == 0
    assert b.taxi_total == 200
    assert b.taxi_is_estimated is True
    assert b.total == 1810


def test_compute_budget_hotel_nights_vs_days():
    """3 天行程（23→25）酒店应算 2 晚而非 3 晚，避免多收一晚钱。"""
    req = TripPlanRequest(
        city="北京", start_date="2026-08-23", end_date="2026-08-25",
        budget_level="经济", travelers=1,
    )
    loc = Location(longitude=116.39, latitude=39.91)
    days = [
        DayPlan(day=1, date="2026-08-23", attractions=[],
                meals=[], hotel=Hotel(name="H", location=loc, price_per_night=800)),
        DayPlan(day=2, date="2026-08-24", attractions=[], meals=[],
                hotel=Hotel(name="H", location=loc, price_per_night=800)),
        DayPlan(day=3, date="2026-08-25", attractions=[], meals=[],
                hotel=Hotel(name="H", location=loc, price_per_night=800)),
    ]
    b = PlannerAgent._compute_budget(req, days, days[0].hotel)
    # 23→25 = 3 天 = 2 晚；不是 3 晚
    assert b.hotel_total == 1600  # 800 * 2 晚


def test_compute_budget_hotel_same_day_trip_zero_nights():
    """同日往返（start=end）不应收酒店费。"""
    req = TripPlanRequest(
        city="北京", start_date="2026-08-23", end_date="2026-08-23",
        budget_level="经济", travelers=1,
    )
    loc = Location(longitude=116.39, latitude=39.91)
    days = [DayPlan(day=1, date="2026-08-23", attractions=[],
                    hotel=Hotel(name="H", location=loc, price_per_night=800))]
    b = PlannerAgent._compute_budget(req, days, days[0].hotel)
    assert b.hotel_total == 0


def test_strip_return_day_hotel():
    """3 天行程（23→25 = 2 晚）：返程日 Day3 的 hotel 应被置空，只保留前 2 晚。"""
    req = TripPlanRequest(
        city="北京", start_date="2026-08-23", end_date="2026-08-25",
        budget_level="经济",
    )
    loc = Location(longitude=116.39, latitude=39.91)
    plan = TripPlan(
        city="北京", start_date="2026-08-23", end_date="2026-08-25",
        days=[
            DayPlan(day=1, date="2026-08-23", attractions=[],
                    hotel=Hotel(name="H", location=loc, price_per_night=230)),
            DayPlan(day=2, date="2026-08-24", attractions=[],
                    hotel=Hotel(name="H", location=loc, price_per_night=230)),
            DayPlan(day=3, date="2026-08-25", attractions=[],
                    hotel=Hotel(name="H", location=loc, price_per_night=230)),
        ],
    )
    PlannerAgent._strip_return_day_hotel(plan, req)
    assert plan.days[0].hotel is not None  # Day1 过夜，保留
    assert plan.days[1].hotel is not None  # Day2 过夜，保留
    assert plan.days[2].hotel is None      # Day3 返程日，移除


def test_apply_single_hotel():
    """多晚住同一家：LLM 给不同天选不同酒店时，统一替换为首选酒店。"""
    loc = Location(longitude=116.39, latitude=39.91)
    hotels = [
        Hotel(name="首选酒店A", location=loc, price_per_night=300, level="豪华型"),
        Hotel(name="备选酒店B", location=loc, price_per_night=200, level="经济型"),
    ]
    plan = TripPlan(
        city="北京", start_date="2026-08-23", end_date="2026-08-25",
        days=[
            DayPlan(day=1, date="2026-08-23", attractions=[],
                    hotel=Hotel(name="首选酒店A", location=loc, price_per_night=300)),
            DayPlan(day=2, date="2026-08-24", attractions=[],
                    hotel=Hotel(name="备选酒店B", location=loc, price_per_night=200)),
            DayPlan(day=3, date="2026-08-25", attractions=[], hotel=None),  # 返程日
        ],
    )
    chosen = PlannerAgent._apply_single_hotel(plan, hotels)
    assert chosen is hotels[0]  # 首选
    assert plan.days[0].hotel.name == "首选酒店A"
    assert plan.days[1].hotel.name == "首选酒店A"  # 被统一成同一家
    assert plan.days[2].hotel is None               # 返程日保持无酒店


def test_compute_budget_with_12306_transport():
    """接入 12306 真实票价时，城际用真实值；市内仍按天估算（不再漏算）。"""
    req = TripPlanRequest(
        city="杭州", start_date="2026-10-01", end_date="2026-10-02",
        travelers=2, budget_level="中等",
    )
    loc = Location(longitude=120.1, latitude=30.2)
    days = [DayPlan(
        day=1, date="2026-10-01",
        attractions=[Attraction(name="西湖", location=loc, ticket_price=80)],
        meals=[Meal(name="楼外楼", location=loc, price=200)],
        hotel=Hotel(name="H", location=loc, price_per_night=900),
    )]
    # 12306 单人往返 1200，2 人 => 城际 2400；市内估算 100*1*2=200
    b = PlannerAgent._compute_budget(
        req, days, days[0].hotel, rail=2400, rail_is_estimated=False
    )
    assert b.rail_total == 2400
    assert b.rail_is_estimated is False
    assert b.taxi_total == 200
    assert b.transport_total == 2600
    assert b.transport_is_estimated is True  # 城际真实但市内估算 → 整体含估算
    assert b.total == (80 * 2) + (200 * 2) + 900 + 2600


def test_compute_budget_with_taxi():
    """接入百度打车真实估算时，市内交通用真实值。"""
    req = TripPlanRequest(
        city="杭州", start_date="2026-10-01", end_date="2026-10-02",
        travelers=2, budget_level="中等",
    )
    loc = Location(longitude=120.1, latitude=30.2)
    days = [DayPlan(
        day=1, date="2026-10-01",
        attractions=[Attraction(name="西湖", location=loc, ticket_price=80)],
        meals=[Meal(name="楼外楼", location=loc, price=200)],
        hotel=Hotel(name="H", location=loc, price_per_night=900),
    )]
    b = PlannerAgent._compute_budget(
        req, days, days[0].hotel, rail=2400, rail_is_estimated=False,
        taxi=120, taxi_is_estimated=False,
    )
    assert b.rail_total == 2400
    assert b.taxi_total == 120
    assert b.taxi_is_estimated is False
    assert b.transport_total == 2520
    assert b.transport_is_estimated is False  # 城际+市内均为真实
    assert b.total == (80 * 2) + (200 * 2) + 900 + 2520


# ----- 多天行程防重复：跨天同名/同景区景点必须被去重 -----
def test_dedupe_attractions_across_days():
    """同一景区（含子景点）排进多天时，只保留首次出现。"""
    loc = Location(longitude=116.39, latitude=39.91)
    plan = TripPlan(
        city="北京", start_date="2026-08-24", end_date="2026-08-26",
        days=[
            DayPlan(day=1, date="2026-08-24", attractions=[
                Attraction(name="故宫博物院", location=loc),
            ]),
            DayPlan(day=2, date="2026-08-25", attractions=[
                Attraction(name="故宫博物院", location=loc),        # 完全同名 → 去重
                Attraction(name="故宫博物院-太和门", location=loc),  # 同景区子景点 → 去重
                Attraction(name="颐和园", location=loc),            # 不同景区 → 保留
            ]),
            DayPlan(day=3, date="2026-08-26", attractions=[
                Attraction(name="天坛公园", location=loc),          # 不同景区 → 保留
            ]),
        ],
    )
    PlannerAgent._dedupe_attractions_across_days(plan)
    names = [a.name for d in plan.days for a in d.attractions]
    assert names == ["故宫博物院", "颐和园", "天坛公园"]


def test_same_scenic_area_rules():
    """同景区判定：同名/长名包含为同景区；短名包含与无关名不算。"""
    from backend.agents.planner import _same_scenic_area

    assert _same_scenic_area("故宫博物院", "故宫博物院")            # 同名
    assert _same_scenic_area("故宫博物院", "故宫博物院-太和门")      # 子景点（包含）
    assert not _same_scenic_area("颐和园", "天坛公园")              # 无关
    assert not _same_scenic_area("天坛", "天坛公园")                # 短名 < 4 字不判同景区


# ----- 封面图统一化：所有 image_url 一律由 search_image 覆盖 -----
def test_enrich_images_overwrites_llm_fake_url(monkeypatch):
    """所有景点/酒店的 image_url 统一由 search_image（Pexels/Openverse）覆盖，杜绝假图。"""
    from backend.planner import TripPlannerAgent

    monkeypatch.setattr(
        "backend.planner.search_image",
        lambda kw, exclude=None: f"https://real.example/{kw}.jpg",
    )
    loc = Location(longitude=116.39, latitude=39.91)
    plan = TripPlan(
        city="北京", start_date="2026-10-01", end_date="2026-10-02",
        days=[DayPlan(
            day=1, date="2026-10-01",
            attractions=[
                Attraction(
                    name="故宫", location=loc,
                    image_url="https://images.unsplash.com/photo-llm-hallucinated-404",
                ),
                Attraction(name="颐和园", location=loc),
            ],
            meals=[],
            hotel=Hotel(
                name="某酒店", location=loc, price_per_night=300,
                image_url="https://images.unsplash.com/photo-llm-hallucinated-404",
            ),
        )],
    )
    TripPlannerAgent._enrich_images(plan)
    day = plan.days[0]
    assert day.attractions[0].image_url == "https://real.example/故宫.jpg"  # 假 URL 被覆盖
    assert day.attractions[1].image_url == "https://real.example/颐和园.jpg"  # 无图 → 补图
    assert day.hotel.image_url == "https://real.example/某酒店.jpg"  # 假 URL 被覆盖


def test_enrich_images_passes_exclude_for_diversity(monkeypatch):
    """不同景点应尽量用不同图：并发检索后主线程去重，保证各景点图不重复。"""
    from backend.planner import TripPlannerAgent

    def fake_search(kw, exclude=None):
        return f"https://real.example/{kw}.jpg"

    monkeypatch.setattr("backend.planner.search_image", fake_search)
    loc = Location(longitude=116.39, latitude=39.91)
    plan = TripPlan(
        city="北京", start_date="2026-10-01", end_date="2026-10-02",
        days=[DayPlan(
            day=1, date="2026-10-01",
            attractions=[
                Attraction(name="故宫", location=loc),
                Attraction(name="颐和园", location=loc),
                Attraction(name="天坛", location=loc),
            ],
            meals=[],
        )],
    )
    TripPlannerAgent._enrich_images(plan)
    urls = [a.image_url for a in plan.days[0].attractions]
    assert len(urls) == 3
    assert len(set(urls)) == 3  # 三个景点拿到三张不同图（去重生效）


def test_enrich_images_dedupe_collision_retries_with_exclude(monkeypatch):
    """并发检索撞图（图库只有一张相关图）时：主线程带已用图补查，查不到则诚实无图。"""
    from backend.planner import TripPlannerAgent

    exclude_seen = []

    def fake_search(kw, exclude=None):
        exclude_seen.append(set(exclude or set()))
        if kw == "故宫":
            return "https://real.example/only-one.jpg"
        if kw == "颐和园":
            # 撞图补查时 exclude 已含该图 → 图库无其他候选，返回 None
            return None if "https://real.example/only-one.jpg" in exclude_seen[-1] \
                else "https://real.example/only-one.jpg"
        return f"https://real.example/{kw}.jpg"

    monkeypatch.setattr("backend.planner.search_image", fake_search)
    loc = Location(longitude=116.39, latitude=39.91)
    plan = TripPlan(
        city="北京", start_date="2026-10-01", end_date="2026-10-02",
        days=[DayPlan(
            day=1, date="2026-10-01",
            attractions=[
                Attraction(name="故宫", location=loc),
                Attraction(name="颐和园", location=loc),
                Attraction(name="天坛", location=loc),
            ],
            meals=[],
        )],
    )
    TripPlannerAgent._enrich_images(plan)
    a1, a2, a3 = plan.days[0].attractions
    assert a1.image_url == "https://real.example/only-one.jpg"  # 故宫先到先得
    assert a2.image_url is None  # 撞图且无第二候选 → 诚实降级为无图
    assert a3.image_url == "https://real.example/天坛.jpg"
    # 补查调用携带了已用图的 exclude（撞图去重生效）
    assert any("https://real.example/only-one.jpg" in s for s in exclude_seen)


# ----- 候选车次限 10 条 + 推荐车次置顶（线上 bug：列表过长）-----
def _mk_train(code: str, with_price: bool = True) -> dict:
    """构造一个最小可用的 train dict（模拟 provider.search_with_prices 输出）。"""
    seats = [{"type": "二等座", "remain": "有", "price": 500 if with_price else None}]
    return {
        "train_no": code, "train_code": code, "train_type": "高铁",
        "from_station": "A", "to_station": "B",
        "depart_time": "09:00", "arrive_time": "13:30", "duration": "04:30",
        "from_station_no": "01", "to_station_no": "02", "seat_types": "O",
        "seats": seats,
        "min_price": 500 if with_price else None,
    }


def test_pick_display_trains_best_in_first_10(monkeypatch):
    """推荐车次已在前 10 条内：置顶且不重复补票价。"""
    from backend.agents.planner import PlannerAgent

    # 防御：best 在前 10 时不应调 _ensure_train_prices
    called = {"n": 0}
    original = PlannerAgent._ensure_train_prices

    def spy(train, date):
        called["n"] += 1
        return original(train, date)

    monkeypatch.setattr(PlannerAgent, "_ensure_train_prices", spy)

    trains = [_mk_train(f"G{i:02d}") for i in range(15)]
    best = trains[3]  # 在前 10
    out = PlannerAgent._pick_display_trains(trains, best, max_display=10)
    assert len(out) == 10
    assert out[0]["train_no"] == "G03"
    assert called["n"] == 0  # 没补票价


def test_pick_display_trains_best_outside_top10_promoted(monkeypatch):
    """推荐车次不在前 10 条内：单独补一次票价并插到第 1 位，总数仍为 10。"""
    from backend.agents.planner import PlannerAgent

    # mock _ensure_train_prices：给 best 补一个明确的价格，便于断言
    def fake_ensure(train, date):
        for s in train["seats"]:
            if s["price"] is None:
                s["price"] = 999
        train["min_price"] = 999
        return train
    monkeypatch.setattr(PlannerAgent, "_ensure_train_prices", fake_ensure)

    trains = [_mk_train(f"G{i:02d}") for i in range(15)]
    best = trains[12]  # 不在前 10
    out = PlannerAgent._pick_display_trains(trains, best, max_display=10)
    assert len(out) == 10
    assert out[0]["train_no"] == "G12"  # 推荐车次置顶
    # 后 9 条是 trains[:9]
    assert [t["train_no"] for t in out[1:]] == [f"G{i:02d}" for i in range(9)]


def test_ensure_train_prices_backfills(monkeypatch):
    """单班车次补票价：seats[].price 被填充，min_price 被计算。"""
    from backend.agents.planner import PlannerAgent
    import backend.agents.planner as m_planner

    class FakeProvider:
        def get_prices(self, train_code, frm, to, seat_types, date):
            return {"二等座": 500.0, "一等座": 800.0}

    class FakeRailClient:
        _provider = FakeProvider()
    monkeypatch.setattr(m_planner, "rail_client", FakeRailClient)

    train = _mk_train("G99", with_price=False)  # 价格为 None
    out = PlannerAgent._ensure_train_prices(train, "2026-10-01")
    assert out["seats"][0]["price"] == 500
    assert out["min_price"] == 500
