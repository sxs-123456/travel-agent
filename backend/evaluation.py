"""旅行规划评测指标汇总；不依赖外部接口，可独立测试。"""
from collections import Counter
from statistics import mean


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


def summarize(records: list[dict]) -> dict:
    """汇总端到端评测记录，返回适合落盘和简历引用的客观指标。"""
    successful = [record for record in records if record.get("success")]
    reports = [record["quality"] for record in successful if record.get("quality")]
    issues = Counter(
        issue for report in reports for issue in report.get("issues", [])
    )
    latencies = [float(record["latency_ms"]) for record in records]
    usages = [record["llm_usage"] for record in successful if record.get("llm_usage")]
    usage_with_tokens = [usage for usage in usages if usage.get("usage_available")]
    known_costs = [
        float(usage["estimated_cost_usd"])
        for usage in usages
        if usage.get("estimated_cost_usd") is not None
    ]
    total = len(records)
    return {
        "total_cases": total,
        "successful_cases": len(successful),
        "success_rate": round(len(successful) / total, 4) if total else 0.0,
        "quality_pass_rate": (
            round(sum(bool(report.get("passed")) for report in reports) / len(reports), 4)
            if reports else 0.0
        ),
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "average_day_coverage": (
            round(mean(report.get("day_coverage", 0) for report in reports), 4)
            if reports else 0.0
        ),
        "average_weather_coverage": (
            round(mean(report.get("weather_coverage", 0) for report in reports), 4)
            if reports else 0.0
        ),
        "issue_counts": dict(sorted(issues.items())),
        "llm_usage": {
            "reported_cases": len(usage_with_tokens),
            "calls": sum(int(usage.get("calls", 0)) for usage in usages),
            "input_tokens": sum(int(usage.get("input_tokens", 0)) for usage in usages),
            "output_tokens": sum(int(usage.get("output_tokens", 0)) for usage in usages),
            "total_tokens": sum(int(usage.get("total_tokens", 0)) for usage in usages),
            "estimated_cost_usd": round(sum(known_costs), 6) if known_costs else None,
        },
    }
