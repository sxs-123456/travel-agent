"""图片服务：按关键词返回一张真实封面图 URL。

来源优先级（全部为真实图片，绝不返回占位/假图）：
1. Pexels 免费图库（需 PEXELS_API_KEY，留空自动跳过）——高质量、免署名、可外链，
   免费额度 200 次/时、2 万次/月，作为首选；
2. Openverse 开放图片 API（免费、无需 key，聚合 Flickr/Wikimedia/Europeana 等
   6 亿+ CC 授权图库，中文关键词可搜）——唯一兜底；
3. 全部失败 → None，前端优雅降级为无图（不显示假图）。

说明：本项目不再使用 Unsplash（需 key 且只有 50 次/小时额度限制）。
另：百度百科词条首图在 agents/attraction.py 与门票一起获取（同一 API），
不经过本模块；高德 POI 实景照片由 tools/amap.py 直接返回。
"""
from __future__ import annotations

import httpx

from backend.config import settings

OPENVERSE_API = "https://api.openverse.org/v1/images/"
PEXELS_API = "https://api.pexels.com/v1/search"

# Openverse 匿名限流（429）与 Wikimedia 强制 User-Agent 的通用请求头。
_UA_HEADERS = {
    "User-Agent": "TripPlannerAgent/1.0 (travel itinerary; contact: dev@example.com)",
}

# 进程内缓存：同一关键词不重复请求（同酒店多晚、多次规划只查一次）。
# 仅缓存成功结果，None 不缓存。
_cache: dict[str, str] = {}

_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# 非照片文件特征（djvu 扫描页 / pdf / svg 地图 / 动图等）
_NON_PHOTO_MARKERS = (
    ".djvu", ".pdf", ".svg", ".tif", ".tiff", ".gif", ".ico",
    ".xcf", ".ogg", ".webm", ".ogv",
)


def _looks_like_photo(url: str) -> bool:
    """过滤掉 SVG 地图 / djvu 扫描页 / 图标等非照片文件。"""
    path = url.lower().split("?")[0]
    if any(m in path for m in _NON_PHOTO_MARKERS):
        return False
    return path.endswith(_PHOTO_EXTS)


def _base_url(url: str) -> str:
    """去掉 query 参数，用于比对「是否同一张图」。"""
    return url.split("?")[0]


def _search_pexels(keyword: str, exclude: set[str] | None = None) -> str | None:
    """Pexels 免费图库（首选，需 PEXELS_API_KEY；留空自动跳过）。

    真实照片、商用免费、免署名、可外链。额度 200 次/时、2 万次/月。
    返回横版大图直链；跳过 exclude 中已用过的图，尽量给不同结果。
    异常/未配 key 时返回 None，由 Openverse 兜底。
    """
    if not settings.pexels_api_key:
        return None
    exclude = exclude or set()
    params = {"query": keyword, "per_page": 15, "orientation": "landscape"}
    headers = {"Authorization": settings.pexels_api_key}
    try:
        resp = httpx.get(PEXELS_API, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        photos = resp.json().get("photos") or []
    except Exception:  # noqa: BLE001  图片为辅助信息，失败不拖垮行程
        return None
    for p in photos:
        src = p.get("src") or {}
        url = src.get("large") or src.get("original")
        if url and _looks_like_photo(url) and _base_url(url) not in exclude:
            return url
    return None


def _search_openverse(keyword: str, exclude: set[str] | None = None) -> str | None:
    """Openverse 检索（免费开放 API，无需 key）——唯一兜底。

    聚合 Flickr / Wikimedia Commons / Europeana 等 6 亿+ CC 授权图库，
    中文关键词可搜。跳过 exclude 中已用过的图。匿名调用可能 429 限流。
    """
    exclude = exclude or set()
    params = {
        "q": keyword,
        "license_type": "all",
        "page_size": 15,
        "aspect_ratio": "wide",   # 封面更贴合横版展示
    }
    try:
        resp = httpx.get(
            OPENVERSE_API, params=params, headers=_UA_HEADERS, timeout=10
        )
        if getattr(resp, "status_code", 200) == 429:  # 匿名限流：返回 None
            return None
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception:  # noqa: BLE001  图片为辅助信息，失败不拖垮行程
        return None
    for item in results:
        url = item.get("url") or item.get("thumbnail")
        if url and _looks_like_photo(url.split("?")[0]) and _base_url(url) not in exclude:
            return url
    return None


def search_image(keyword: str, exclude: set[str] | None = None) -> str | None:
    """按关键词返回一张真实封面图 URL；全部来源失败时返回 None。

    优先级：Pexels（有 key）→ Openverse（免 key）→ None。
    exclude 传入「本次行程已用过的图」，尽量给不同景点/酒店返回不同照片。
    任何异常都不会抛出，由上层决定降级为无图，绝不返回假 URL。
    """
    if not keyword:
        return None
    exclude = {_base_url(u) for u in (exclude or set())}
    cached = _cache.get(keyword)
    if cached and _base_url(cached) not in exclude:
        return cached

    url = _search_pexels(keyword, exclude)
    if not url:
        url = _search_openverse(keyword, exclude)

    if url and _base_url(url) not in exclude:
        _cache[keyword] = url
    return url
