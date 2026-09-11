"""百度百科词条卡片 API（免费、无需 key、结构化）：门票价格。

数据源说明
----------
- 高德免费接口（v3/v5 实测）不返回景点门票价格；
- 百度百科卡片 API（https://baike.baidu.com/api/openapi/BaikeLemmaCardApi）
  是公开的免 key 接口，词条卡片含「门票价格」字段（如故宫：
  「60元旺季/40元淡季(珍宝馆、钟表馆10元)」），覆盖大量 5A/4A 景区；
- 查询不到（词条缺失/无字段/接口失败）时返回 (None, None)，由上层如实标注
  「门票以景区现场公告为准」，绝不臆造价格。

返回
----
query_baike_card(name) -> (price: int | None, note: str | None)
- price：文本中第一个「X元」的价格（元，旺季/常规价），无法解析为 None；
- note：清理 HTML 后的原始门票说明文本（如「60元旺季/40元淡季」）。
"""
from __future__ import annotations

import re
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

import httpx

BAIKE_CARD_API = "https://baike.baidu.com/api/openapi/BaikeLemmaCardApi"

# 进程内缓存：同一景点只查一次（门票共享缓存，多次规划不重复请求）。
_cache: dict[str, tuple[int | None, str | None]] = {}


def _strip_html(text: str) -> str:
    """去掉百度百科 value 里的 HTML 标签、角标及其内容（<sup>4</sup><a ...> 等）。"""
    if not text:
        return ""
    # 先整体移除 <sup>…</sup> / <a …>…</a> 这类带内容的角标（连内容一起删，避免残留 "4"）
    text = re.sub(r"<sup>.*?</sup>", "", text, flags=re.DOTALL)
    text = re.sub(r"<a\b[^>]*>.*?</a>", "", text, flags=re.DOTALL)
    # 再删剩余孤立标签
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_price(text: str) -> int | None:
    """从门票文本中提取第一个「X元」的价格（元，取整数）。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
    if not m:
        return None
    try:
        return int(float(m.group(1)))
    except (ValueError, TypeError):
        return None


def query_baike_card(name: str) -> tuple[int | None, str | None]:
    """按景点名查询百度百科词条，返回 (门票价格, 门票说明)。

    任何失败（词条缺失/网络异常）都返回 (None, None)，
    绝不抛出异常、绝不臆造数据，由上层决定如何展示。
    """
    if not name:
        return None, None
    if name in _cache:
        return _cache[name]

    params = {
        "scope": "103",
        "format": "json",
        "appid": "379020",  # 百度百科卡片 API 公开演示 appid
        "bk_key": name,
    }
    try:
        resp = httpx.get(
            BAIKE_CARD_API, params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception:  # noqa: BLE001  辅助信息，失败不拖垮行程
        _cache[name] = (None, None)
        return None, None

    # 门票价格（card 列表里的「门票价格」项）
    note: str | None = None
    for item in data.get("card") or []:
        if str(item.get("name") or "") != "门票价格":
            continue
        values = item.get("value")
        if isinstance(values, list) and values:
            note = _strip_html(str(values[0]))
        elif isinstance(values, str):
            note = _strip_html(values)
        break
    price = _parse_price(note) if note else None

    _cache[name] = (price, note)
    return price, note
