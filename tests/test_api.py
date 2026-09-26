"""FastAPI 接口契约测试；外部依赖使用桩替换。"""
import threading
import time

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


def test_trip_job_returns_before_slow_planner_finishes(monkeypatch):
    extracted = TripPlanRequest(
        city="北京", origin_city="上海", start_date="2026-10-01", end_date="2026-10-04"
    )
    release = threading.Event()
    monkeypatch.setattr(api_main, "parse_trip_intent", lambda query, **kwargs: extracted)

    def slow_plan(_self, _request):
        assert release.wait(timeout=2)
        return _sample_plan()

    monkeypatch.setattr(TripPlannerAgent, "plan_trip", slow_plan)
    started = time.perf_counter()
    response = client.post("/api/trip-plan/jobs", json={
        "query": "十月一号到十月四号从上海去北京",
    })
    elapsed = time.perf_counter() - started
    assert response.status_code == 202
    assert elapsed < 0.5
    job_id = response.json()["job_id"]

    running = client.get(f"/api/trip-plan/jobs/{job_id}")
    assert running.status_code == 200
    assert running.json()["status"] in {"pending", "running"}

    release.set()
    for _ in range(20):
        finished = client.get(f"/api/trip-plan/jobs/{job_id}").json()
        if finished["status"] == "complete":
            break
        time.sleep(0.02)
    assert finished["status"] == "complete"
    assert finished["result"]["plan"]["city"] == "杭州"


def test_natural_language_missing_information(monkeypatch):
    def missing(_query):
        raise intent.TripIntentError("请补充返程日期", ["end_date"])

    monkeypatch.setattr(api_main, "parse_trip_intent", missing)
    response = client.post("/api/trip-plan/from-text", json={"query": "我想从上海去北京玩"})
    assert response.status_code == 422
    assert "返程日期" in response.json()["detail"]
    assert response.json()["missing_fields"] == ["end_date"]


def test_date_picker_values_are_forwarded_to_intent_parser(monkeypatch):
    captured = {}

    def parse_with_dates(query, **kwargs):
        captured.update({"query": query, **kwargs})
        return TripPlanRequest(
            city="北京", start_date=kwargs["start_date_override"],
            end_date=kwargs["end_date_override"],
        )

    monkeypatch.setattr(api_main, "parse_trip_intent", parse_with_dates)
    monkeypatch.setattr(TripPlannerAgent, "plan_trip", lambda self, request: _sample_plan())
    response = client.post("/api/trip-plan/from-text", json={
        "query": "我想去北京玩",
        "start_date": "2026-10-01",
        "end_date": "2026-10-04",
    })

    assert response.status_code == 200
    assert captured["start_date_override"] == "2026-10-01"
    assert captured["end_date_override"] == "2026-10-04"


def test_natural_language_planner_failure_is_returned(monkeypatch):
    request = TripPlanRequest(city="北京", start_date="2026-10-01", end_date="2026-10-07")
    monkeypatch.setattr(api_main, "parse_trip_intent", lambda _query: request)

    def unavailable(_self, _request):
        raise RuntimeError("规划服务暂不可用")

    monkeypatch.setattr(TripPlannerAgent, "plan_trip", unavailable)
    response = client.post("/api/trip-plan/from-text", json={"query": "十月一号到十月七号去北京"})
    assert response.status_code == 400
    assert "规划服务暂不可用" in response.json()["detail"]


def test_model_quota_error_has_actionable_safe_message(monkeypatch):
    class QuotaError(Exception):
        status_code = 402

        def __str__(self):
            return "Insufficient Balance (request_id: upstream-private-id)"

    request = TripPlanRequest(city="南京", start_date="2026-10-01", end_date="2026-10-04")
    monkeypatch.setattr(api_main, "parse_trip_intent", lambda _query: request)

    def unavailable(_self, _request):
        raise QuotaError()

    monkeypatch.setattr(TripPlannerAgent, "plan_trip", unavailable)
    response = client.post("/api/trip-plan/from-text", json={"query": "十月一号到四号去南京"})
    assert response.status_code == 503
    assert "额度已用完" in response.json()["detail"]
    assert "upstream-private-id" not in response.json()["detail"]

    def parse_unavailable(_query):
        raise QuotaError()

    monkeypatch.setattr(api_main, "parse_trip_intent", parse_unavailable)
    response = client.post("/api/trip-plan/from-text", json={"query": "十月一号到四号去南京"})
    assert response.status_code == 503
    assert "额度已用完" in response.json()["detail"]
    assert "upstream-private-id" not in response.json()["detail"]


