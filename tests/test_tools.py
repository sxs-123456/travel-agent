"""高德工具层与图片/车票服务的真实路径测试（使用 monkeypatch 模拟 HTTP）。"""
import httpx

from backend.tools.amap import (
    _parse_pois,
    _parse_weather,
    text_search,
    weather,
    driving_route,
)
from backend.tools.images import search_image
from backend.rail_client import RailClient
from backend.tools.train import TrainTicketProvider, _normalize_date
from backend.models.trip import Attraction, DayPlan, Location, WeatherInfo
from backend.config import settings
import backend.tools.restaurants as restaurant_module


# ---------------------------------------------------------------------------
# 真实解析逻辑（纯函数，无需网络）
# ---------------------------------------------------------------------------
def test_parse_pois_real():
    data = {
        "status": "1",
        "pois": [
            {"id": "B000A001", "name": "天安门", "location": "116.39,39.90", "address": "东城",
             "type": "风景名胜", "biz_ext": {"cost": "50"}},
        ],
    }
    out = _parse_pois(data)
    assert out[0]["name"] == "天安门"
    assert out[0]["source_id"] == "B000A001"
    assert out[0]["location"].longitude == 116.39
    assert out[0]["ticket_price"] == 50


def test_amap_driving_route_parses_distance_and_duration(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "1",
                "route": {"paths": [{"distance": "12500", "duration": "1800"}]},
            }

    monkeypatch.setattr(settings, "amap_api_key", "test-key")
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: FakeResp())
    result = driving_route(
        Location(longitude=116.3, latitude=39.9),
        Location(longitude=116.4, latitude=40.0),
    )
    assert result == {
        "distance_km": 12.5, "duration_min": 30.0, "source": "amap_driving"
    }


def test_restaurant_recommender_returns_real_nearby_poi(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "1",
                "pois": [{
                    "id": "food-1",
                    "name": "测试餐厅",
                    "location": "120.11,30.21",
                    "address": "测试路 1 号",
                    "type": "餐饮服务;中餐厅;地方菜",
                    "biz_ext": {"cost": "88"},
                }],
            }

    monkeypatch.setattr(settings, "amap_api_key", "test-key")
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: FakeResp())
    restaurant_module._search_near.cache_clear()
    days = [DayPlan(
        day=1,
        date="2026-10-01",
        attractions=[Attraction(
            name="西湖", location=Location(longitude=120.1, latitude=30.2)
        )],
    )]
    result = restaurant_module.recommend_restaurants(days)
    assert result[1].source_id == "food-1"
    assert result[1].name == "测试餐厅"
    assert result[1].price == 88
    assert result[1].location is not None
    assert result[1].price_is_estimated is False


# ---------------------------------------------------------------------------
# 12306 直连火车票（真实票价，免 key 免 npx）
# ---------------------------------------------------------------------------
def test_rail_available_depends_on_setting(monkeypatch):
    """直连 12306 无需 npx：available() 只取决于 USE_RAIL_MCP 开关。"""
    monkeypatch.setattr(settings, "use_rail_mcp", True)
    assert RailClient().available() is True
    monkeypatch.setattr(settings, "use_rail_mcp", False)
    assert RailClient().available() is False


def test_train_normalize_date():
    assert _normalize_date("2026-10-01") == "2026-10-01"
    assert _normalize_date("10/1", default_year=2026) == "2026-10-01"


def test_train_parse_seats():
    p = ["x"] * 36
    p[31] = "有"   # 一等座
    p[32] = "20"   # 二等座
    p[29] = "--"   # 硬座（空值应被跳过）
    seats = TrainTicketProvider._parse_seats(p, "G")
    types = {s["type"]: s["remain"] for s in seats}
    assert types["一等座"] == "有"
    assert types["二等座"] == "20"
    assert "硬座" not in types


def test_train_get_prices(monkeypatch):
    """queryTicketPrice 返回的 ¥ 价格应被正确解析为 {席别: 价格}。"""
    prov = TrainTicketProvider()
    monkeypatch.setattr(
        prov, "_request",
        lambda url, *a, **kw: '{"data": {"train_no": "24000G10300", "A4": "¥969", "O": "¥576", "OT": []}}',
    )
    prices = prov.get_prices("24000G10300", "01", "10", "O", "2026-10-01")
    assert prices["二等座"] == 576.0
    assert prices["一等座"] == 969.0


