"""
智能旅行助手（Trip Planner Agent）
=================================

基于《Hello-Agents》第十三章「智能旅行助手」架构实现的完整 Agent 项目。

技术栈：
- 多智能体协作（LangChain ChatOpenAI + 结构化输出 + function_calling/json_mode 双通道）
- Pydantic 数据模型（自底向上：Location → Attraction/Meal/Hotel → DayPlan → TripPlan）
- 外部工具：高德（景点/天气/酒店）、12306（车票）、百度地图（打车）、百度百科（门票）、
  Pexels/Openverse（封面图）、Open-Meteo（天气补充）、本地 RAG 知识库
- FastAPI 提供 HTTP 接口 + Vue3 前端

架构（四层，前后端分离）：
  前端(Vue3)  →  FastAPI  →  多智能体编排层  →  外部服务(高德/12306/百度/LLM/Pexels)

四个专属 Agent：
  - AttractionSearchAgent：按偏好搜索景点（门票经百度百科回填）
  - WeatherQueryAgent：查询目的地天气（高德 + Open-Meteo 补充长行程）
  - HotelAgent：搜索推荐酒店（档次由预算等级决定）
  - PlannerAgent：整合上述结果，生成逐日行程 + 预算 + 车次推荐

运行模式：
  - 仅真实模式：所有外部数据（景点 / 天气 / 酒店 / 行程 / 封面图 / 车票）均来自真实接口，
    不保留任何 Mock 或演示数据。运行前需在 .env 配置 LLM_API_KEY 与 AMAP_API_KEY
    （参考 .env.example），缺失密钥将抛出清晰错误。

"""

import sys
from pathlib import Path

# 允许直接双击/IDE 运行本文件时也能找到 backend 包
_ROOT_MARKERS = ("backend", "requirements.txt")
_PROJECT_ROOT = Path(__file__).resolve().parent
while (
    not any((_PROJECT_ROOT / m).exists() for m in _ROOT_MARKERS)
    and _PROJECT_ROOT.parent != _PROJECT_ROOT
):
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.config import settings

__all__ = ["settings"]
