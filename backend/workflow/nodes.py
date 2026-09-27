"""Independent workflow nodes adapting existing agents and deterministic tools."""
from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from time import perf_counter, sleep
from typing import Any, Callable

from pydantic import BaseModel, Field

from backend.agents.attraction import AttractionSearchAgent
from backend.agents.hotel import HotelAgent
from backend.agents.planner import PlannerAgent
from backend.agents.weather import WeatherQueryAgent
from backend.models.agent import ToolResult, ToolStatus
from backend.models.trip import Meal, TripPlan
from backend.observability import current_llm_usage_tracker
from backend.tools.restaurants import recommend_restaurants
from backend.workflow.constraints import ConstraintChecker
from backend.workflow.errors import classify_error
from backend.workflow.state import TravelState


_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="workflow-node")


class RouteDayPatch(BaseModel):
    day: int
    transit_advice: list[str] = Field(default_factory=list)
    transit_cost: int = 0
    transit_cost_is_estimated: bool = True


class RoutePatch(BaseModel):
    days: list[RouteDayPatch] = Field(default_factory=list)


class RestaurantPatch(BaseModel):
    meals: dict[int, Meal] = Field(default_factory=dict)


class RailPatch(BaseModel):
    rail: int = 0
    rail_is_estimated: bool = True
    train_info: list[Any] | None = None
    train_note: str | None = None


class WorkflowNode(ABC):
    name: str
    provider: str | None = None
    timeout_seconds: float
    max_attempts: int

    def __init__(self, *, timeout_seconds: float, max_attempts: int = 1) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    @abstractmethod
    def execute(self, state: TravelState) -> Any:
        raise NotImplementedError

    def fallback(self, state: TravelState, error: BaseException) -> Any:  # noqa: ARG002
        raise error

    def source_ids(self, value: Any) -> list[str]:  # noqa: ARG002
        return []


class NodeRunner:
    """Apply timeout, retry, error classification and fallback uniformly."""

    def run(self, node: WorkflowNode, state: TravelState) -> ToolResult[Any]:
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        last_error: BaseException | None = None
        attempts = 0
        for attempt in range(1, node.max_attempts + 1):
            attempts = attempt
            tracker = current_llm_usage_tracker.get()

            def invoke():
                token = current_llm_usage_tracker.set(tracker)
                try:
                    return node.execute(state.model_copy(deep=True))
                finally:
                    current_llm_usage_tracker.reset(token)

            future = _EXECUTOR.submit(invoke)
            try:
                value = future.result(timeout=node.timeout_seconds)
                return ToolResult(
                    tool=node.name, status=ToolStatus.SUCCESS, value=value,
                    started_at=started_at,
                    latency_ms=round((perf_counter() - started) * 1000, 2),
                    attempts=attempt, source_ids=node.source_ids(value),
                )
            except FutureTimeoutError:
                future.cancel()
                last_error = TimeoutError(
                    f"{node.name} exceeded {node.timeout_seconds:.1f}s"
                )
            except Exception as exc:  # noqa: BLE001 - node seam classifies failures
                last_error = exc
            classified = classify_error(last_error, provider=node.provider)
            if not classified.retryable or attempt >= node.max_attempts:
                break
            sleep(min(0.1 * attempt, 0.3))

        assert last_error is not None
        classified = classify_error(last_error, provider=node.provider)
        try:
            value = node.fallback(state.model_copy(deep=True), last_error)
            return ToolResult(
                tool=node.name, status=ToolStatus.FALLBACK, value=value,
                started_at=started_at,
                error=classified,
                latency_ms=round((perf_counter() - started) * 1000, 2),
                attempts=attempts, fallback_used=True, source_ids=node.source_ids(value),
            )
        except Exception:  # noqa: BLE001 - original classified error is authoritative
            status = ToolStatus.TIMEOUT if classified.kind.value == "timeout" else ToolStatus.FAILED
            return ToolResult(
                tool=node.name, status=status, error=classified,
                started_at=started_at,
                latency_ms=round((perf_counter() - started) * 1000, 2),
                attempts=attempts,
            )


class AttractionNode(WorkflowNode):
    name = "attractions"
    provider = "amap+llm+baike"

    def __init__(self, agent: AttractionSearchAgent, **policy: Any) -> None:
        super().__init__(**policy)
        self.agent = agent

    def execute(self, state: TravelState):
        return self.agent.run(state.request)

    def source_ids(self, value: Any) -> list[str]:
        return [item.source_id for item in value if item.source_id]


class WeatherNode(WorkflowNode):
    name = "weather"
    provider = "amap+open-meteo"

    def __init__(self, agent: WeatherQueryAgent, **policy: Any) -> None:
        super().__init__(**policy)
        self.agent = agent

    def execute(self, state: TravelState):
        return self.agent.run(state.request)

    def fallback(self, state: TravelState, error: BaseException):  # noqa: ARG002
        return []


