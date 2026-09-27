"""Deterministic constraints and optional LLM-only semantic preference checks."""
from __future__ import annotations

import re
from datetime import date
from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel, Field

from backend.agents.base import get_llm, structured_chain
from backend.models.agent import (
    ConstraintReport,
    ConstraintSeverity,
    ConstraintViolation,
)
from backend.models.trip import TripPlan, TripPlanRequest
from backend.workflow.state import TravelState


def _norm(value: str) -> str:
    return "".join(character for character in value if character.isalnum()).lower()


def _same_place(left: str, right: str) -> bool:
    left, right = _norm(left), _norm(right)
    if not left or not right:
        return False
    return left == right or (
        min(len(left), len(right)) >= 4 and (left in right or right in left)
    )


def _distance_km(left, right) -> float:
    lon1, lat1, lon2, lat2 = map(radians, (
        left.longitude, left.latitude, right.longitude, right.latitude,
    ))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(h))


class SemanticAssessment(BaseModel):
    satisfied: bool
    reasons: list[str] = Field(default_factory=list)


class SemanticPreferenceChecker:
    """LLM seam limited to preference meaning; it receives no authority over facts."""

    def check(self, request: TripPlanRequest, plan: TripPlan) -> list[ConstraintViolation]:
        itinerary = [
            {"day": day.day, "attractions": [item.name for item in day.attractions]}
            for day in plan.days
        ]
        prompt = (
            "只判断行程景点在语义上是否覆盖用户偏好，不核验名称、坐标、价格、"
            "营业时间或其他事实。返回 satisfied 和简短 reasons。\n"
            f"用户偏好：{request.preferences}\n行程：{itinerary}"
        )
        assessment: SemanticAssessment = structured_chain(
            get_llm(temperature=0), SemanticAssessment
        ).invoke(prompt)
        if assessment.satisfied:
            return []
        return [ConstraintViolation(
            code="semantic_preference_mismatch",
            message="；".join(assessment.reasons) or "行程未覆盖用户语义偏好",
            deterministic=False,
            retryable=True,
        )]


