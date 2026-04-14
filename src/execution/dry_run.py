"""
Dry-Run Exchange Wrapper.

Connects to real exchange for market data (prices, OHLCV, orderbooks),
but simulates all order execution locally. Zero risk, real data.
"""
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DryRunExchange:
    """Wraps a real CCXT exchange; passes through reads, simulates writes."""

    def __init__(self, exchange, initial_balance: float = 10000.0):
        self._exchange = exchange
        self._initial_balance = initial_balance
        self._free_balance = initial_balance
        self._used_margin = 0.0
        self._realized_pnl = 0.0
        self._order_counter = 0
        self._open_margins: dict[str, float] = {}  # symbol -> margin locked

        # Forward exchange attributes
        self.markets = exchange.markets
        self.id = exchange.id

        logger.info(
            "DRY-RUN mode active | Virtual balance: $%.2f | Real market data from %s",
            initial_balance, exchange.id,
        )

    # ------------------------------------------------------------------
    # Market data: pass through to real exchange
    # ------------------------------------------------------------------

    async def fetch_ticker(self, symbol, params=None):
        return await self._exchange.fetch_ticker(symbol, params or {})

    async def fetch_ohlcv(self, symbol, timeframe="5m", since=None, limit=None, params=None):
        return await self._exchange.fetch_ohlcv(
            symbol, timeframe, since=since, limit=limit, params=params or {},
        )

    async def fetch_order_book(self, symbol, limit=None, params=None):
        return await self._exchange.fetch_order_book(symbol, limit=limit, params=params or {})

    async def load_markets(self, reload=False):
        result = await self._exchange.load_markets(reload)
        self.markets = self._exchange.markets
        return result

    def market(self, symbol):
        return self._exchange.market(symbol)

    # ------------------------------------------------------------------
    # Account: virtual balance
    # ------------------------------------------------------------------

    async def fetch_balance(self, params=None):
        total = self._free_balance + self._used_margin
        return {
            "USDT": {
                "free": self._free_balance,
                "used": self._used_margin,
                "total": total,
            },
            "free": {"USDT": self._free_balance},
            "used": {"USDT": self._used_margin},
            "total": {"USDT": total},
        }

    # ------------------------------------------------------------------
    # Trading: simulate locally
    # ------------------------------------------------------------------

    async def set_leverage(self, leverage, symbol, params=None):
        logger.debug("DRY-RUN: set_leverage(%d, %s) - simulated", leverage, symbol)

    async def set_position_mode(self, hedged, symbol, params=None):
        logger.debug("DRY-RUN: set_position_mode(%s, %s) - simulated", hedged, symbol)

    async def create_order(
        self, symbol, type, side, amount, price=None, params=None,
    ):
        """Simulate order fill at current market price."""
        params = params or {}
        is_reduce = params.get("reduceOnly", False)

        # Get current market price
        ticker = await self._exchange.fetch_ticker(symbol)
        fill_price = ticker.get("last", 0)

        # Use bid/ask for more realistic simulation
        if side == "buy":
            fill_price = ticker.get("ask", fill_price) or fill_price
        else:
            fill_price = ticker.get("bid", fill_price) or fill_price

        cost = amount * fill_price
        self._order_counter += 1
        order_id = f"dry-{self._order_counter:06d}"

        if is_reduce:
            # Closing position: release margin, apply PnL
            released = self._open_margins.pop(symbol, 0)
            self._used_margin -= released
            self._free_balance += released
            logger.info(
                "DRY-RUN CLOSE %s %s: %.6f @ $%.2f (margin released: $%.2f)",
                side.upper(), symbol, amount, fill_price, released,
            )
        else:
            # Opening position: lock margin
            # Margin = cost / leverage (approximate, since we don't know leverage here)
            # Use full cost as conservative margin estimate
            margin = cost
            self._open_margins[symbol] = margin
            self._used_margin += margin
            self._free_balance -= margin
            logger.info(
                "DRY-RUN OPEN %s %s: %.6f @ $%.2f (margin locked: $%.2f)",
                side.upper(), symbol, amount, fill_price, margin,
            )

        logger.info(
            "DRY-RUN balance: free=$%.2f used=$%.2f total=$%.2f",
            self._free_balance, self._used_margin,
            self._free_balance + self._used_margin,
        )

        return {
            "id": order_id,
            "clientOrderId": order_id,
            "symbol": symbol,
            "type": type,
            "side": side,
            "amount": amount,
            "filled": amount,
            "remaining": 0,
            "average": fill_price,
            "price": fill_price,
            "cost": cost,
            "status": "closed",
            "timestamp": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
            "datetime": datetime.now(tz=timezone.utc).isoformat(),
            "info": {"dry_run": True},
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self):
        total = self._free_balance + self._used_margin
        pnl = total - self._initial_balance
        logger.info(
            "DRY-RUN session ended | Start: $%.2f | Final: $%.2f | PnL: $%.2f (%.2f%%)",
            self._initial_balance, total, pnl,
            (pnl / self._initial_balance * 100) if self._initial_balance > 0 else 0,
        )
        await self._exchange.close()

    @property
    def summary(self) -> dict:
        """Return dry-run session summary."""
        total = self._free_balance + self._used_margin
        return {
            "initial_balance": self._initial_balance,
            "final_balance": total,
            "free_balance": self._free_balance,
            "used_margin": self._used_margin,
            "pnl": total - self._initial_balance,
            "pnl_pct": (total - self._initial_balance) / self._initial_balance * 100
            if self._initial_balance > 0 else 0,
            "total_orders": self._order_counter,
        }
