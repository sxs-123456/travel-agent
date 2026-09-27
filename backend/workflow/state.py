"""Shared state passed through every node in the travel workflow."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend.models.agent import ConstraintReport, ToolResult, TraceSpan
from backend.models.trip import Attraction, Hotel, TripPlan, TripPlanRequest, WeatherInfo


class WorkflowRoute(str, Enum):
    DISCOVER = "discover"
    PLAN = "plan"
    ENRICH = "enrich"
    CHECK = "check"
    REPLAN = "replan"
    COMPLETE = "complete"
    FAILED = "failed"


class TravelState(BaseModel):
    """Strongly typed source of truth for a single planning request."""

    trace_id: str
    request: TripPlanRequest
    route: WorkflowRoute = WorkflowRoute.DISCOVER
    attractions: list[Attraction] = Field(default_factory=list)
    hotels: list[Hotel] = Field(default_factory=list)
    selected_hotel: Hotel | None = None
    weather: list[WeatherInfo] = Field(default_factory=list)
    plan: TripPlan | None = None
    rail_result: tuple[int, bool, list[Any] | None, str | None] | None = None
    constraint_report: ConstraintReport | None = None
    tool_results: dict[str, ToolResult[Any]] = Field(default_factory=dict)
    traces: list[TraceSpan] = Field(default_factory=list)
    replan_feedback: list[str] = Field(default_factory=list)
    loop_count: int = 0
    replan_count: int = 0
    retry_count: int = 0
    fallback_count: int = 0
    max_loops: int = Field(default=2, ge=1, le=5)
    failure: str | None = None

