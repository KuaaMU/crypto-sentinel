import logging

import ccxt.async_support as ccxt

from src.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class OrderbookCollector(BaseCollector):
    """Collects order book depth from OKX to detect buy/sell imbalance."""

    def __init__(self, exchange: ccxt.Exchange, pairs: tuple[str, ...]):
        self._exchange = exchange
        self._pairs = pairs

    async def collect(self) -> dict[str, dict]:
        """Collect orderbook imbalance data for all pairs.

        Returns dict[pair] -> {
            'bid_volume': total bid volume (top 20 levels),
            'ask_volume': total ask volume (top 20 levels),
            'imbalance': (bid - ask) / (bid + ask),  # -1 to +1
            'spread_pct': (ask - bid) / mid_price * 100,
        }
        """
        results = {}
        for pair in self._pairs:
            try:
                book = await self._exchange.fetch_order_book(pair, limit=20)
                bids = book.get("bids", [])
                asks = book.get("asks", [])

                bid_volume = sum(b[1] for b in bids) if bids else 0
                ask_volume = sum(a[1] for a in asks) if asks else 0
                total = bid_volume + ask_volume

                best_bid = bids[0][0] if bids else 0
                best_ask = asks[0][0] if asks else 0
                mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else 1

                results[pair] = {
                    "bid_volume": bid_volume,
                    "ask_volume": ask_volume,
                    "imbalance": (bid_volume - ask_volume) / total if total > 0 else 0,
                    "spread_pct": (best_ask - best_bid) / mid_price * 100 if mid_price > 0 else 0,
                }
            except Exception as e:
                logger.error("Orderbook collection failed for %s: %s", pair, e)
                results[pair] = {"bid_volume": 0, "ask_volume": 0, "imbalance": 0, "spread_pct": 0}
        return results

    async def health_check(self) -> bool:
        try:
            await self._exchange.fetch_order_book(self._pairs[0], limit=5)
            return True
        except Exception:
            return False
