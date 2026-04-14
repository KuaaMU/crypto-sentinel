import logging
import uuid
from datetime import datetime, timezone

import ccxt.async_support as ccxt

from src.models import Position, Direction, PositionStatus, CompositeSignal

logger = logging.getLogger(__name__)


async def open_position(
    exchange: ccxt.Exchange,
    signal: CompositeSignal,
    size_usd: float,
    leverage: int,
    stop_loss: float,
    tp_levels: list[tuple[float, float]],
) -> Position | None:
    """Open a new position on the exchange.

    Args:
        exchange: CCXT exchange instance
        signal: The composite signal that triggered entry
        size_usd: Position size in USDT
        leverage: Leverage multiplier
        stop_loss: Stop loss price
        tp_levels: List of (pct_of_position, target_price)
    """
    pair = signal.pair
    side = "buy" if signal.direction == Direction.LONG else "sell"

    try:
        # Set one-way position mode and leverage
        try:
            await exchange.set_position_mode(False, pair)
        except Exception:
            pass  # already in net mode
        await exchange.set_leverage(leverage, pair, params={"mgnMode": "isolated"})

        # Get current price for amount calculation
        ticker = await exchange.fetch_ticker(pair)
        price = ticker["last"]

        # Calculate amount in base currency
        amount = (size_usd * leverage) / price

        # Check minimum order size
        market = exchange.market(pair)
        min_amount = market.get("limits", {}).get("amount", {}).get("min", 0)
        if amount < (min_amount or 0):
            logger.warning("Order too small: %.6f < min %.6f for %s", amount, min_amount, pair)
            return None

        # Place market order
        order = await exchange.create_order(
            symbol=pair,
            type="market",
            side=side,
            amount=amount,
            params={"tdMode": "isolated"},
        )

        fill_price = order.get("average") or order.get("price") or price
        filled_amount = order.get("filled") or amount

        position = Position(
            id=str(uuid.uuid4())[:8],
            pair=pair,
            direction=signal.direction,
            entry_price=fill_price,
            size=filled_amount,
            remaining_size=filled_amount,
            leverage=leverage,
            conviction=signal.conviction,
            stop_loss=stop_loss,
            trailing_stop=stop_loss,
            tp_levels=[{"pct": p, "target": t, "filled": False} for p, t in tp_levels],
            status=PositionStatus.OPEN,
            opened_at=datetime.now(tz=timezone.utc),
        )

        logger.info(
            "OPENED %s %s: size=%.4f @ $%.2f, leverage=%dx, SL=$%.2f, conviction=%.3f",
            signal.direction.value.upper(), pair, filled_amount, fill_price,
            leverage, stop_loss, signal.conviction,
        )
        return position

    except Exception as e:
        logger.error("Failed to open position for %s: %s", pair, e)
        return None


async def close_position(
    exchange: ccxt.Exchange,
    position: Position,
    amount: float | None = None,
    reason: str = "",
) -> float:
    """Close a position (fully or partially).

    Returns realized PnL in USDT.
    """
    close_amount = amount or position.remaining_size
    side = "sell" if position.direction == Direction.LONG else "buy"

    try:
        order = await exchange.create_order(
            symbol=position.pair,
            type="market",
            side=side,
            amount=close_amount,
            params={"reduceOnly": True, "tdMode": "isolated"},
        )

        fill_price = order.get("average") or order.get("price") or 0
        filled = order.get("filled") or close_amount

        # Calculate PnL
        if position.direction == Direction.LONG:
            pnl = (fill_price - position.entry_price) * filled * position.leverage
        else:
            pnl = (position.entry_price - fill_price) * filled * position.leverage

        position.remaining_size -= filled
        position.realized_pnl += pnl

        if position.remaining_size <= 0:
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.now(tz=timezone.utc)
        else:
            position.status = PositionStatus.PARTIAL_CLOSED

        position.exit_reason = reason

        logger.info(
            "CLOSED %.4f of %s %s @ $%.2f | PnL: $%.2f | Reason: %s",
            filled, position.direction.value.upper(), position.pair,
            fill_price, pnl, reason,
        )
        return pnl

    except Exception as e:
        logger.error("Failed to close position %s: %s", position.id, e)
        return 0.0