def test_intent_extraction_validates_missing_and_invalid_values(monkeypatch):
    assert intent._has_date_evidence("10.1\u523010.4") is True
    assert intent._extract_travelers("\u4e00\u4e2a\u4eba\u51fa\u53d1") == 1
    assert intent._extract_travelers("\u4e24\u4e2a\u4eba\u51fa\u53d1") == 2
    assert intent._extract_travelers("12\u4f4d\u6e38\u5ba2") == 12
    assert intent._extract_budget_level(
        "\u9884\u7b973000", "2026-09-27", "2026-10-02", 1
    ) == "\u4e2d\u7b49"
    assert intent._extract_budget_level(
        "\u4e24\u4e2a\u4eba\u9884\u7b973\u5343", "2026-10-01", "2026-10-03", 2
    ) == "\u4e2d\u7b49"

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

    chain.result = intent.TripIntent(city="北京", origin_city="上海")
    with pytest.raises(intent.TripIntentError, match="请补充出发日期、返程日期"):
        intent.parse_trip_intent("我想从上海去北京旅行")

    # The model may hallucinate dates even when the user did not provide them.
    # Raw user input remains the source of truth and must trigger a follow-up.
    chain.result = intent.TripIntent(
        city="北京", origin_city="上海",
        start_date="2026-10-01", end_date="2026-10-04",
    )
    with pytest.raises(intent.TripIntentError) as exc_info:
        intent.parse_trip_intent("travel from Shanghai to Beijing")
    assert exc_info.value.missing_fields == [
        "city", "origin_city", "start_date", "end_date",
        "travelers", "budget_level", "preferences",
    ]

    # Exact regression: selected dates plus two cities are still insufficient.
    # Common model defaults must be rejected and returned as follow-up fields.
    chain.result = intent.TripIntent(
        city="北京", origin_city="上海",
        start_date="2026-10-01", end_date="2026-10-04",
        travelers=1, budget_level="中等", preferences="热门景点、美食",
    )
    with pytest.raises(intent.TripIntentError) as exc_info:
        intent.parse_trip_intent(
            "上海到北京游玩",
            start_date_override="2026-10-01",
            end_date_override="2026-10-04",
        )
    assert exc_info.value.missing_fields == ["travelers", "budget_level", "preferences"]

    # Exact regression: a provider may omit travelers even though the user said
    # one person. The deterministic parser must recover it from the raw request.
    chain.result = intent.TripIntent(
        city="\u5357\u4eac", origin_city="\u4e0a\u6d77",
        start_date="2026-09-27", end_date="2026-10-02",
        travelers=None, budget_level="\u4e2d\u7b49", preferences="\u7f8e\u98df",
    )
    request = intent.parse_trip_intent(
        "\u4e00\u4e2a\u4eba\u4ece\u4e0a\u6d77\u53bb\u5357\u4eac\u73a9\uff0c\u9884\u7b973000\uff0c\u559c\u6b22\u7f8e\u98df",
        start_date_override="2026-09-27",
        end_date_override="2026-10-02",
    )
    assert request.travelers == 1

    chain.result = intent.TripIntent(
        city="北京", origin_city="上海",
        start_date="2026-10-07", end_date="2026-10-01",
        travelers=1, budget_level="中等", preferences="美食",
    )
    with pytest.raises(intent.TripIntentError, match="返程日期不能早于出发日期"):
        intent.parse_trip_intent("一个人十月七号到十月一号从上海去北京，喜欢美食，中等预算")


def test_intent_json_fallback_accepts_observed_provider_shape(monkeypatch):
    """DeepSeek JSON mode can use synonyms and a list for food preferences."""
    provider_output = {
        "origin_city": "上海",
        "destination_city": "南京",
        "start_date": "2026-10-01",
        "end_date": "2026-10-04",
        "budget": "豪华",
        "preferences": ["美食"],
        "travelers": 1,
    }
    fallback_prompts = []

    class NoToolCall:
        def invoke(self, _prompt):
            return None

    class JsonMode:
        def invoke(self, prompt):
            fallback_prompts.append(str(prompt))
            return intent.TripIntent.model_validate(provider_output)

    class FakeLlm:
        def with_structured_output(self, _schema, method):
            return NoToolCall() if method == "function_calling" else JsonMode()

    monkeypatch.setattr(intent, "get_llm", lambda **_kwargs: FakeLlm())
    request = intent.parse_trip_intent(
        "计划一份十月一号到十月四号四天三晚的南京游玩攻略，"
        "一个人从上海出发，爱好美食预算充足"
    )

    assert request.city == "南京"
    assert request.origin_city == "上海"
    assert request.start_date == "2026-10-01"
    assert request.end_date == "2026-10-04"
    assert request.preferences == "美食"
    assert request.budget_level == "豪华"
    assert fallback_prompts
    assert "preferences" in fallback_prompts[0]
    assert "weather_info" not in fallback_prompts[0]
