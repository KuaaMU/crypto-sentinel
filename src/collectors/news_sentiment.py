import aiohttp
import logging
import ssl
from datetime import datetime, timezone

from src.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


def _make_connector() -> aiohttp.TCPConnector:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ctx)


class NewsSentimentCollector(BaseCollector):
    """Collects crypto news sentiment. Uses CoinGecko trending + simple heuristics."""

    def __init__(self, coingecko_base: str, news_api_key: str = ""):
        self._coingecko_base = coingecko_base
        self._news_api_key = news_api_key

    async def collect(self) -> dict:
        try:
            trending = await self._fetch_trending()
            market_data = await self._fetch_global_market()

            btc_dominance = market_data.get("btc_dominance", 50)
            market_cap_change = market_data.get("market_cap_change_24h", 0)
            volume_change = market_data.get("volume_change_24h", 0)

            momentum_score = 50
            momentum_score += min(max(market_cap_change * 5, -25), 25)
            momentum_score += min(max(volume_change * 2, -15), 15)

            trending_count = len(trending)
            if trending_count > 5:
                momentum_score += 5

            sentiment_score = max(0, min(100, momentum_score))

            return {
                "sentiment_score": sentiment_score,
                "market_cap_change_24h": market_cap_change,
                "volume_change_24h": volume_change,
                "btc_dominance": btc_dominance,
                "trending_count": trending_count,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error("News sentiment collection failed: %s", e)
            return {"sentiment_score": 50, "error": str(e)}

    async def _fetch_trending(self) -> list:
        url = f"{self._coingecko_base}/search/trending"
        try:
            async with aiohttp.ClientSession(connector=_make_connector()) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return data.get("coins", [])
        except Exception:
            return []

    async def _fetch_global_market(self) -> dict:
        url = f"{self._coingecko_base}/global"
        try:
            async with aiohttp.ClientSession(connector=_make_connector()) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return {}
                    data = await resp.json()
                    gd = data.get("data", {})
                    return {
                        "btc_dominance": gd.get("market_cap_percentage", {}).get("btc", 50),
                        "market_cap_change_24h": gd.get("market_cap_change_percentage_24h_usd", 0),
                        "volume_change_24h": 0,
                    }
        except Exception:
            return {}

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession(connector=_make_connector()) as session:
                url = f"{self._coingecko_base}/ping"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False
