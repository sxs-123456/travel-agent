"""Offline regression tests for itinerary quality and orchestration boundaries."""
import logging
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.models.trip import (
    Attraction, Budget, DayPlan, Location, TripPlan, TripPlanRequest, WeatherInfo,
)
from backend.planner import TripPlannerAgent
from backend.quality import evaluate_plan


def request():
    return TripPlanRequest(city="杭州", start_date="2026-10-01", end_date="2026-10-02")


def plan():
    return TripPlan(city="杭州", start_date="2026-10-01", end_date="2026-10-02",
                    days=[DayPlan(day=i, date=f"2026-10-0{i}", attractions=[
                        Attraction(name=f"景点{i}", location=Location(longitude=120, latitude=30))
                    ]) for i in (1, 2)], budget=Budget())


@pytest.mark.parametrize("patch", [
    {"start_date": "2026-02-30"}, {"end_date": "2026-13-01"},
    {"start_date": "20261001"}, {"start_date": "2026-1-1"}, {"city": "  "},
])
def test_invalid_request_never_runs_agent(monkeypatch, patch):
    def unexpected(*args):
        pytest.fail("invalid request reached agent")
    monkeypatch.setattr(TripPlannerAgent, "plan_trip", unexpected)
    body = request().model_dump() | patch
    response = TestClient(app).post("/api/trip-plan", json=body)
    assert response.status_code == 422
    assert len(response.headers["X-Request-ID"]) == 32


def test_quality_accepts_consistent_plan_and_reports_weather():
    candidate = plan()
    candidate.weather_info = [WeatherInfo(date="2026-10-02", temperature=20, condition="晴")]
    assert evaluate_plan(request(), candidate) == {
        "passed": True, "issues": [], "weather_coverage": 0.5, "day_coverage": 1.0,
    }


def test_quality_detects_missing_days_and_budget_errors():
    candidate = plan()
    candidate.days.pop()
    candidate.budget.total = 100
    report = evaluate_plan(request(), candidate)
    assert not report["passed"]
    assert {"date_coverage", "day_numbering", "budget_inconsistent"} <= set(report["issues"])
    assert report["day_coverage"] == 0.5


def test_weather_aligned_by_date_and_stages_traced(monkeypatch, caplog):
    agent = TripPlannerAgent()
    candidate = plan()
    monkeypatch.setattr(agent, "_require_real_mode", lambda: None)
    monkeypatch.setattr(agent.attraction_agent, "run", lambda r: [])
    monkeypatch.setattr(agent.weather_agent, "run", lambda r: [
        WeatherInfo(date="2026-10-02", temperature=20, condition="晴")])
    monkeypatch.setattr(agent.hotel_agent, "run", lambda r: [])
    monkeypatch.setattr(agent.planner_agent, "run", lambda *args: candidate)
    monkeypatch.setattr(agent, "_enrich_images", lambda p: None)
    with caplog.at_level(logging.INFO, logger="trip-planner"):
        result = agent.plan_trip(request())
    assert "暂无天气预报" in result.days[0].notes
    assert "暂无天气预报" not in result.days[1].notes
    assert sum("agent_stage" in r.message for r in caplog.records) == 5
    assert "plan_quality" in caplog.text


def test_duplicate_names_all_receive_verified_image(monkeypatch):
    candidate = plan()
    candidate.days[1].attractions[0].name = candidate.days[0].attractions[0].name
    candidate.days[1].attractions[0].image_url = "https://fake.invalid/a.jpg"
    monkeypatch.setattr("backend.planner.search_image", lambda *a, **k: "https://real.example/a.jpg")
    TripPlannerAgent._enrich_images(candidate)
    assert all(d.attractions[0].image_url == "https://real.example/a.jpg" for d in candidate.days)


def test_train_backfill_keeps_travel_date(monkeypatch):
    from backend.agents.planner import PlannerAgent
    dates = []
    def backfill(train, date):
        dates.append(date)
        return train
    monkeypatch.setattr(PlannerAgent, "_ensure_train_prices", backfill)
    best = {"train_no": "G2"}
    result = PlannerAgent._pick_display_trains([{"train_no": "G1"}, best], best,
                                             max_display=1, date="2026-10-02")
    assert result == [best]
    assert dates == ["2026-10-02"]


def test_http_trace_matches_agent_trace_and_context_resets(monkeypatch, caplog):
    from backend.tracing import request_id
    observed = []
    def fake_plan(self, req):
        observed.append(request_id.get())
        return plan()
    monkeypatch.setattr(TripPlannerAgent, "plan_trip", fake_plan)
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="trip-planner"):
        first = client.post("/api/trip-plan", json=request().model_dump())
        second = client.post("/api/trip-plan", json=request().model_dump())
    assert observed == [first.headers["X-Request-ID"], second.headers["X-Request-ID"]]
    assert observed[0] != observed[1]
    assert request_id.get() is None
    assert all(value in caplog.text for value in observed)