class HotelNode(WorkflowNode):
    name = "hotels"
    provider = "amap"

    def __init__(self, agent: HotelAgent, **policy: Any) -> None:
        super().__init__(**policy)
        self.agent = agent

    def execute(self, state: TravelState):
        return self.agent.run(state.request)

    def fallback(self, state: TravelState, error: BaseException):  # noqa: ARG002
        return []

    def source_ids(self, value: Any) -> list[str]:
        return [item.source_id for item in value if item.source_id]


class DraftNode(WorkflowNode):
    name = "draft"
    provider = "llm"

    def __init__(self, planner: PlannerAgent, **policy: Any) -> None:
        super().__init__(**policy)
        self.planner = planner

    def execute(self, state: TravelState):
        return self.planner.build_draft(
            state.request, state.attractions, state.weather, state.hotels,
            state.replan_feedback,
        )

    def fallback(self, state: TravelState, error: BaseException):  # noqa: ARG002
        return self.planner.build_deterministic_draft(
            state.request, state.attractions, state.hotels
        )


class PrepareNode(WorkflowNode):
    name = "prepare"

    def __init__(self, planner: PlannerAgent, **policy: Any) -> None:
        super().__init__(**policy)
        self.planner = planner

    def execute(self, state: TravelState):
        assert state.plan is not None
        plan = state.plan.model_copy(deep=True)
        hotel = self.planner.prepare_plan(
            plan, state.request, state.attractions, state.hotels
        )
        return {"plan": plan, "hotel": hotel}


class RouteNode(WorkflowNode):
    name = "routes"
    provider = "amap"

    def __init__(self, planner: PlannerAgent, **policy: Any) -> None:
        super().__init__(**policy)
        self.planner = planner

    def execute(self, state: TravelState) -> RoutePatch:
        assert state.plan is not None
        plan = self.planner.enrich_routes(state.plan.model_copy(deep=True))
        return RoutePatch(days=[RouteDayPatch(
            day=day.day,
            transit_advice=day.transit_advice,
            transit_cost=day.transit_cost,
            transit_cost_is_estimated=day.transit_cost_is_estimated,
        ) for day in plan.days])

    def fallback(self, state: TravelState, error: BaseException) -> RoutePatch:  # noqa: ARG002
        assert state.plan is not None
        return RoutePatch(days=[RouteDayPatch(
            day=day.day,
            transit_advice=["公共交通实时路线暂不可用，请出发前使用导航确认。"],
            transit_cost=0,
            transit_cost_is_estimated=True,
        ) for day in state.plan.days])


class RestaurantNode(WorkflowNode):
    name = "restaurants"
    provider = "amap"

    def execute(self, state: TravelState) -> RestaurantPatch:
        assert state.plan is not None
        return RestaurantPatch(meals=recommend_restaurants(state.plan.days))

    def fallback(self, state: TravelState, error: BaseException) -> RestaurantPatch:  # noqa: ARG002
        return RestaurantPatch()

    def source_ids(self, value: RestaurantPatch) -> list[str]:
        return [meal.source_id for meal in value.meals.values() if meal.source_id]


class RailNode(WorkflowNode):
    name = "rail"
    provider = "12306"

    def __init__(self, planner: PlannerAgent, **policy: Any) -> None:
        super().__init__(**policy)
        self.planner = planner

    def execute(self, state: TravelState) -> RailPatch:
        rail, estimated, info, note = self.planner.enrich_rail(state.request)
        return RailPatch(
            rail=rail, rail_is_estimated=estimated,
            train_info=info, train_note=note,
        )

    def fallback(self, state: TravelState, error: BaseException) -> RailPatch:
        return RailPatch(train_note=f"12306 暂时不可用，火车票未计入预算（{error}）。")


class BudgetNode(WorkflowNode):
    name = "budget"

    def __init__(self, planner: PlannerAgent, **policy: Any) -> None:
        super().__init__(**policy)
        self.planner = planner

    def execute(self, state: TravelState) -> TripPlan:
        assert state.plan is not None and state.rail_result is not None
        return self.planner.finalize_budget(
            state.plan.model_copy(deep=True), state.request,
            state.selected_hotel, state.rail_result,
        )


class ConstraintNode(WorkflowNode):
    name = "constraints"

    def __init__(self, checker: ConstraintChecker, **policy: Any) -> None:
        super().__init__(**policy)
        self.checker = checker

    def execute(self, state: TravelState):
        return self.checker.check(state)


class ImageNode(WorkflowNode):
    name = "images"
    provider = "amap+pexels+openverse"

    def __init__(self, enricher: Callable[[TripPlan], None], **policy: Any) -> None:
        super().__init__(**policy)
        self.enricher = enricher

    def execute(self, state: TravelState) -> TripPlan:
        assert state.plan is not None
        plan = state.plan.model_copy(deep=True)
        self.enricher(plan)
        return plan

    def fallback(self, state: TravelState, error: BaseException) -> TripPlan:  # noqa: ARG002
        assert state.plan is not None
        return state.plan
