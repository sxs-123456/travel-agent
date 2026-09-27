"""Explicit state machine for discovery, planning, enrichment and bounded replan."""
from __future__ import annotations

import concurrent.futures as futures
import logging
from time import perf_counter

from backend.models.agent import ToolResult, ToolStatus, TraceSpan, WorkflowMetrics
from backend.models.trip import TripPlanRequest
from backend.observability import current_llm_usage_tracker
from backend.workflow.nodes import (
    AttractionNode,
    BudgetNode,
    ConstraintNode,
    DraftNode,
    HotelNode,
    ImageNode,
    NodeRunner,
    PrepareNode,
    RailNode,
    RestaurantNode,
    RouteNode,
    WeatherNode,
)
from backend.workflow.state import TravelState, WorkflowRoute

logger = logging.getLogger("trip-planner")


class TravelWorkflow:
    """Deep workflow module: callers provide a request and receive a validated plan."""

    def __init__(
        self, *, attraction_node: AttractionNode, weather_node: WeatherNode,
        hotel_node: HotelNode, draft_node: DraftNode, prepare_node: PrepareNode,
        route_node: RouteNode, restaurant_node: RestaurantNode, rail_node: RailNode,
        budget_node: BudgetNode, constraint_node: ConstraintNode,
        image_node: ImageNode, runner: NodeRunner | None = None,
    ) -> None:
        self.discovery_nodes = [attraction_node, weather_node, hotel_node]
        self.draft_node = draft_node
        self.prepare_node = prepare_node
        self.enrichment_nodes = [route_node, restaurant_node, rail_node]
        self.budget_node = budget_node
        self.constraint_node = constraint_node
        self.image_node = image_node
        self.runner = runner or NodeRunner()

    def run(
        self, request: TripPlanRequest, *, trace_id: str, max_loops: int = 2
    ) -> TravelState:
        started = perf_counter()
        state = TravelState(
            trace_id=trace_id, request=request, max_loops=max_loops,
        )
        self._run_discovery(state)
        state.route = WorkflowRoute.PLAN

        while state.loop_count < state.max_loops:
            state.loop_count += 1
            draft = self._run_node(self.draft_node, state)
            self._require(draft)
            state.plan = draft.value

            prepared = self._run_node(self.prepare_node, state)
            self._require(prepared)
            state.plan = prepared.value["plan"]
            state.selected_hotel = prepared.value["hotel"]
            state.route = WorkflowRoute.ENRICH

            self._run_enrichment(state)
            budget = self._run_node(self.budget_node, state)
            self._require(budget)
            state.plan = budget.value
            self._attach_weather(state)

            state.route = WorkflowRoute.CHECK
            checked = self._run_node(self.constraint_node, state)
            self._require(checked)
            state.constraint_report = checked.value
            if checked.value.passed:
                images = self._run_node(self.image_node, state)
                self._require(images)
                state.plan = images.value
                state.route = WorkflowRoute.COMPLETE
                break

            feedback = checked.value.retryable_messages
            if feedback and state.loop_count < state.max_loops:
                state.route = WorkflowRoute.REPLAN
                state.replan_count += 1
                state.replan_feedback = feedback
                continue

            state.route = WorkflowRoute.FAILED
            state.failure = "；".join(
                item.message for item in checked.value.violations
                if item.severity.value == "error"
            ) or "行程未通过约束检查"
            raise RuntimeError(f"行程未通过约束检查：{state.failure}")

        if state.plan is None or state.route != WorkflowRoute.COMPLETE:
            raise RuntimeError(state.failure or "工作流达到最大循环次数但未生成有效行程")

        state.plan.workflow_metrics = WorkflowMetrics(
            trace_id=state.trace_id,
            status=state.route.value,
            loop_count=state.loop_count,
            replan_count=state.replan_count,
            tool_calls=len(state.traces),
            tool_successes=sum(
                trace.status == ToolStatus.SUCCESS
                for trace in state.traces
            ),
            retry_count=state.retry_count,
            fallback_count=state.fallback_count,
            total_latency_ms=round((perf_counter() - started) * 1000, 2),
            constraint_report=state.constraint_report,
            traces=state.traces,
        )
        return state

    def _run_discovery(self, state: TravelState) -> None:
        results = self._run_parallel(self.discovery_nodes, state)
        for result in results.values():
            self._record(state, result)
        self._require(results["attractions"])
        state.attractions = results["attractions"].value
        state.weather = results["weather"].value or []
        state.hotels = results["hotels"].value or []

    def _run_enrichment(self, state: TravelState) -> None:
        results = self._run_parallel(self.enrichment_nodes, state)
        for result in results.values():
            self._record(state, result)
            self._require(result)

        route_patch = results["routes"].value
        by_day = {day.day: day for day in state.plan.days}
        for patch in route_patch.days:
            day = by_day.get(patch.day)
            if day is not None:
                day.transit_advice = patch.transit_advice
                day.transit_cost = patch.transit_cost
                day.transit_cost_is_estimated = patch.transit_cost_is_estimated

        restaurant_patch = results["restaurants"].value
        for day_number, meal in restaurant_patch.meals.items():
            day = by_day.get(day_number)
            if day is not None:
                day.meals = [meal]

        rail_patch = results["rail"].value
        state.rail_result = (
            rail_patch.rail, rail_patch.rail_is_estimated,
            rail_patch.train_info, rail_patch.train_note,
        )

    def _run_node(self, node, state: TravelState) -> ToolResult:
        result = self.runner.run(node, state)
        self._record(state, result)
        return result

    def _run_parallel(self, nodes, state: TravelState) -> dict[str, ToolResult]:
        """Run independent nodes while preserving request-scoped usage context."""
        tracker = current_llm_usage_tracker.get()

        def run(node):
            token = current_llm_usage_tracker.set(tracker)
            try:
                return self.runner.run(node, state)
            finally:
                current_llm_usage_tracker.reset(token)

        with futures.ThreadPoolExecutor(max_workers=len(nodes)) as executor:
            pending = {node.name: executor.submit(run, node) for node in nodes}
            return {name: future.result() for name, future in pending.items()}

    @staticmethod
    def _require(result: ToolResult) -> None:
        if not result.ok:
            message = result.error.message if result.error else f"{result.tool} failed"
            raise RuntimeError(message)

    @staticmethod
    def _record(state: TravelState, result: ToolResult) -> None:
        state.tool_results[result.tool] = result
        state.retry_count += max(0, result.attempts - 1)
        state.fallback_count += int(result.fallback_used)
        trace = TraceSpan(
            trace_id=state.trace_id,
            node=result.tool,
            status=result.status,
            latency_ms=result.latency_ms,
            attempt=result.attempts,
            fallback_used=result.fallback_used,
            error_code=result.error.code if result.error else None,
        )
        state.traces.append(trace)
        logger.info(
            "agent_stage trace_id=%s stage=%s status=%s duration_ms=%.2f attempts=%d fallback=%s",
            state.trace_id, result.tool, result.status.value, result.latency_ms,
            result.attempts, result.fallback_used,
        )

    @staticmethod
    def _attach_weather(state: TravelState) -> None:
        assert state.plan is not None
        state.plan.weather_info = list(state.weather)
        forecast_dates = {item.date for item in state.weather}
        for day in state.plan.days:
            if day.date not in forecast_dates:
                suffix = "（该日暂无天气预报，未提供）"
                if suffix not in day.notes:
                    day.notes = (day.notes + "；" if day.notes else "") + suffix

