"""FastAPI 接口契约测试；外部依赖使用桩替换。"""
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.models.trip import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Location,
    Meal,
    TripPlan,
    WeatherInfo,
)
from backend.planner import TripPlannerAgent
from backend import intent
from backend.api import main as api_main
from backend.models.trip import TripPlanRequest

client = TestClient(app)


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


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_trip_plan(monkeypatch):
    # 替换编排器返回，验证 API 层（请求校验 / 响应模型 / 状态码）契约。
    monkeypatch.setattr(TripPlannerAgent, "plan_trip", lambda self, request: _sample_plan())

    body = {
        "city": "杭州",
        "start_date": "2026-10-01",
        "end_date": "2026-10-02",
        "preferences": "自然风光",
        "budget_level": "经济",
        "travelers": 1,
    }
    r = client.post("/api/trip-plan", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["city"] == "杭州"
    assert len(d["days"]) == 1
    assert d["budget"]["total"] == 1000
    assert d["days"][0]["attractions"]  # 至少含一个景点


def test_trip_plan_validation_error():
    # 返程早于出发，应当被请求模型校验拦截（422）。
    body = {
        "city": "杭州",
        "start_date": "2026-10-03",
        "end_date": "2026-10-01",
        "preferences": "自然风光",
        "budget_level": "经济",
        "travelers": 1,
    }
    r = client.post("/api/trip-plan", json=body)
    assert r.status_code == 422


def test_natural_language_trip_plan(monkeypatch):
    extracted = TripPlanRequest(
        city="北京", origin_city="上海", start_date="2026-10-01",
        end_date="2026-10-07", preferences="故宫、胡同、美食", travelers=2,
    )
    monkeypatch.setattr(api_main, "parse_trip_intent", lambda query: extracted)
    monkeypatch.setattr(TripPlannerAgent, "plan_trip", lambda self, request: _sample_plan())

    response = client.post("/api/trip-plan/from-text", json={
        "query": "十月一号到十月七号从上海去北京，两个人想逛故宫和胡同",
    })
    assert response.status_code == 200
    assert response.json()["request"]["origin_city"] == "上海"
    assert response.json()["request"]["city"] == "北京"
    assert response.json()["plan"]["days"]


def test_natural_language_missing_information(monkeypatch):
    def missing(_query):
        raise intent.TripIntentError("请补充返程日期")

    monkeypatch.setattr(api_main, "parse_trip_intent", missing)
    response = client.post("/api/trip-plan/from-text", json={"query": "我想从上海去北京玩"})
    assert response.status_code == 422
    assert "返程日期" in response.json()["detail"]


def test_natural_language_planner_failure_is_returned(monkeypatch):
    request = TripPlanRequest(city="北京", start_date="2026-10-01", end_date="2026-10-07")
    monkeypatch.setattr(api_main, "parse_trip_intent", lambda _query: request)

    def unavailable(_self, _request):
        raise RuntimeError("规划服务暂不可用")

    monkeypatch.setattr(TripPlannerAgent, "plan_trip", unavailable)
    response = client.post("/api/trip-plan/from-text", json={"query": "十月一号到十月七号去北京"})
    assert response.status_code == 400
    assert "规划服务暂不可用" in response.json()["detail"]


def test_intent_extraction_validates_missing_and_invalid_values(monkeypatch):
    class FakeChain:
        result = None

        def invoke(self, _prompt):
            return self.result

    chain = FakeChain()
    monkeypatch.setattr(intent, "get_llm", lambda **kwargs: object())
    monkeypatch.setattr(intent, "structured_chain", lambda _llm, _schema: chain)

    chain.result = intent.TripIntent(city="北京", start_date="2026-10-01")
    with pytest.raises(intent.TripIntentError, match="返程日期"):
        intent.parse_trip_intent("十月一号从上海去北京")

    chain.result = intent.TripIntent(city="北京", start_date="2026-10-07", end_date="2026-10-01")
    with pytest.raises(intent.TripIntentError, match="返程日期不能早于出发日期"):
        intent.parse_trip_intent("十月七号到十月一号去北京")
