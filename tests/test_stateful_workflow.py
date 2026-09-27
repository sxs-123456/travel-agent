from __future__ import annotations

from time import sleep

from backend.evaluation import summarize
from backend.models.agent import ToolStatus
from backend.models.trip import Attraction, Budget, DayPlan, Location, TripPlan, TripPlanRequest
from backend.workflow.constraints import ConstraintChecker
from backend.workflow.nodes import NodeRunner, WorkflowNode
from backend.workflow.state import TravelState


def request() -> TripPlanRequest:
    return TripPlanRequest(
        city="南京", origin_city="上海", start_date="2026-10-01",
        end_date="2026-10-01", preferences="历史文化，不去夫子庙",
        budget_level="中等", travelers=1,
    )


def attraction(source_id: str, name: str, longitude: float = 118.8) -> Attraction:
    return Attraction(
        source_id=source_id, name=name,
        location=Location(longitude=longitude, latitude=32.05),
        ticket_price=0, recommended_duration=2,
    )


def plan(items: list[Attraction]) -> TripPlan:
    return TripPlan(
        city="南京", start_date="2026-10-01", end_date="2026-10-01",
        days=[DayPlan(day=1, date="2026-10-01", attractions=items)],
        budget=Budget(
            ticket_total=0, hotel_total=0, meal_total=0, transport_total=0,
            rail_total=0, local_transit_total=0, total=0,
        ),
    )


def test_constraint_checker_rejects_ungrounded_duplicates_and_hard_constraint():
    verified = attraction("poi-1", "南京博物院")
    forbidden = attraction("poi-2", "夫子庙")
    invented = attraction("invented", "不存在的景点")
    state = TravelState(
        trace_id="t", request=request(), attractions=[verified, forbidden],
        plan=plan([verified, verified.model_copy(), forbidden, invented]),
    )

    report = ConstraintChecker().check(state)

    assert not report.passed
    assert {item.code for item in report.violations} >= {
        "ungrounded_poi", "duplicate_attraction", "hard_constraint_forbidden_place"
    }
    assert report.grounded_poi_rate == 0.75
    assert report.hallucination_rate == 0.25


def test_constraint_checker_accepts_grounded_consistent_plan():
    verified = attraction("poi-1", "南京博物院")
    state = TravelState(
        trace_id="t", request=request(), attractions=[verified], plan=plan([verified])
    )
    report = ConstraintChecker().check(state)
    assert report.passed
    assert report.grounded_poi_rate == 1
    assert report.constraint_satisfaction_rate == 1


def test_constraint_checker_enforces_explicit_total_budget():
    req = request().model_copy(update={"budget_max": 100})
    verified = attraction("poi-1", "南京博物院")
    expensive = plan([verified])
    expensive.budget.hotel_total = 500
    expensive.budget.total = 500
    state = TravelState(
        trace_id="t", request=req, attractions=[verified], plan=expensive
    )
    report = ConstraintChecker().check(state)
    assert "budget_exceeded" in {item.code for item in report.violations}


class FlakyNode(WorkflowNode):
    name = "flaky"
    provider = "test"

    def __init__(self):
        super().__init__(timeout_seconds=1, max_attempts=2)
        self.calls = 0

    def execute(self, state):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("temporary provider failure")
        return "ok"


class SlowFallbackNode(WorkflowNode):
    name = "slow"

    def __init__(self):
        super().__init__(timeout_seconds=0.01, max_attempts=1)

    def execute(self, state):
        sleep(0.05)

    def fallback(self, state, error):
        return "cached"


def test_node_runner_retries_retryable_failure():
    result = NodeRunner().run(FlakyNode(), TravelState(trace_id="t", request=request()))
    assert result.status == ToolStatus.SUCCESS
    assert result.attempts == 2
    assert result.value == "ok"


def test_node_runner_timeout_uses_explicit_fallback():
    result = NodeRunner().run(SlowFallbackNode(), TravelState(trace_id="t", request=request()))
    assert result.status == ToolStatus.FALLBACK
    assert result.fallback_used
    assert result.error and result.error.code == "tool_timeout"


def test_evaluation_summarizes_agent_specific_metrics():
    record = {
        "success": True, "latency_ms": 120, "quality": {"passed": True},
        "llm_usage": {"usage_available": True, "calls": 1, "input_tokens": 10,
                      "output_tokens": 5, "total_tokens": 15, "estimated_cost_usd": 0.01},
        "workflow": {
            "tool_calls": 10, "tool_successes": 9, "retry_count": 1,
            "fallback_count": 2,
            "constraint_report": {
                "passed": True, "grounded_poi_rate": 1,
                "constraint_satisfaction_rate": 0.9,
                "duplicate_rate": 0.1, "hallucination_rate": 0,
            },
        },
    }
    result = summarize([record])
    assert result["task_success_rate"] == 1
    assert result["tool_call_success_rate"] == 0.9
    assert result["retry_rate"] == 0.1
    assert result["fallback_rate"] == 0.2
    assert result["grounded_poi_rate"] == 1

