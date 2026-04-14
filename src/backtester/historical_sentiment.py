"""
Historical sentiment data provider for backtesting.

Fetches Fear & Greed Index history from Alternative.me API,
enabling realistic sentiment scoring in backtests instead of
neutral defaults.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from src.models import FearGreedData

logger = logging.getLogger(__name__)

_FNG_API = "https://api.alternative.me/fng/"


def fetch_historical_fear_greed(
    days: int = 365,
    proxy: str = "",
) -> dict[str, FearGreedData]:
    """Fetch historical Fear & Greed data keyed by date string.

    Returns:
        {"2025-12-01": FearGreedData(...), "2025-12-02": ...}
    """
    proxies = {"https": proxy, "http": proxy} if proxy else {}

    try:
        response = requests.get(
            _FNG_API,
            params={"limit": days, "format": "json"},
            proxies=proxies,
            timeout=15,
        )
        response.raise_for_status()
        raw_data = response.json().get("data", [])
    except Exception as exc:
        logger.error("Failed to fetch historical F&G: %s", exc)
        return {}

    result: dict[str, FearGreedData] = {}
    for entry in raw_data:
        ts = int(entry["timestamp"])
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        date_key = dt.strftime("%Y-%m-%d")
        result[date_key] = FearGreedData(
            value=int(entry["value"]),
            classification=entry["value_classification"],
            timestamp=dt,
        )

    logger.info("Loaded %d days of historical Fear & Greed data", len(result))
    return result


def get_fg_for_timestamp(
    fg_history: dict[str, FearGreedData],
    timestamp: datetime,
) -> Optional[FearGreedData]:
    """Look up Fear & Greed data for a given timestamp.

    F&G is published daily, so we look up by date.
    """
    date_key = timestamp.strftime("%Y-%m-%d")
    return fg_history.get(date_key)