def test_failed_stage_records_error_without_planning(monkeypatch, caplog):
    agent = TripPlannerAgent()
    monkeypatch.setattr(agent, "_require_real_mode", lambda: None)
    def fail(r):
        raise ValueError("provider unavailable")
    monkeypatch.setattr(agent.attraction_agent, "run", fail)
    monkeypatch.setattr(agent.weather_agent, "run", lambda r: [])
    monkeypatch.setattr(agent.hotel_agent, "run", lambda r: [])
    monkeypatch.setattr(agent.planner_agent, "run", lambda *a: pytest.fail("must not plan"))
    with caplog.at_level(logging.INFO, logger="trip-planner"), pytest.raises(ValueError):
        agent.plan_trip(request())
    assert "stage=attractions status=error" in caplog.text


def test_recommendation_uses_selected_train_for_price_and_reason(monkeypatch):
    from backend.agents.planner import PlannerAgent
    from backend.config import settings
    import backend.agents.planner as module
    def train(code, price):
        return {"train_no": code, "seats": [
            {"type": "二等座", "remain": "有", "price": price}], "min_price": price}
    candidates = [train("G1", 800), train("G2", 500)]
    class Rail:
        def search_with_prices(self, *args):
            return candidates
        def recommend(self, *args, **kwargs):
            return candidates[1], "推荐 G2"
    monkeypatch.setattr(module, "rail_client", Rail())
    monkeypatch.setattr(settings, "rail_mcp_seat_class", "二等座")
    req = request().model_copy(update={"origin_city": "上海"})
    results = PlannerAgent._build_train_recommendations(req)
    assert len(results) == 2
    assert all(r.recommended.train_no == "G2" and r.price_per_person == 500
               and r.candidates[0].train_no == "G2" and "G2" in r.reason for r in results)


def test_quality_detects_duplicates_empty_days_and_request_mismatch():
    candidate = plan()
    candidate.city = "北京"
    candidate.days[0].attractions *= 2
    candidate.days[1].attractions = []
    report = evaluate_plan(request(), candidate)
    assert {"request_mismatch", "duplicate_attraction", "empty_day"} <= set(report["issues"])


def test_attraction_agent_binds_poi_and_resets_unverified_price(monkeypatch):
    from types import SimpleNamespace
    import backend.agents.attraction as module
    monkeypatch.setattr(module, "text_search", lambda *a: [
        {"source_id": "amap-west-lake", "name": "西湖",
         "location": Location(longitude=121, latitude=31), "ticket_price": 999}])
    monkeypatch.setattr(module, "get_llm", lambda: object())
    monkeypatch.setattr(module, "structured_chain", lambda *a: SimpleNamespace(
        invoke=lambda p: module.AttractionSelection(
            source_ids=["amap-west-lake", "invented", "amap-west-lake"])))
    queried = []
    def ticket(name):
        queried.append(name)
        return None, None
    monkeypatch.setattr(module, "query_baike_card", ticket)
    result = module.AttractionSearchAgent().run(request())
    assert queried == ["西湖"]
    assert len(result) == 1
    assert result[0].source_id == "amap-west-lake"
    assert result[0].location.longitude == 121
    assert result[0].ticket_price == 0


def test_planner_retries_invalid_draft_once(monkeypatch):
    from backend.agents.planner import DayPlanDraft, ItineraryDraft, PlannerAgent
    from backend.config import settings
    import backend.agents.planner as module

    attrs = [
        Attraction(source_id="poi-a", name="A", location=Location(longitude=120, latitude=30),
                   ticket_price=60),
        Attraction(source_id="poi-b", name="B", location=Location(longitude=120.1, latitude=30)),
    ]
    drafts = [
        ItineraryDraft(days=[DayPlanDraft(attraction_ids=["unknown"])]),
        ItineraryDraft(days=[
            DayPlanDraft(attraction_ids=["poi-a"]),
            DayPlanDraft(attraction_ids=["poi-b"]),
        ]),
    ]

    class Chain:
        calls = 0

        def invoke(self, prompt):
            value = drafts[self.calls]
            self.calls += 1
            return value

    chain = Chain()
    monkeypatch.setattr(module, "get_llm", lambda **kwargs: object())
    monkeypatch.setattr(module, "structured_chain", lambda *args: chain)
    monkeypatch.setattr(module, "recommend_restaurants", lambda days: {})
    monkeypatch.setattr(settings, "use_rail_mcp", False)
    monkeypatch.setattr(settings, "baidu_map_ak", "")
    result = PlannerAgent().run(request(), attrs, [], [])
    assert chain.calls == 2
    assert [[a.source_id for a in day.attractions] for day in result.days] == [
        ["poi-a"], ["poi-b"],
    ]
    assert result.days[0].attractions[0].ticket_price == 60
    assert result.days[0].attractions[0] is not attrs[0]


