from backend.mcp_tools import tools
from backend.models.trip import Location, WeatherInfo


def test_mcp_poi_tool_preserves_source_id(monkeypatch):
    monkeypatch.setattr(tools, "text_search", lambda keywords, city: [{
        "source_id": "amap-1", "name": "中山陵",
        "location": Location(longitude=118.85, latitude=32.06, address="南京"),
        "opening_hours": "08:30-17:00",
    }])
    result = tools.search_pois("南京", "景点")
    assert result == [{
        "source_id": "amap-1", "name": "中山陵", "longitude": 118.85,
        "latitude": 32.06, "address": "南京", "opening_hours": "08:30-17:00",
        "provider": "amap",
    }]


def test_mcp_weather_tool_reuses_existing_provider(monkeypatch):
    monkeypatch.setattr(
        tools, "weather",
        lambda city, days: [WeatherInfo(date="2026-10-01", temperature=20, condition="晴")],
    )
    assert tools.weather_forecast("南京", 99)[0]["condition"] == "晴"

