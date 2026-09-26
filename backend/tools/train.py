"""火车票供应商：直连 12306 官方（真实、免费、免 key、免 npx）。

融合自 Agent2Agent 出行助手（D:/develop/PythonProject/agent/train.py），
作为旅行助手的「真实车票票价」数据源，替换原先依赖 `npx 12306-mcp`
（社区逆向 MCP server）的方案——直连 12306 官方接口无需 Node/npx，更稳、零额外依赖。

说明
----
- 12306 是国内铁路官方，余票/车次/时刻为公开数据，个人查询不需要 key。
- 反爬：需先访问 leftTicket/init 拿 C_LEFT_TICKET cookie；证书链在部分环境不被信任，
  故使用宽松 SSL 上下文（查询不含敏感信息，仅读取公开车次/余票）。
- 票价：通过 12306 官方 queryTicketPrice 接口实时获取各席别真实票价（见 get_prices），
  展示时标注「以官方最终下单为准」，不臆造。
- 仅真实模式：不提供任何 Mock；接口异常抛出 TrainApiError，由上层回退到估算。
"""
from __future__ import annotations

import http.cookiejar as _cookiejar
import json
import os
import ssl as _ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

try:
    import certifi  # 若装了则用其 CA 库做严格校验
    _SSL_CTX = _ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = _ssl._create_unverified_context()  # 退而求其次：宽松校验


class TrainApiError(RuntimeError):
    """12306 无法返回可信的真实结果时抛出（用于友好报错，不造假）。"""


def _normalize_date(text: str, default_year: int | None = None) -> str:
    """把宽松 / 自然语言日期统一成 YYYY-MM-DD。不合法则抛错。"""
    import re
    from datetime import datetime

    if not text:
        raise ValueError("缺少日期；请提供 YYYY-MM-DD 或『8/16』这类格式。")
    text = str(text).strip()
    year = default_year or datetime.now().year
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    elif (m := re.fullmatch(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", text)):
        y, mo, d = (int(x) for x in m.groups())
    elif (m := re.fullmatch(r"(\d{1,2})[/.](\d{1,2})", text)):
        mo, d = (int(x) for x in m.groups())
        y = year
    elif (m := re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text)):
        mo, d = (int(x) for x in m.groups())
        y = year
    elif (m := re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text)):
        y, mo, d = (int(x) for x in m.groups())
    else:
        raise ValueError(f"无法识别日期格式：{text!r}（请使用 YYYY-MM-DD 或『8/16』）。")
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        raise ValueError(f"日期不合法：{text!r}")
    return f"{y:04d}-{mo:02d}-{d:02d}"


_TRAIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
}

# 12306 余票串中各席别所在的字段索引（按真实返回实测校准；不同车型略有差异，缺失即不显示）。
_SEAT_NAME_BY_INDEX: dict[int, str] = {
    19: "无座",
    23: "高级软卧",
    24: "软卧",
    25: "硬卧",
    28: "动卧",
    29: "硬座",
}
# 高铁/动车/城际额外包含商务/特等/一/二等座
_HS_SEAT_NAME_BY_INDEX: dict[int, str] = {
    26: "商务座",
    30: "特等座",
    31: "一等座",
    32: "二等座",
}


