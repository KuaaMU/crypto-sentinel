"""Historical OHLCV data fetching with caching via CCXT."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import ccxt.async_support as ccxt

logger = logging.getLogger(__name__)

# Timeframe to milliseconds mapping
TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

_BATCH_LIMIT = 1000
_RATE_LIMIT_SECONDS = 0.5


def _iso_to_ms(date_str: str) -> int:
    """Convert ISO date string (e.g. '2025-01-01') to UTC millisecond timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _validate_timeframe(timeframe: str) -> int:
    """Return milliseconds for the given timeframe or raise ValueError."""
    if timeframe not in TIMEFRAME_MS:
        supported = ", ".join(sorted(TIMEFRAME_MS.keys()))
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {supported}")
    return TIMEFRAME_MS[timeframe]


class HistoricalDataFeed:
    """Fetch and cache historical OHLCV data from exchange."""

    def __init__(self, exchange: ccxt.Exchange) -> None:
        self._exchange = exchange

    async def fetch_ohlcv(
        self,
        pair: str,
        timeframe: str,
        start_date: str,  # ISO format "2025-01-01"
        end_date: str,    # ISO format "2025-01-31"
    ) -> list[list]:
        """Fetch OHLCV data with pagination.

        Returns: [[timestamp, open, high, low, close, volume], ...]
        """
        timeframe_ms = _validate_timeframe(timeframe)
        start_ms = _iso_to_ms(start_date)
        end_ms = _iso_to_ms(end_date)

        if start_ms >= end_ms:
            raise ValueError(f"start_date ({start_date}) must be before end_date ({end_date})")

        all_candles: list[list] = []
        since = start_ms

        logger.info("Fetching %s %s OHLCV from %s to %s", pair, timeframe, start_date, end_date)

        while since < end_ms:
            try:
                batch = await self._exchange.fetch_ohlcv(
                    pair, timeframe, since=since, limit=_BATCH_LIMIT,
                )
            except ccxt.BaseError as exc:
                logger.error("Exchange error fetching %s %s (since=%d): %s", pair, timeframe, since, exc)
                raise

            if not batch:
                logger.debug("No more data returned, stopping pagination")
                break

            all_candles.extend(batch)

            last_timestamp = batch[-1][0]
            since = last_timestamp + timeframe_ms

            logger.debug("Fetched %d candles, total: %d", len(batch), len(all_candles))

            if since < end_ms:
                await asyncio.sleep(_RATE_LIMIT_SECONDS)

        # Filter to requested date range
        filtered = [c for c in all_candles if start_ms <= c[0] < end_ms]

        # Sort by timestamp and deduplicate
        seen: set[int] = set()
        unique: list[list] = []
        for candle in sorted(filtered, key=lambda c: c[0]):
            if candle[0] not in seen:
                seen.add(candle[0])
                unique.append(candle)

        logger.info("Fetched %d unique candles for %s %s", len(unique), pair, timeframe)
        return unique

    async def fetch_ohlcv_cached(
        self,
        pair: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        db_save_fn: Optional[Callable] = None,  # async fn to save to ohlcv_cache
        db_load_fn: Optional[Callable] = None,   # async fn to load from ohlcv_cache
    ) -> list[list]:
        """Fetch with database caching. Try loading from cache first.

        Args:
            db_save_fn: async callable(pair, timeframe, start_date, end_date, data)
            db_load_fn: async callable(pair, timeframe, start_date, end_date) -> list
        """
        # Try cache load
        if db_load_fn is not None:
            try:
                cached = await db_load_fn(pair, timeframe, start_date, end_date)
                if cached and len(cached) > 0:
                    logger.info("Cache hit: %d candles for %s %s", len(cached), pair, timeframe)
                    return cached
            except Exception as exc:
                logger.warning("Cache load failed, falling back to exchange: %s", exc)

        logger.info("Cache miss for %s %s, fetching from exchange", pair, timeframe)

        # Fetch from exchange
        data = await self.fetch_ohlcv(pair, timeframe, start_date, end_date)

        # Persist to cache
        if db_save_fn is not None and data:
            try:
                await db_save_fn(pair, timeframe, start_date, end_date, data)
                logger.info("Cached %d candles for %s %s", len(data), pair, timeframe)
            except Exception as exc:
                logger.warning("Cache save failed: %s", exc)

        return data
