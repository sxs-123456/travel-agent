"""FastAPI 接口测试（真实链路，用 monkeypatch 替换编排器返回，验证接口契约）。"""
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