class TrainTicketProvider:
    """直连 12306 官方接口查询火车票车次与真实票价。"""

    name = "12306-官方火车票(真实免费,免Key)"
    STATION_URL = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
    INIT_URL = "https://kyfw.12306.cn/otn/leftTicket/init"
    TICKET_URL = "https://kyfw.12306.cn/otn/leftTicket/query"
    PRICE_URL = "https://kyfw.12306.cn/otn/leftTicket/queryTicketPrice"

    # queryTicketPrice 返回 key -> 规范化席别名（与余票解析的 type 对齐，便于匹配）
    _PRICE_KEY_TO_SEAT: dict[str, str] = {
        "A1": "商务座", "A2": "特等座", "A3": "一等包座", "A4": "一等座",
        "A5": "二等座", "A6": "高级软卧", "A7": "软卧", "A8": "硬卧",
        "A9": "商务座", "A10": "硬座", "A11": "硬座", "A12": "无座",
        "M": "一等座", "O": "二等座", "P": "特等座", "WZ": "无座",
    }

    def __init__(self) -> None:
        self.timeout = int(os.getenv("TRAVEL_API_TIMEOUT_SECONDS", "15"))
        self._stations: dict[str, str] = {}            # 站名 -> 电报码
        self._code_to_name: dict[str, str] = {}        # 电报码 -> 站名
        self._city_stations: dict[str, list[str]] = {}  # 城市名 -> [站名]
        self._opener = build_opener(HTTPCookieProcessor(_cookiejar.CookieJar()))
        self._opener._context = _SSL_CTX

    def _request(self, url: str, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> str:
        if params:
            url = f"{url}?{urlencode(params, doseq=True)}"
        hdrs = dict(_TRAIN_HEADERS)
        if headers:
            hdrs.update(headers)
        try:
            with self._opener.open(Request(url, headers=hdrs), timeout=self.timeout) as r:
                return r.read().decode("utf-8-sig", "replace")
        except HTTPError as exc:
            raise TrainApiError(f"12306 返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise TrainApiError(f"无法连接 12306：{exc}（需国内网络；若超时请重试）") from exc

    def _load_stations(self) -> None:
        if self._stations:
            return
        raw = self._request(self.STATION_URL)
        for entry in raw.split("@")[1:]:
            parts = entry.strip("';").split("|")
            if len(parts) >= 3 and parts[1] and parts[2]:
                name, code = parts[1], parts[2]
                self._stations[name] = code
                self._code_to_name[code] = name
                city = name[:-1] if name.endswith(("站", "东", "西", "南", "北")) else name
                self._city_stations.setdefault(city, []).append(name)
        if not self._stations:
            raise TrainApiError("12306 车站表拉取为空，请检查网络后重试。")

    def _resolve_station(self, place: str) -> str:
        """中文站名/城市名 -> 电报码；已是三字码则原样返回。"""
        self._load_stations()
        place = (place or "").strip()
        if len(place) == 3 and place.isalpha() and place.isupper():
            return place
        if place in self._stations:
            return self._stations[place]
        if place in self._city_stations and self._city_stations[place]:
            return self._stations[self._city_stations[place][0]]
        for name in self._stations:
            if place in name:
                return self._stations[name]
        raise TrainApiError(
            f"无法识别车站『{place}』；请使用具体站名（如『北京南』『上海虹桥』）或城市名。"
        )

    def search_trains(self, frm: str, to: str, date: str) -> list[dict[str, Any]]:
        """查询 12306 余票；遇「网络类」错误自动重试（风控/空结果不重试，直接报错）。"""
        retries = max(int(os.getenv("TRAVEL_API_RETRIES", "1")), 1)
        last_err: Exception | None = None
        for _ in range(retries + 1):
            try:
                self._request(self.INIT_URL)  # 先访问 init 拿 C_LEFT_TICKET cookie
                date = _normalize_date(date)
                from_code = self._resolve_station(frm)
                to_code = self._resolve_station(to)
                data = self._request(self.TICKET_URL, {
                    "leftTicketDTO.train_date": date,
                    "leftTicketDTO.from_station": from_code,
                    "leftTicketDTO.to_station": to_code,
                    "purpose_codes": "ADULT",
                })
                try:
                    j = json.loads(data)
                except json.JSONDecodeError:
                    snippet = data[:300].replace("\n", " ")
                    raise TrainApiError(
                        f"12306 返回了非预期数据（可能触发风控）。片段：{snippet!r}（请稍后重试或更换网络）"
                    )
                if j.get("status") is not True and j.get("httpstatus") != 200:
                    raise TrainApiError(f"12306 返回错误：{j.get('messages') or '未知错误'}")
                result = (j.get("data") or {}).get("result") or []
                if not result:
                    hint = ""
                    try:
                        from datetime import date as _d2, timedelta as _td2
                        if _d2.fromisoformat(date) > _d2.today() + _td2(days=15):
                            hint = f"（{date} 已超出 12306 预售期约 15 天，请改选更近的日期）"
                    except ValueError:
                        pass
                    raise TrainApiError(
                        f"12306 未返回『{frm}→{to} {date}』的车次{hint}；"
                        f"请检查出发/到达城市名，或稍后重试。"
                    )
                trains: list[dict[str, Any]] = []
                for s in result:
                    p = s.split("|")
                    if len(p) < 35:
                        continue
                    code = p[3]
                    ttype = code[:1] if code else ""
                    trains.append({
                        "train_no": code,
                        "train_type": {"G": "高铁", "D": "动车", "C": "城际", "K": "快速",
                                       "Z": "直达", "T": "特快", "Y": "旅游"}.get(ttype, ttype),
                        "from_station": self._code_to_name.get(p[6], p[6]),
                        "to_station": self._code_to_name.get(p[7], p[7]),
                        "depart_time": p[8],
                        "arrive_time": p[9],
                        "duration": p[10],
                        "seats": self._parse_seats(p, ttype),
                        "train_code": p[2] if len(p) > 2 else "",
                        "from_station_no": p[16] if len(p) > 16 else "",
                        "to_station_no": p[17] if len(p) > 17 else "",
                        "seat_types": p[35] if len(p) > 35 else "",
                        "train_date": date,
                        "price": None,
                        "currency": "CNY",
                        "source_note": "真实车次/余票/票价均来自12306官方接口",
                    })
                return trains
            except TrainApiError as exc:
                last_err = exc
                if "无法连接" in str(exc) or "HTTP" in str(exc):
                    continue  # 仅网络类错误值得重试
                raise  # 风控/空结果直接抛出
        raise last_err or TrainApiError("12306 查询失败（未知原因）")

    def search_with_prices(
        self, frm: str, to: str, date: str, preferred_seat: str = "二等座",
        max_trains: int = 10,
    ) -> list[dict[str, Any]]:
        """查询车次列表并为每班车补充真实票价（按席别）。

        返回每班车：train_no / 起止站 / 出发到达时间 / 历时 / seats(各席别余票+真实价) /
        min_price(可订席别最低价) / price(同 min_price，向后兼容)。
        票价接口失败的车次保留 price=None，由上层标注为「票价未返回」。
        """
        trains = self.search_trains(frm, to, date)
        # 只对前若干班车补票价（票价接口有频控，没必要查全部）
        for t in trains[:max_trains]:
            prices = self.get_prices(
                t["train_code"], t["from_station_no"], t["to_station_no"],
                t["seat_types"], date,
            )
            for s in t.get("seats", []):
                if s["type"] in prices:
                    s["price"] = prices[s["type"]]
            priced = [s["price"] for s in t.get("seats", [])
                      if s.get("price") is not None and s.get("remain") not in ("无", "", None)]
            t["min_price"] = min(priced) if priced else None
            t["price"] = t["min_price"]
        return trains

    @staticmethod
    def recommend_train(
        trains: list[dict[str, Any]], preferred_seat: str = "二等座"
    ) -> tuple[dict[str, Any] | None, str]:
        """从候选车次中挑「最合适」的一班并给出推荐理由。

        评分（越低越好）：
          1. 先避开凌晨出发或深夜到达的车次；
          2. 首选席别真实票价（未返回票价的车次排后）；
          3. 优先上午出发、下午前到达，再比较票价与历时。
        返回 (推荐车次 dict | None, 推荐理由 str)。
        """
        if not trains:
            return None, "12306 未返回可用车次。"
        pref = preferred_seat or "二等座"

        def _min_minutes(t) -> int:
            """历时 HH:MM -> 分钟；解析失败返回极大值。"""
            d = t.get("duration") or ""
            try:
                h, m = (int(x) for x in d.split(":")[:2])
                return h * 60 + m
            except (ValueError, AttributeError):
                return 10 ** 9

        def _pref_price(t) -> int | None:
            """首选席别的真实票价；无则取 min_price；都无返回 None。"""
            for s in t.get("seats", []):
                if s.get("type") == pref and s.get("price") is not None:
                    return int(s["price"])
            return t.get("min_price")

        def _hm_minutes(v: str) -> int | None:
            try:
                h, m = (int(x) for x in str(v).split(":")[:2])
                return h * 60 + m
            except (ValueError, AttributeError):
                return None

        def _time_score(dep: str, arr: str) -> int:
            d = _hm_minutes(dep)
            a = _hm_minutes(arr)
            s = 0
            if d is not None:
                if 8 * 60 <= d <= 10 * 60:
                    s -= 40  # 上午 8-10 点出发最合适
                elif d < 6 * 60 or d >= 22 * 60:
                    s += 60   # 太早/太晚减分
                elif d < 8 * 60:
                    s += 30
                elif d >= 18 * 60:
                    s += 20
            if a is not None:
                if a < 6 * 60 or a >= 23 * 60:
                    s += 60  # 凌晨/深夜到站，接驳通常不便
                elif a <= 15 * 60:
                    s -= 20  # 下午 3 点前到达加分
            return s

        def _unsocial_hours(t) -> int:
            """夜间时段不作为常规首选，但没有白天车次时仍允许兜底推荐。"""
            dep = _hm_minutes(t.get("depart_time"))
            arr = _hm_minutes(t.get("arrive_time"))
            return int(
                dep is not None and (dep < 6 * 60 or dep >= 22 * 60)
                or arr is not None and (arr < 6 * 60 or arr >= 23 * 60)
            )

        def _score(t) -> tuple:
            p = _pref_price(t)
            # 时间可行性优先于票价，避免便宜的凌晨班次压过正常白天车次。
            has_pref = 0 if any(
                s.get("type") == pref and s.get("price") is not None
                for s in t.get("seats", [])
            ) else 1
            price_key = (0, p) if p is not None else (1, 0)
            return (_unsocial_hours(t), has_pref,
                    _time_score(t.get("depart_time"), t.get("arrive_time")),
                    price_key, _min_minutes(t))

        best = min(trains, key=_score)
        p = _pref_price(best)
        price_txt = f"，{pref}{p}元" if p is not None else "，票价暂未返回"
        reasons = []
        dep_min = _hm_minutes(best.get("depart_time"))
        if dep_min is not None and 8 * 60 <= dep_min <= 10 * 60:
            reasons.append("上午出发时间合适")
        elif dep_min is not None and dep_min < 6 * 60:
            reasons.append("凌晨出发，建议提前确认交通接驳")
        elif dep_min is not None and dep_min >= 22 * 60:
            reasons.append("深夜出发，建议提前确认交通接驳")
        arr_min = _hm_minutes(best.get("arrive_time"))
        if arr_min is not None and (arr_min < 6 * 60 or arr_min >= 23 * 60):
            reasons.append("到站时段较晚或较早，建议确认接驳安排")
        if arr_min is not None and 6 * 60 <= arr_min <= 15 * 60:
            reasons.append("午后即可到达，方便安排当日行程")
        if best.get("duration"):
            reasons.append(f"全程约 {best['duration']}")
        reason = (f"推荐 {best.get('train_no')}（{best.get('depart_time')}→{best.get('arrive_time')}）"
                  f"{price_txt}。" + "；".join(reasons) + "。"
                  "实际以 12306 下单为准，余票随时变化。")
        return best, reason

    @staticmethod
    def _parse_seats(p: list[str], ttype: str) -> list[dict[str, Any]]:
        """从余票串里按实测索引解析各席别余票（有/无/具体数字）。"""
        idxs = dict(_SEAT_NAME_BY_INDEX)
        if ttype in ("G", "D", "C"):
            idxs.update(_HS_SEAT_NAME_BY_INDEX)
        seats: list[dict[str, Any]] = []
        for i, name in idxs.items():
            if i >= len(p):
                continue
            v = p[i]
            if v in ("", "--"):
                continue
            if v not in ("有", "无") and not v.isdigit():
                continue
            seats.append({"type": name, "remain": v, "price": None})
        return seats

    def get_prices(self, train_code: str, from_station_no: str, to_station_no: str,
                   seat_types: str, date: str) -> dict[str, float]:
        """查询某车次各席别真实票价（元）。失败返回空 dict（不抛错，由调用方决定是否标注）。"""
        if not (train_code and from_station_no and to_station_no):
            return {}
        try:
            data = self._request(self.PRICE_URL, {
                "train_no": train_code,
                "from_station_no": from_station_no,
                "to_station_no": to_station_no,
                "seat_types": seat_types or "O",
                "train_date": _normalize_date(date),
            }, headers={"Referer": "https://kyfw.12306.cn/otn/leftTicket/query"})
            j = json.loads(data)
            pricedata = j.get("data") if isinstance(j, dict) else None
            if not isinstance(pricedata, dict):
                return {}
            result: dict[str, float] = {}
            for key, raw in pricedata.items():
                if key == "train_no" or not isinstance(raw, str):
                    continue
                if not raw.startswith("¥"):
                    continue  # 跳过空值/非价格
                try:
                    # 12306 偶发返回半价/折扣价（带 .5），Pydantic TrainSeat.price 是 int 字段
                    # 直接 float 会触发 int_from_float 校验错误，把整次车次推荐都干掉。
                    # 在数据入口处一次性截断为整数，下游 int 链路保持稳定。
                    price = int(round(float(raw.lstrip("¥"))))
                except ValueError:
                    continue
                seat = self._PRICE_KEY_TO_SEAT.get(key)
                if seat and seat not in result:
                    result[seat] = price
            return result
        except (TrainApiError, json.JSONDecodeError, ValueError):
            return {}