def test_train_get_prices_rounds_half_fare(monkeypatch):
    """12306 偶发返回半价/折扣价（带 .5/.6 等小数），必须截断为整数；
    否则下游 TrainSeat.price (int) 会触发 Pydantic int_from_float 校验错误，
    把整次车次推荐流程都干掉（实际线上 bug）。"""
    prov = TrainTicketProvider()
    monkeypatch.setattr(
        prov, "_request",
        lambda url, *a, **kw: '{"data": {"train_no": "x", "A4": "¥969.6", "O": "¥273.5"}}',
    )
    prices = prov.get_prices("x", "01", "10", "O", "2026-10-01")
    # Python int(round(.5)) 用银行家舍入到偶数：273.5->274, 969.6->970
    assert prices["二等座"] == 274
    assert prices["一等座"] == 970
    assert isinstance(prices["二等座"], int)


def test_parse_weather_real_multi_day():
    data = {
        "status": "1",
        "forecasts": [{"city": "北京", "casts": [
            {"date": "2026-10-01", "dayweather": "晴", "daytemp": "26"},
            {"date": "2026-10-02", "dayweather": "多云", "daytemp": "24"},
        ]}],
    }
    out = _parse_weather(data, 3)
    assert len(out) == 2
    assert out[0].condition == "晴"
    assert out[0].temperature == 26


# ---------------------------------------------------------------------------
# 真实 HTTP 分支（mock 掉网络层，验证真实解析被正确调用）
# ---------------------------------------------------------------------------
def test_text_search_real_branch(monkeypatch):
    monkeypatch.setattr(settings, "amap_api_key", "test-key")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "1", "pois": [
                {"name": "真实景点", "location": "120.0,30.0", "address": "x",
                 "type": "t", "biz_ext": {"cost": "0"}},
            ]}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
    res = text_search("景点", "杭州")
    assert res[0]["name"] == "真实景点"
    assert res[0]["location"].latitude == 30.0


def test_weather_real_branch(monkeypatch):
    monkeypatch.setattr(settings, "amap_api_key", "test-key")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "1", "forecasts": [{"city": "杭州", "casts": [
                {"date": "2026-10-01", "dayweather": "晴", "daytemp": "25"},
            ]}]}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
    out = weather("杭州", 2)
    assert out[0].condition == "晴"


# ---------------------------------------------------------------------------
# 异常路径：缺失 key 应抛出清晰错误（不再静默降级到演示数据）
# ---------------------------------------------------------------------------
def test_text_search_missing_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "amap_api_key", "")
    try:
        text_search("景点", "北京")
        assert False, "应当因缺失 AMAP_API_KEY 而抛出异常"
    except RuntimeError as e:
        assert "AMAP_API_KEY" in str(e)


# ---------------------------------------------------------------------------
# 图片服务：Pexels（有 key 首选）→ Openverse（免 key 兜底）→ None
# ---------------------------------------------------------------------------
def test_search_image_pexels_first(monkeypatch):
    """配置 PEXELS_API_KEY 时，Pexels 作为首选返回真实照片直链。"""
    monkeypatch.setattr(settings, "pexels_api_key", "test-pexels-key")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"photos": [{"src": {
                "large": "https://images.pexels.com/photos/1/photo.jpeg?auto=compress",
            }}]}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
    assert search_image("故宫") == "https://images.pexels.com/photos/1/photo.jpeg?auto=compress"


def test_search_image_pexels_no_key_falls_to_openverse(monkeypatch):
    """未配 PEXELS_API_KEY 时跳过 Pexels，自动落到 Openverse 兜底。"""
    monkeypatch.setattr(settings, "pexels_api_key", "")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [
                {"title": "故宫", "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/b/Forbidden_City.jpg"},
            ]}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
    assert search_image("故宫") == "https://upload.wikimedia.org/wikipedia/commons/thumb/a/b/Forbidden_City.jpg"


def test_search_image_openverse_429_returns_none(monkeypatch):
    """Openverse 匿名限流（429）时已无兜底源，返回 None（不报错、不假图）。"""
    monkeypatch.setattr(settings, "pexels_api_key", "")

    class RateLimitedResp:
        status_code = 429

        def raise_for_status(self):
            raise httpx.HTTPStatusError("429", request=None, response=None)

        def json(self):
            return {}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: RateLimitedResp())
    assert search_image("故宫") is None


def test_search_image_filters_non_photo(monkeypatch):
    """结果里的 SVG/地图等非照片文件应被跳过，取后续真实照片。"""
    monkeypatch.setattr(settings, "pexels_api_key", "")

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [
                {"title": "地图", "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/b/locator_map.svg"},
                {"title": "实景", "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/b/Real_Spot_photo.jpg"},
            ]}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: Resp())
    assert search_image("某景点") == "https://upload.wikimedia.org/wikipedia/commons/thumb/a/b/Real_Spot_photo.jpg"