class ConstraintChecker:
    """Validate facts and hard constraints without asking an LLM to judge them."""

    _BUDGET_HOTEL_LEVELS = {
        "经济": ("经济", "舒适"),
        "中等": ("舒适", "高档", "经济"),
        "豪华": ("豪华", "高档"),
    }

    def __init__(self, semantic_checker: SemanticPreferenceChecker | None = None) -> None:
        self.semantic_checker = semantic_checker

    def check(self, state: TravelState) -> ConstraintReport:
        if state.plan is None:
            violation = ConstraintViolation(
                code="missing_plan", message="规划节点未生成行程", retryable=True
            )
            return ConstraintReport(
                passed=False, violations=[violation], grounded_poi_rate=0,
                constraint_satisfaction_rate=0, duplicate_rate=0, hallucination_rate=1,
            )

        request, plan = state.request, state.plan
        violations: list[ConstraintViolation] = []
        expected_dates = [
            date.fromordinal(date.fromisoformat(request.start_date).toordinal() + index).isoformat()
            for index in range(request.total_days())
        ]
        if (plan.city, plan.start_date, plan.end_date) != (
            request.city, request.start_date, request.end_date
        ):
            violations.append(ConstraintViolation(
                code="request_mismatch", message="行程城市或日期与用户请求不一致"
            ))
        if [day.date for day in plan.days] != expected_dates:
            violations.append(ConstraintViolation(
                code="date_coverage", message="逐日行程未完整覆盖出返程日期"
            ))
        if any(not day.attractions for day in plan.days):
            violations.append(ConstraintViolation(
                code="empty_day", message="存在没有真实景点的空白行程日"
            ))

        candidate_ids = {item.source_id for item in state.attractions if item.source_id}
        planned = [item for day in plan.days for item in day.attractions]
        grounded = [
            item for item in planned
            if item.source_id is not None and item.source_id in candidate_ids
        ]
        unknown = [item for item in planned if item not in grounded]
        for item in unknown:
            violations.append(ConstraintViolation(
                code="ungrounded_poi",
                message=f"景点「{item.name}」无法匹配真实候选 source_id",
                path=f"attractions.{item.name}",
            ))

        duplicate_count = 0
        seen_names: list[str] = []
        for item in planned:
            if any(_same_place(item.name, seen) for seen in seen_names):
                duplicate_count += 1
                violations.append(ConstraintViolation(
                    code="duplicate_attraction",
                    message=f"景点「{item.name}」与其他日景点重复或属于同一景区",
                    path=f"attractions.{item.name}",
                ))
            seen_names.append(item.name)

        forbidden = self._forbidden_places(request.preferences)
        for item in planned:
            if any(token and token in _norm(item.name) for token in forbidden):
                violations.append(ConstraintViolation(
                    code="hard_constraint_forbidden_place",
                    message=f"用户明确要求避开的地点仍出现在行程中：{item.name}",
                ))

        for day_plan in plan.days:
            weekday = date.fromisoformat(day_plan.date).weekday() + 1
            total_hours = sum(item.recommended_duration for item in day_plan.attractions)
            route_hours = float(day_plan.route_distance_km or 0) / 20
            if total_hours + route_hours > 10:
                violations.append(ConstraintViolation(
                    code="daily_time_conflict",
                    message=f"Day {day_plan.day} 的游玩与通勤预计超过 10 小时",
                    path=f"days.{day_plan.day}",
                ))
            if (day_plan.route_distance_km or 0) > 60:
                violations.append(ConstraintViolation(
                    code="route_too_long",
                    message=f"Day {day_plan.day} 的市内路线距离过长",
                    path=f"days.{day_plan.day}.route_distance_km",
                ))
            for previous, current in zip(day_plan.attractions, day_plan.attractions[1:]):
                if _distance_km(previous.location, current.location) > 40:
                    violations.append(ConstraintViolation(
                        code="route_leg_too_long",
                        message=f"{previous.name} 到 {current.name} 的单段距离超过 40 公里",
                        path=f"days.{day_plan.day}.attractions",
                    ))
            for attraction in day_plan.attractions:
                hours = attraction.opening_hours or ""
                if self._closed_on_weekday(hours, weekday):
                    violations.append(ConstraintViolation(
                        code="attraction_closed",
                        message=f"{attraction.name} 在 Day {day_plan.day} 可能闭馆：{hours}",
                        path=f"days.{day_plan.day}.attractions.{attraction.name}",
                    ))

        if plan.budget is None:
            violations.append(ConstraintViolation(
                code="missing_budget", message="缺少确定性预算汇总"
            ))
        else:
            budget = plan.budget
            if budget.total != (
                budget.ticket_total + budget.hotel_total
                + budget.meal_total + budget.transport_total
            ) or budget.transport_total != budget.rail_total + budget.local_transit_total:
                violations.append(ConstraintViolation(
                    code="budget_inconsistent", message="预算分项与总额不一致"
                ))
            if request.budget_max is not None and budget.total > request.budget_max:
                violations.append(ConstraintViolation(
                    code="budget_exceeded",
                    message=f"预计总额 ¥{budget.total} 超过用户预算上限 ¥{request.budget_max}",
                ))

        allowed_levels = self._BUDGET_HOTEL_LEVELS.get(request.budget_level, ())
        selected_hotels = [day.hotel for day in plan.days if day.hotel]
        if allowed_levels and any(
            hotel.level and not any(level in hotel.level for level in allowed_levels)
            for hotel in selected_hotels
        ):
            violations.append(ConstraintViolation(
                code="hotel_budget_mismatch",
                message="酒店档次与用户预算等级不一致",
                severity=ConstraintSeverity.WARNING,
                retryable=False,
            ))

        if self.semantic_checker is not None:
            violations.extend(self.semantic_checker.check(request, plan))

        errors = [item for item in violations if item.severity == ConstraintSeverity.ERROR]
        checks = 8 + len(planned)
        grounded_rate = len(grounded) / len(planned) if planned else 0.0
        duplicate_rate = duplicate_count / len(planned) if planned else 0.0
        hallucination_rate = len(unknown) / len(planned) if planned else 1.0
        return ConstraintReport(
            passed=not errors,
            violations=violations,
            grounded_poi_rate=round(grounded_rate, 4),
            constraint_satisfaction_rate=round(max(0, checks - len(errors)) / checks, 4),
            duplicate_rate=round(duplicate_rate, 4),
            hallucination_rate=round(hallucination_rate, 4),
        )

    @staticmethod
    def _forbidden_places(preferences: str) -> set[str]:
        values = re.findall(r"(?:不去|不要去|避开)\s*([^，。；、,;]+)", preferences)
        return {_norm(value) for value in values if _norm(value)}

    @staticmethod
    def _closed_on_weekday(opening_hours: str, weekday: int) -> bool:
        if not opening_hours:
            return False
        chinese = "一二三四五六日"[weekday - 1]
        return bool(re.search(rf"(?:周|星期){chinese}[^；;，,]*(?:闭馆|休息|不开放)", opening_hours))
