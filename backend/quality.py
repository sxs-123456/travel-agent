"""Deterministic itinerary checks; these are diagnostics, not an LLM judge."""
from datetime import date, timedelta

from backend.models.trip import TripPlan, TripPlanRequest


def evaluate_plan(request: TripPlanRequest, plan: TripPlan) -> dict:
    expected = [
        (date.fromisoformat(request.start_date) + timedelta(days=i)).isoformat()
        for i in range(request.total_days())
    ]
    issues = []
    if (plan.city, plan.start_date, plan.end_date) != (
        request.city, request.start_date, request.end_date
    ):
        issues.append("request_mismatch")
    if [d.date for d in plan.days] != expected:
        issues.append("date_coverage")
    if [d.day for d in plan.days] != list(range(1, len(expected) + 1)):
        issues.append("day_numbering")
    if any(not d.attractions for d in plan.days):
        issues.append("empty_day")
    names = ["".join(c for c in a.name if c.isalnum())
             for d in plan.days for a in d.attractions]
    if len(names) != len(set(names)):
        issues.append("duplicate_attraction")
    if any(d.hotel is not None for d in plan.days if d.date >= request.end_date):
        issues.append("return_day_hotel")
    budget = plan.budget
    if budget is None:
        issues.append("missing_budget")
    elif (budget.total != budget.ticket_total + budget.hotel_total
          + budget.meal_total + budget.transport_total
          or budget.transport_total != budget.rail_total + budget.taxi_total):
        issues.append("budget_inconsistent")
    weather_dates = {w.date for w in plan.weather_info}
    return {
        "passed": not issues,
        "issues": issues,
        "weather_coverage": sum(d in weather_dates for d in expected) / len(expected),
        "day_coverage": len(set(expected) & {d.date for d in plan.days}) / len(expected),
    }
