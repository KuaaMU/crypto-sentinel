import aiohttp
import logging
import ssl
from datetime import datetime, timezone

from src.collectors.base import BaseCollector
from src.models import FearGreedData

logger = logging.getLogger(__name__)


def _make_tcp_connector() -> aiohttp.TCPConnector:
    """Create a connector that skips SSL verification for environments with DNS/proxy issues."""
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ssl_ctx)


class FearGreedCollector(BaseCollector):
    """Collects Crypto Fear & Greed Index from alternative.me (free, no key needed)."""

    def __init__(self, url: str = "https://api.alternative.me/fng/"):
        self._url = url

    async def collect(self) -> FearGreedData | None:
        try:
            async with aiohttp.ClientSession(connector=_make_tcp_connector()) as session:
                async with session.get(self._url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning("Fear&Greed API returned status %d", resp.status)
                        return None
                    data = await resp.json()

            entry = data["data"][0]
            return FearGreedData(
                value=int(entry["value"]),
                classification=entry["value_classification"],
                timestamp=datetime.fromtimestamp(int(entry["timestamp"]), tz=timezone.utc),
            )
        except Exception as e:
            logger.error("Fear&Greed collection failed: %s", e)
            return None

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession(connector=_make_tcp_connector()) as session:
                async with session.get(self._url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False