def test_search_image_all_sources_fail_returns_none(monkeypatch):
    """全部来源失败/无结果 → None（绝不返回假图）。"""
    monkeypatch.setattr(settings, "pexels_api_key", "")

    class EmptyResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": []}  # Openverse 无结果

    monkeypatch.setattr(httpx, "get", lambda url, **kw: EmptyResp())
    assert search_image("不存在的地方xyz") is None


# ---------------------------------------------------------------------------
# WeatherInfo 温度校验（兼容 LLM 偶发的小数 / 带单位字符串）
# ---------------------------------------------------------------------------
def test_weatherinfo_temperature_decimal():
    assert WeatherInfo(date="2026-10-01", condition="晴", temperature="23.5").temperature == 23
    assert WeatherInfo(date="2026-10-01", condition="晴", temperature=23.5).temperature == 23
    assert WeatherInfo(date="2026-10-01", condition="晴", temperature="26℃").temperature == 26
    assert WeatherInfo(date="2026-10-01", condition="晴", temperature="").temperature == 0


# ---------------------------------------------------------------------------
# 打车估算（百度驾车路线规划 → 参考价）
# ---------------------------------------------------------------------------
def test_taxi_estimate_fare():
    from backend.tools.taxi import estimate_fare

    r = estimate_fare("A", "B", 10000, 1200)  # 10 km, 20 min
    # 14 起步 + (10-3)*2.6 里程 + 20*0.5 等候 = 42.2
    assert r["distance_km"] == 10.0
    assert r["duration_min"] == 20.0
    assert r["estimated_fare"] == 42.2


def test_taxi_ride_by_coords(monkeypatch):
    from backend.tools.taxi import BaiduRideProvider

    monkeypatch.setattr(settings, "baidu_map_ak", "test-ak")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"status": 0, "result": {"routes": [{"distance": 10000, "duration": 1200}]}}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
    r = BaiduRideProvider().estimate_ride_by_coords(30.2, 120.1, 30.3, 120.2)
    assert r["estimated_fare"] == 42.2


def test_taxi_missing_key_raises(monkeypatch):
    from backend.tools.taxi import BaiduRideProvider, TaxiApiError

    monkeypatch.setattr(settings, "baidu_map_ak", "")
    try:
        BaiduRideProvider().estimate_ride_by_coords(30, 120, 31, 121)
        assert False, "缺失 BAIDU_MAP_AK 应抛出 TaxiApiError"
    except TaxiApiError as e:
        assert "BAIDU_MAP_AK" in str(e)


# ---------------------------------------------------------------------------
# 车次选择推荐（12306 真实数据 → 哪班车合适）
# ---------------------------------------------------------------------------
def test_recommend_train_picks_best_by_price_and_time():
    """推荐逻辑：有真实票价的车次优先，其次考虑出发时间/耗时。"""
    trains = [
        {"train_no": "G1", "depart_time": "09:00", "arrive_time": "13:30", "duration": "04:30",
         "seats": [{"type": "二等座", "remain": "有", "price": 598},
                   {"type": "一等座", "remain": "有", "price": 1006}], "min_price": 598},
        {"train_no": "G3", "depart_time": "07:00", "arrive_time": "11:00", "duration": "04:00",
         "seats": [{"type": "二等座", "remain": "有", "price": 700},
                   {"type": "一等座", "remain": "无", "price": None}], "min_price": 700},
        {"train_no": "G5", "depart_time": "18:00", "arrive_time": "22:30", "duration": "04:30",
         "seats": [{"type": "二等座", "remain": "无", "price": None}], "min_price": None},
    ]
    best, reason = TrainTicketProvider.recommend_train(trains, "二等座")
    assert best["train_no"] == "G1"  # 有价 + 上午出发 → 综合最优
    assert "G1" in reason


def test_recommend_train_prefers_preferred_seat_price():
    """首选席别有价时用其价格参与评分；无票价车次永远排最后。"""
    trains = [
        {"train_no": "D1", "depart_time": "10:00", "arrive_time": "14:00", "duration": "04:00",
         "seats": [{"type": "一等座", "remain": "有", "price": 880}], "min_price": 880},
        {"train_no": "D2", "depart_time": "09:00", "arrive_time": "13:00", "duration": "04:00",
         "seats": [{"type": "二等座", "remain": "有", "price": 550}], "min_price": 550},
        {"train_no": "D3", "depart_time": "08:00", "arrive_time": "12:00", "duration": "04:00",
         "seats": [{"type": "二等座", "remain": "有", "price": None}], "min_price": None},
    ]
    best, _ = TrainTicketProvider.recommend_train(trains, "一等座")
    assert best["train_no"] == "D1"  # 首选席别一等座有价 → 优先
    best2, _ = TrainTicketProvider.recommend_train(trains, "二等座")
    assert best2["train_no"] == "D2"
    assert best2["train_no"] != "D3"  # 无票价车次不会被推荐


