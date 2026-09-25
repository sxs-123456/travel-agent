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

from backend.models.trip import TripPlan, TripPlanRequest
from backend.planner import TripPlannerAgent
from backend.tracing import request_id as current_request_id

logger = logging.getLogger("trip-planner")

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/trip-plan", response_model=TripPlan)
def create_plan(request: TripPlanRequest) -> TripPlan:
    """接收行程请求，返回完整的多智能体规划结果。"""
    try:
        return planner.plan_trip(request)
    except Exception as e:  # noqa: BLE001  边界处统一兜底，避免向客户端泄漏堆栈
        logger.exception("行程规划失败")
        # 截断 detail，防止 LLM/上游返回的完整原文被回给前端
        detail = (str(e) or e.__class__.__name__)[:200]
        status = 400 if isinstance(e, RuntimeError) else 502
        return JSONResponse(status_code=status, content={"detail": detail})


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
