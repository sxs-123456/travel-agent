"""FastAPI 应用：对外提供行程规划 HTTP 接口。"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.config import settings
from backend.intent import TripIntentError, parse_trip_intent
from backend.models.trip import TripPlan, TripPlanRequest
from backend.observability import LlmUsageTracker, current_llm_usage_tracker
from backend.planner import TripPlannerAgent
from backend.tracing import request_id as current_request_id

logger = logging.getLogger("trip-planner")

_LLM_QUOTA_MESSAGE = "AI 服务额度已用完，请联系站点维护者更新模型账户额度。"


def _is_llm_quota_error(exc: BaseException) -> bool:
    """识别模型供应商的 402 错误，不把原始上游响应回显给用户。"""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None)
        response = getattr(current, "response", None)
        if status == 402 or getattr(response, "status_code", None) == 402:
            return True
        if "insufficient balance" in str(current).lower():
            return True
        current = current.__cause__ or current.__context__
    return False

# CORS：默认仅允许本地前端来源；如需放开，用 CORS_ORIGINS（逗号分隔）覆盖。
_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
]
_cors_origins = [
    o.strip().rstrip("/")
    for o in os.getenv("CORS_ORIGINS", "").split(",")
    if o.strip()
] or _default_origins

app = FastAPI(title="智能旅行助手 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

@app.middleware("http")
async def trace_request(request, call_next):
    request_id = uuid4().hex
    started = perf_counter()
    token = current_request_id.set(request_id)
    try:
        response = await call_next(request)
    finally:
        current_request_id.reset(token)
    response.headers["X-Request-ID"] = request_id
    logger.info("http_request request_id=%s method=%s path=%s status=%d duration_ms=%.2f",
                request_id, request.method, request.url.path, response.status_code,
                (perf_counter() - started) * 1000)
    return response


planner = TripPlannerAgent()


class NaturalTripRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    start_date: str | None = None
    end_date: str | None = None

    @field_validator("query")
    @classmethod
    def nonempty_query(cls, value: str) -> str:
        if len(value.strip()) < 2:
            raise ValueError("请告诉我你想去哪里")
        return value.strip()

    @field_validator("start_date", "end_date")
    @classmethod
    def valid_optional_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from datetime import date

        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("请选择有效日期") from None
        return parsed.isoformat()


class NaturalTripResponse(BaseModel):
    request: TripPlanRequest
    plan: TripPlan


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/public-config")
def public_config() -> dict[str, str]:
    """只向浏览器提供本来就会公开的高德 JS API 配置，不返回服务端密钥。"""
    return {
        "amap_js_key": os.getenv("AMAP_JS_API_KEY") or os.getenv("VITE_AMAP_KEY", ""),
        "amap_js_security_code": (
            os.getenv("AMAP_JS_API_SECURITY_CODE")
            or os.getenv("VITE_AMAP_SECURITY_CODE", "")
        ),
    }


@app.post("/api/trip-plan", response_model=TripPlan)
def create_plan(request: TripPlanRequest) -> TripPlan:
    """接收行程请求，返回完整的多智能体规划结果。"""
    try:
        return planner.plan_trip(request)
    except Exception as e:  # noqa: BLE001  边界处统一兜底，避免向客户端泄漏堆栈
        logger.exception("行程规划失败")
        if _is_llm_quota_error(e):
            return JSONResponse(status_code=503, content={"detail": _LLM_QUOTA_MESSAGE})
        detail = (
            (str(e) or e.__class__.__name__)[:200]
            if isinstance(e, RuntimeError)
            else "行程规划暂时不可用，请稍后重试。"
        )
        status = 400 if isinstance(e, RuntimeError) else 502
        return JSONResponse(status_code=status, content={"detail": detail})


@app.post("/api/trip-plan/from-text", response_model=NaturalTripResponse)
def create_plan_from_text(payload: NaturalTripRequest) -> NaturalTripResponse | JSONResponse:
    """Extract a natural-language request and run the existing planner."""
    intent_tracker = LlmUsageTracker()
    token = current_llm_usage_tracker.set(intent_tracker)
    try:
        if payload.start_date or payload.end_date:
            request = parse_trip_intent(
                payload.query,
                start_date_override=payload.start_date,
                end_date_override=payload.end_date,
            )
        else:
            # 保持单参数调用，兼容现有集成和扩展。
            request = parse_trip_intent(payload.query)
    except TripIntentError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "missing_fields": exc.missing_fields},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("旅行需求解析失败")
        if _is_llm_quota_error(exc):
            return JSONResponse(status_code=503, content={"detail": _LLM_QUOTA_MESSAGE})
        detail = str(exc)[:200] if isinstance(exc, RuntimeError) else "需求解析暂时不可用，请稍后重试。"
        status = 400 if isinstance(exc, RuntimeError) else 502
        return JSONResponse(status_code=status, content={"detail": detail})
    finally:
        current_llm_usage_tracker.reset(token)
    result = create_plan(request)
    if isinstance(result, JSONResponse):
        return result
    if result.generation_metrics:
        intent_usage = intent_tracker.snapshot(
            model=settings.llm_model,
            input_cost_per_1m_usd=settings.llm_input_cost_per_1m_usd,
            output_cost_per_1m_usd=settings.llm_output_cost_per_1m_usd,
        )
        metrics = result.generation_metrics
        metrics.calls += intent_usage["calls"]
        metrics.input_tokens += intent_usage["input_tokens"]
        metrics.output_tokens += intent_usage["output_tokens"]
        metrics.total_tokens += intent_usage["total_tokens"]
        metrics.usage_available = metrics.usage_available or intent_usage["usage_available"]
        if intent_usage["estimated_cost_usd"] is not None:
            metrics.estimated_cost_usd = round(
                (metrics.estimated_cost_usd or 0) + intent_usage["estimated_cost_usd"], 6
            )
    return NaturalTripResponse(request=request, plan=result)


# ---------------------------------------------------------------------------
# 前端托管：若已构建 frontend/dist，则在同一端口直接提供页面（无需单独跑 Vite）。
# API 路由（/api、/health、/docs）已在上方注册，优先匹配；其余路径回退到 index.html（SPA）。
# 使用 StaticFiles 挂载，Starlette 会拒绝任何 ../ 目录穿越，从根本上杜绝密钥泄露。
# ---------------------------------------------------------------------------
_DIST_DIR = _PROJECT_ROOT / "frontend" / "dist"

if _DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="spa")
else:
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        raise HTTPException(
            status_code=404,
            detail="未找到前端构建产物。请先构建前端（cd frontend && npm install && npm run build），"
            "或直接用开发模式（cd frontend && npm run dev）。",
        )
