"""FastAPI 应用：对外提供行程规划 HTTP 接口。"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# 允许以脚本方式直接运行本模块
_ROOT_MARKERS = ("backend", "requirements.txt")
_PROJECT_ROOT = Path(__file__).resolve().parent
while (
    not any((_PROJECT_ROOT / m).exists() for m in _ROOT_MARKERS)
    and _PROJECT_ROOT.parent != _PROJECT_ROOT
):
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.models.trip import TripPlan, TripPlanRequest
from backend.models.rag import RagQueryRequest, RagQueryResponse
from backend.planner import TripPlannerAgent

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
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
] or _default_origins

app = FastAPI(title="智能旅行助手 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

planner = TripPlannerAgent()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/trip-plan", response_model=TripPlan)
def create_plan(request: TripPlanRequest) -> TripPlan:
    """接收行程请求，返回完整的多智能体规划结果。"""
    # 调试期临时打印请求体（含 origin_city），便于定位「填了出发城市但查不到车票」类问题。
    # 上线后可移除或降级为 debug 日志。
    print(f"[trip-plan] request: {request.model_dump_json()}", flush=True)
    try:
        return planner.plan_trip(request)
    except Exception as e:  # noqa: BLE001  边界处统一兜底，避免向客户端泄漏堆栈
        logger.exception("行程规划失败")
        # 截断 detail，防止 LLM/上游返回的完整原文被回给前端
        detail = (str(e) or e.__class__.__name__)[:200]
        status = 400 if isinstance(e, RuntimeError) else 502
        return JSONResponse(status_code=status, content={"detail": detail})


@app.post("/api/rag/query", response_model=RagQueryResponse)
def rag_query(request: RagQueryRequest) -> RagQueryResponse:
    """知识库问答（RAG）：向量检索 + LLM 生成带引用来源的回答。

    依赖未安装或知识库为空时返回 503，并给出清晰的安装/入库提示。
    """
    from backend.rag import query_knowledge, RagUnavailableError

    try:
        return query_knowledge(request.question, top_k=request.top_k)
    except RagUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


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
