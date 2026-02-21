import logging
from datetime import datetime, timezone

import ccxt.async_support as ccxt

from src.collectors.base import BaseCollector
from src.models import MarketSnapshot

logger = logging.getLogger(__name__)


class PriceCollector(BaseCollector):
    """Collects OHLCV and ticker data from OKX via CCXT."""

    def __init__(self, exchange: ccxt.Exchange, pairs: tuple[str, ...]):
        self._exchange = exchange
        self._pairs = pairs

    async def collect(self) -> dict[str, MarketSnapshot]:
        """Collect current market snapshot for all pairs."""
        snapshots = {}
        for pair in self._pairs:
            try:
                ticker = await self._exchange.fetch_ticker(pair)
                snapshots[pair] = MarketSnapshot(
                    pair=pair,
                    price=ticker["last"],
                    bid=ticker.get("bid", ticker["last"]),
                    ask=ticker.get("ask", ticker["last"]),
                    volume_24h=ticker.get("quoteVolume", 0),
                    high_24h=ticker.get("high", ticker["last"]),
                    low_24h=ticker.get("low", ticker["last"]),
                    change_24h_pct=ticker.get("percentage", 0) or 0,
                    timestamp=datetime.now(tz=timezone.utc),
                )
            except Exception as e:
                logger.error("Price collection failed for %s: %s", pair, e)
        return snapshots

    async def fetch_ohlcv(self, pair: str, timeframe: str = "5m", limit: int = 100) -> list:
        """Fetch OHLCV candles for technical analysis."""
        try:
            return await self._exchange.fetch_ohlcv(pair, timeframe, limit=limit)
        except Exception as e:
            logger.error("OHLCV fetch failed for %s: %s", pair, e)
            return []

    async def health_check(self) -> bool:
        try:
            await self._exchange.fetch_ticker(self._pairs[0])
            return True
        except Exception:
            return False