def test_route_optimizer_orders_nearest_first_and_records_distance(monkeypatch):
    import backend.agents.planner as planner_module
    from backend.agents.planner import PlannerAgent
    from backend.models.trip import Hotel

    candidate = TripPlan(
        city="测试", start_date="2026-10-01", end_date="2026-10-01",
        days=[DayPlan(
            day=1,
            date="2026-10-01",
            attractions=[
                Attraction(name="远", location=Location(longitude=0.10, latitude=0)),
                Attraction(name="近", location=Location(longitude=0.01, latitude=0)),
            ],
            hotel=Hotel(name="酒店", location=Location(longitude=0, latitude=0)),
        )],
    )
    PlannerAgent._optimize_routes(candidate)
    monkeypatch.setattr(planner_module.settings, "use_amap_driving_route", False)
    PlannerAgent._enrich_driving_routes(candidate)
    day = candidate.days[0]
    assert [a.name for a in day.attractions] == ["近", "远"]
    assert day.route_distance_km == pytest.approx(22.2, abs=0.2)
    assert "实际路程以地图导航为准" in day.notes


def test_driving_route_metrics_replace_straight_line(monkeypatch):
    import backend.agents.planner as planner_module
    from backend.agents.planner import PlannerAgent
    from backend.models.trip import Hotel

    candidate = TripPlan(
        city="测试", start_date="2026-10-01", end_date="2026-10-01",
        days=[DayPlan(day=1, date="2026-10-01", attractions=[
            Attraction(name="甲", location=Location(longitude=1, latitude=1)),
            Attraction(name="乙", location=Location(longitude=2, latitude=2)),
        ], hotel=Hotel(name="酒店", location=Location(longitude=0, latitude=0)))],
    )
    monkeypatch.setattr(planner_module.settings, "use_amap_driving_route", True)
    monkeypatch.setattr(
        planner_module,
        "driving_route",
        lambda origin, destination: {
            "distance_km": 5.0, "duration_min": 10.0, "source": "amap_driving"
        },
    )
    PlannerAgent._optimize_routes(candidate)
    PlannerAgent._enrich_driving_routes(candidate)
    day = candidate.days[0]
    assert day.route_distance_source == "amap_driving"
    assert day.route_distance_km == 15.0
    assert day.route_duration_min == 30.0
    assert "高德驾车路线" in day.notes


def test_llm_usage_tracker_handles_openai_usage():
    from types import SimpleNamespace
    from backend.observability import LlmUsageTracker

    tracker = LlmUsageTracker()
    tracker.on_llm_end(SimpleNamespace(
        llm_output={"token_usage": {
            "prompt_tokens": 1000, "completion_tokens": 250, "total_tokens": 1250,
        }},
        generations=[],
    ))
    snapshot = tracker.snapshot(
        model="test-model", input_cost_per_1m_usd=1.0, output_cost_per_1m_usd=2.0,
    )
    assert snapshot["calls"] == 1
    assert snapshot["total_tokens"] == 1250
    assert snapshot["estimated_cost_usd"] == 0.0015


def test_empty_day_is_filled_from_unused_verified_candidate():
    from backend.agents.planner import PlannerAgent

    used = Attraction(
        source_id="used", name="龙门石窟",
        location=Location(longitude=112.4, latitude=34.5),
    )
    spare = Attraction(
        source_id="spare", name="洛阳博物馆",
        location=Location(longitude=112.45, latitude=34.62), ticket_price=20,
    )
    plan = TripPlan(
        city="洛阳", start_date="2026-10-01", end_date="2026-10-02",
        days=[
            DayPlan(day=1, date="2026-10-01", attractions=[used]),
            DayPlan(day=2, date="2026-10-02", attractions=[]),
        ],
    )
    PlannerAgent._fill_empty_days(plan, [used, spare])
    assert plan.days[1].attractions[0].source_id == "spare"
    assert plan.days[1].attractions[0] is not spare
    assert "已验证 POI" in plan.days[1].notes


def test_evaluation_summary_reports_reproducible_metrics():
    from backend.evaluation import summarize

    summary = summarize([
        {"success": True, "latency_ms": 100, "quality": {
            "passed": True, "issues": [], "day_coverage": 1, "weather_coverage": 0.5,
        }},
        {"success": True, "latency_ms": 300, "quality": {
            "passed": False, "issues": ["empty_day"],
            "day_coverage": 0.5, "weather_coverage": 0,
        }},
        {"success": False, "latency_ms": 200},
    ])
    assert summary["success_rate"] == pytest.approx(2 / 3, abs=0.0001)
    assert summary["quality_pass_rate"] == 0.5
    assert summary["latency_ms"] == {"p50": 200.0, "p95": 300.0}
    assert summary["issue_counts"] == {"empty_day": 1}


def test_evaluation_case_set_has_varied_valid_scenarios():
    cases_path = Path(__file__).parent.parent / "evals" / "cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    assert len(cases) >= 10
    assert len({case["city"] for case in cases}) >= 10
    assert {case["duration_days"] for case in cases} >= {1, 2, 3, 4}
    assert all(case["travelers"] >= 1 for case in cases)