def test_recommend_train_does_not_choose_overnight_departure_for_lower_fare():
    """普通白天班次应优先于凌晨班次，即使凌晨票价更低。"""
    trains = [
        {"train_no": "G4944", "depart_time": "01:22", "arrive_time": "02:29", "duration": "01:07",
         "seats": [{"type": "二等座", "price": 141}], "min_price": 141},
        {"train_no": "G100", "depart_time": "08:00", "arrive_time": "09:15", "duration": "01:15",
         "seats": [{"type": "二等座", "price": 220}], "min_price": 220},
    ]

    best, _ = TrainTicketProvider.recommend_train(trains, "二等座")

    assert best["train_no"] == "G100"

    overnight, overnight_reason = TrainTicketProvider.recommend_train(trains[:1], "二等座")
    assert overnight["train_no"] == "G4944"  # 没有白天车次时仍给出可用兜底
    assert "凌晨出发" in overnight_reason
    assert "午后即可到达" not in overnight_reason


def test_rail_recommendation_models():
    """TrainRecommendation / TrainOption / TrainSeat 模型可被 pydantic 正确序列化。"""
    from backend.models.trip import TrainOption, TrainRecommendation, TrainSeat

    seat = TrainSeat(type="二等座", remain="有", price=598)
    opt = TrainOption(
        train_no="G1", train_type="高铁", from_station="北京南", to_station="上海虹桥",
        depart_time="09:00", arrive_time="13:30", duration="04:30",
        seats=[seat], min_price=598,
    )
    rec = TrainRecommendation(
        direction="去程：北京→上海", date="2026-10-01",
        recommended=opt, reason="推荐 G1", candidates=[opt], price_per_person=598,
    )
    d = rec.model_dump()
    assert d["direction"] == "去程：北京→上海"
    assert d["recommended"]["train_no"] == "G1"
    assert d["candidates"][0]["seats"][0]["price"] == 598
    assert d["price_per_person"] == 598


def test_hotel_estimate_price_by_level_and_city():
    """酒店参考估算：按档次基准 × 城市系数（与旧项目口径一致）。"""
    from backend.tools.amap import estimate_hotel_price

    # 北京（系数 1.3）× 经济型（180）≈ 230（round 到 10）
    assert estimate_hotel_price("经济型", None, "北京") == 230
    # 评分档位兜底：4.7 分以上 ≈ 360 × 杭州系数(1.1) → 400
    assert estimate_hotel_price(None, 4.8, "杭州") == 400
    # 未知档次 + 无评分 → None
    assert estimate_hotel_price("未知类型", None, "北京") is None


# ---------------------------------------------------------------------------
# 门票价格 + 词条首图：百度百科词条卡片 API（免费、免 key、真实）
# ---------------------------------------------------------------------------
def test_ticket_query_real_branch(monkeypatch):
    """百度百科卡片 API 返回「门票价格」→ 解析出价格与说明。"""
    from backend.tools.ticket import query_baike_card

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "card": [
                    {"name": "开放时间", "value": ["08:30-17:00"]},
                    {"name": "门票价格", "value": ["60元旺季/40元淡季<sup>4</sup><a name=\"ref_4\"></a>"]},
                ],
            }

    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
    price, note = query_baike_card("故宫")
    assert price == 60
    assert note == "60元旺季/40元淡季"  # HTML 标签已清理


def test_ticket_query_no_field_returns_none(monkeypatch):
    """词条无「门票价格」字段 → 各值 None，绝不臆造价格。"""
    from backend.tools.ticket import query_baike_card

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"card": [{"name": "简介", "value": ["历史建筑"]}]}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
    assert query_baike_card("某小众景点") == (None, None)


def test_ticket_query_failure_returns_none(monkeypatch):
    """接口异常 → (None, None)，不抛错、不拖垮行程。"""
    from backend.tools.ticket import query_baike_card

    def boom(url, **kw):
        raise httpx.ConnectError("网络错误")

    monkeypatch.setattr(httpx, "get", boom)
    assert query_baike_card("故宫") == (None, None)


def test_ticket_parse_price_variants():
    """价格解析兼容多种写法：纯数字元、区间、小数。"""
    from backend.tools.ticket import _parse_price

    assert _parse_price("60元旺季/40元淡季") == 60   # 取第一个价格（旺季常规价）
    assert _parse_price("免费") is None
    assert _parse_price("门票 30.5元") == 30
    assert _parse_price("无价格信息") is None
