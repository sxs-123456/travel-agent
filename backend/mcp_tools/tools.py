"""Plain Python functions exposed through MCP and directly testable without transport."""
from __future__ import annotations

from backend.tools.amap import text_search, weather


def search_pois(city: str, keywords: str, limit: int = 10) -> list[dict]:
    """Return grounded POIs. Every item keeps the provider source ID."""
    safe_limit = max(1, min(limit, 20))
    return [
        {
            "source_id": item.get("source_id"),
            "name": item.get("name"),
            "longitude": item["location"].longitude,
            "latitude": item["location"].latitude,
            "address": item["location"].address,
            "opening_hours": item.get("opening_hours"),
            "provider": "amap",
        }
        for item in text_search(keywords.strip(), city.strip())[:safe_limit]
    ]


def weather_forecast(city: str, days: int = 4) -> list[dict]:
    """Return the existing AMap forecast through a transport-neutral contract."""
    return [item.model_dump() for item in weather(city.strip(), max(1, min(days, 4)))]

