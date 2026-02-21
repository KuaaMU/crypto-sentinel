import logging
from datetime import datetime, timezone

from src.models import Position, Direction, PositionStatus

logger = logging.getLogger(__name__)


def calculate_atr(ohlcv: list, period: int = 14) -> float:
    """Calculate Average True Range from OHLCV data."""
    if len(ohlcv) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(ohlcv)):
        high = ohlcv[i][2]
        low = ohlcv[i][3]
        prev_close = ohlcv[i - 1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    return sum(true_ranges[-period:]) / period


def calculate_stop_loss(
    entry_price: float,
    direction: Direction,
    atr: float,
    multiplier: float = 1.5,
) -> float:
    """Calculate initial stop loss based on ATR."""
    distance = atr * multiplier
    if direction == Direction.LONG:
        return entry_price - distance
    else:
        return entry_price + distance


def calculate_tp_prices(
    entry_price: float,
    direction: Direction,
    tp_config: tuple,
) -> list[tuple[float, float]]:
    """Calculate take-profit price levels.

    Args:
        entry_price: Entry price
        direction: Long or Short
        tp_config: ((pct_of_position, target_pct_or_'trailing'), ...)

    Returns:
        [(pct_of_position, target_price), ...]
    """
    levels = []
    for pct, target in tp_config:
        if target == "trailing":
            # Trailing level uses 0 as marker (handled separately)
            levels.append((pct, 0.0))
        else:
            if direction == Direction.LONG:
                levels.append((pct, entry_price * (1 + target)))
            else:
                levels.append((pct, entry_price * (1 - target)))
    return levels


class ExitManager:
    """Manages smart exits: trailing stops, partial TPs, conviction decay, time exit."""

    def __init__(self, atr_multiplier: float = 1.5, max_hold_minutes: int = 240):
        self._atr_multiplier = atr_multiplier
        self._max_hold_minutes = max_hold_minutes

    def check_exits(
        self,
        position: Position,
        current_price: float,
        current_atr: float,
        current_conviction: float,
        conviction_exit_threshold: float,
    ) -> list[dict]:
        """Check all exit conditions for a position.

        Returns list of exit actions: [{'type': 'stop'|'tp'|'trailing'|'conviction'|'time', 'amount': ..., 'reason': ...}]
        """
        if position.status == PositionStatus.CLOSED:
            return []

        actions = []

        # 1. Stop loss check
        stop_action = self._check_stop_loss(position, current_price)
        if stop_action:
            return [stop_action]  # Stop loss exits everything immediately

        # 2. Partial take-profit check
        tp_actions = self._check_take_profits(position, current_price)
        actions.extend(tp_actions)

        # 3. Update trailing stop
        self._update_trailing_stop(position, current_price, current_atr)

        # 4. Trailing stop check (for remaining position)
        trailing_action = self._check_trailing_stop(position, current_price)
        if trailing_action:
            actions.append(trailing_action)

        # 5. Conviction decay exit
        if current_conviction < conviction_exit_threshold:
            actions.append({
                "type": "conviction",
                "amount": position.remaining_size,
                "reason": f"Conviction decayed to {current_conviction:.3f} < {conviction_exit_threshold}",
            })

        # 6. Time-based exit
        time_action = self._check_time_exit(position)
        if time_action:
            actions.append(time_action)

        return actions

    def _check_stop_loss(self, position: Position, current_price: float) -> dict | None:
        if position.direction == Direction.LONG and current_price <= position.stop_loss:
            return {
                "type": "stop",
                "amount": position.remaining_size,
                "reason": f"Stop loss hit: ${current_price:.2f} <= ${position.stop_loss:.2f}",
            }
        if position.direction == Direction.SHORT and current_price >= position.stop_loss:
            return {
                "type": "stop",
                "amount": position.remaining_size,
                "reason": f"Stop loss hit: ${current_price:.2f} >= ${position.stop_loss:.2f}",
            }
        return None

    def _check_take_profits(self, position: Position, current_price: float) -> list[dict]:
        actions = []
        for tp in position.tp_levels:
            if tp["filled"] or tp["target"] == 0.0:
                continue  # Skip already filled or trailing levels

            target = tp["target"]
            hit = False
            if position.direction == Direction.LONG and current_price >= target:
                hit = True
            elif position.direction == Direction.SHORT and current_price <= target:
                hit = True

            if hit:
                amount = position.remaining_size * tp["pct"] / sum(
                    t["pct"] for t in position.tp_levels if not t["filled"]
                )
                tp["filled"] = True
                actions.append({
                    "type": "tp",
                    "amount": amount,
                    "reason": f"TP hit: ${current_price:.2f} reached ${target:.2f}",
                })
        return actions

    def _update_trailing_stop(self, position: Position, current_price: float, atr: float) -> None:
        """Move trailing stop up (long) or down (short) as price moves favorably."""
        if atr <= 0:
            return

        new_trail = 0.0
        if position.direction == Direction.LONG:
            new_trail = current_price - (atr * self._atr_multiplier)
            if new_trail > position.trailing_stop:
                position.trailing_stop = new_trail
        else:
            new_trail = current_price + (atr * self._atr_multiplier)
            if new_trail < position.trailing_stop or position.trailing_stop == position.stop_loss:
                position.trailing_stop = new_trail

    def _check_trailing_stop(self, position: Position, current_price: float) -> dict | None:
        if position.direction == Direction.LONG and current_price <= position.trailing_stop:
            if position.trailing_stop > position.stop_loss:
                return {
                    "type": "trailing",
                    "amount": position.remaining_size,
                    "reason": f"Trailing stop: ${current_price:.2f} <= ${position.trailing_stop:.2f}",
                }
        if position.direction == Direction.SHORT and current_price >= position.trailing_stop:
            if position.trailing_stop < position.stop_loss:
                return {
                    "type": "trailing",
                    "amount": position.remaining_size,
                    "reason": f"Trailing stop: ${current_price:.2f} >= ${position.trailing_stop:.2f}",
                }
        return None

    def _check_time_exit(self, position: Position) -> dict | None:
        elapsed = (datetime.now(tz=timezone.utc) - position.opened_at).total_seconds() / 60
        if elapsed >= self._max_hold_minutes:
            return {
                "type": "time",
                "amount": position.remaining_size,
                "reason": f"Max hold time ({self._max_hold_minutes}min) exceeded ({elapsed:.0f}min)",
            }
        return None
