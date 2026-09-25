"""Against a running API, execute fixed cases and persist reproducible metrics."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.evaluation import summarize  # noqa: E402
from backend.models.trip import TripPlan, TripPlanRequest  # noqa: E402
from backend.quality import evaluate_plan  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="运行旅行规划 Agent 固定评测集")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results" / "latest.json")
    parser.add_argument("--start-offset-days", type=int, default=7)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--case-name", help="只运行指定名称的场景（用于失败案例回归）")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.case_name:
        cases = [case for case in cases if case["name"] == args.case_name]
        if not cases:
            parser.error(f"未找到场景：{args.case_name}")
    start = date.today() + timedelta(days=args.start_offset_days)
    records = []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        for case in cases:
            duration = max(1, int(case["duration_days"]))
            body = {
                key: value for key, value in case.items()
                if key not in {"name", "duration_days"}
            }
            body["start_date"] = start.isoformat()
            body["end_date"] = (start + timedelta(days=duration - 1)).isoformat()
            request = TripPlanRequest.model_validate(body)
            started = perf_counter()
            try:
                response = client.post("/api/trip-plan", json=request.model_dump())
                latency = (perf_counter() - started) * 1000
                response.raise_for_status()
                plan = TripPlan.model_validate(response.json())
                record = {
                    "name": case["name"],
                    "success": True,
                    "latency_ms": round(latency, 2),
                    "request_id": response.headers.get("X-Request-ID"),
                    "quality": evaluate_plan(request, plan),
                    "llm_usage": (
                        plan.generation_metrics.model_dump()
                        if plan.generation_metrics else None
                    ),
                }
            except Exception as exc:  # each case must remain visible in the report
                record = {
                    "name": case["name"],
                    "success": False,
                    "latency_ms": round((perf_counter() - started) * 1000, 2),
                    "error": str(exc)[:300],
                }
            records.append(record)
            print(f"{record['name']}: {'ok' if record['success'] else 'failed'}")

    payload = {"summary": summarize(records), "records": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"结果已写入 {args.output}")


if __name__ == "__main__":
    main()
