"""
Backtrader strategy that reuses Crypto Sentinel's 3-dimensional scoring logic.

Supports two modes:
  - Technical-only: neutral defaults for sentiment/whale (original behavior)
  - Historical sentiment: uses real Fear & Greed Index data for sentiment dimension

Configurable features:
  - Trend filter: skip counter-trend entries (LONG below EMA55, SHORT above EMA55)
  - Cooldown: minimum bars between trades to avoid overtrading
"""

import logging
from datetime import datetime, timezone

import backtrader as bt
import pandas as pd

from src.analyzers.sentiment import analyze_sentiment
from src.analyzers.technical import analyze_technical
from src.strategy.signal_generator import generate_signal, should_enter
from src.execution.exit_manager import (
    ExitManager,
    calculate_stop_loss,
    calculate_tp_prices,
    calculate_atr,
)
from src.strategy.risk_manager import calculate_position_size
from src.models import ScoreResult, Direction, CompositeSignal, FearGreedData
from src.config import ScoringWeights, TradingConfig, ExitConfig
from src.backtester.results import BacktestTrade

logger = logging.getLogger(__name__)


def _neutral_score() -> ScoreResult:
    """Create a neutral score for dimensions without historical data."""
    return ScoreResult(
        value=50.0,
        direction=Direction.NEUTRAL,
        confidence=0.0,
        reason="No historical data available",
        timestamp=datetime.now(tz=timezone.utc),
    )


class CryptoSentinelStrategy(bt.Strategy):
    """Backtrader strategy using Crypto Sentinel's scoring engine.

    Technical-only mode: sentiment and whale use neutral defaults.
    """

    params = (
        ("pair", "BTC/USDT:USDT"),
        ("scoring_weights", None),  # ScoringWeights
        ("trading_config", None),  # TradingConfig
        ("exit_config", None),  # ExitConfig
        ("lookback", 100),  # OHLCV lookback for indicators
        ("leverage", 2),  # Default leverage
        ("fg_history", None),  # dict[str, FearGreedData] for real sentiment
        ("trend_filter", True),  # Skip counter-trend entries
        ("cooldown_bars", 6),  # Minimum bars between trades (30min on 5m)
        ("trail_after_atr", 1.0),  # Only trail after price moves 1x ATR in favor
    )

    def __init__(self):
        self._bt_trades: list[BacktestTrade] = []
        self._equity_curve: list[tuple[str, float]] = []
        self._current_trade: dict | None = None
        self._exit_manager = ExitManager(
            atr_multiplier=(
                self.p.exit_config.trailing_atr_multiplier
                if self.p.exit_config
                else 1.5
            ),
            max_hold_minutes=(
                self.p.trading_config.max_hold_minutes
                if self.p.trading_config
                else 240
            ),
        )
        self._bar_count = 0
        self._last_trade_bar = -999  # For cooldown tracking
        self._filtered_count = 0  # Track how many signals filtered by trend

    # ------------------------------------------------------------------
    # Core bar-by-bar logic
    # ------------------------------------------------------------------

    def next(self):
        """Called on each bar. Build OHLCV window, analyze, decide."""
        self._bar_count += 1

        # Record equity
        self._equity_curve.append((
            self.data.datetime.datetime(0)
            .replace(tzinfo=timezone.utc)
            .isoformat(),
            self.broker.getvalue(),
        ))

        # Need enough bars for indicators
        if len(self.data) < self.p.lookback:
            return

        # Build OHLCV window for analyze_technical
        ohlcv = self._build_ohlcv_window()

        # Check exits first if we have an open position
        if self.position:
            self._check_exits(ohlcv)
            return  # Don't enter new position while one is open

        # Generate signal
        tech_score = analyze_technical(ohlcv, self.p.pair)

        # Use real historical sentiment if available
        fg_data = None
        if self.p.fg_history:
            from src.backtester.historical_sentiment import get_fg_for_timestamp
            current_dt = self.data.datetime.datetime(0).replace(tzinfo=timezone.utc)
            fg_data = get_fg_for_timestamp(self.p.fg_history, current_dt)

        if fg_data is not None:
            # Real sentiment analysis using historical Fear & Greed
            sentiment_score = analyze_sentiment(fg_data, {"sentiment_score": 50})
        else:
            sentiment_score = _neutral_score()

        whale_score = _neutral_score()

        weights = self.p.scoring_weights or ScoringWeights(
            sentiment=0.35, whale=0.35, technical=0.30
        )
        signal = generate_signal(
            sentiment_score, whale_score, tech_score, weights, self.p.pair
        )

        threshold = (
            self.p.trading_config.entry_conviction_threshold
            if self.p.trading_config
            else 0.65
        )

        if not should_enter(signal, threshold):
            return

        # Trend filter: skip counter-trend entries
        if self.p.trend_filter:
            closes = pd.Series([c[4] for c in ohlcv])
            ema55 = float(closes.ewm(span=55, adjust=False).mean().iloc[-1])
            current_price = self.data.close[0]

            if signal.direction == Direction.LONG and current_price < ema55:
                self._filtered_count += 1
                return  # Don't go LONG below EMA55 (downtrend)
            if signal.direction == Direction.SHORT and current_price > ema55:
                self._filtered_count += 1
                return  # Don't go SHORT above EMA55 (uptrend)

        # Cooldown: avoid overtrading
        if (self._bar_count - self._last_trade_bar) < self.p.cooldown_bars:
            return

        # Calculate position size
        balance = self.broker.getvalue()
        trading_config = self.p.trading_config or TradingConfig(
            base_leverage=2,
            max_leverage=5,
            max_positions=3,
            max_position_pct=0.30,
            daily_loss_limit=-0.05,
            entry_conviction_threshold=0.65,
            exit_conviction_threshold=0.30,
            max_hold_minutes=240,
        )
        size_usd, leverage = calculate_position_size(signal, balance, trading_config)

        current_price = self.data.close[0]

        # Size in base currency (leveraged)
        actual_size = (size_usd * leverage) / current_price

        # Calculate stop loss via ATR
        exit_cfg = self.p.exit_config
        atr_period = exit_cfg.trailing_atr_period if exit_cfg else 14
        atr_mult = exit_cfg.trailing_atr_multiplier if exit_cfg else 1.5

        atr = calculate_atr(ohlcv, atr_period)
        if atr <= 0:
            return

        sl = calculate_stop_loss(current_price, signal.direction, atr, atr_mult)

        # Enter trade
        if signal.direction == Direction.LONG:
            self.buy(size=actual_size)
        else:
            self.sell(size=actual_size)

        self._last_trade_bar = self._bar_count

        # Track current trade state
        self._current_trade = {
            "direction": signal.direction.value,
            "entry_time": self.data.datetime.datetime(0).replace(
                tzinfo=timezone.utc
            ),
            "entry_price": current_price,
            "size": actual_size,
            "leverage": leverage,
            "conviction": signal.conviction,
            "stop_loss": sl,
            "trailing_stop": sl,
            "scores": {
                "sentiment": sentiment_score.value,
                "whale": whale_score.value,
                "technical": tech_score.value,
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_ohlcv_window(self) -> list[list]:
        """Build OHLCV window from Backtrader data for analyze_technical."""
        lookback = min(self.p.lookback, len(self.data))
        ohlcv: list[list] = []
        for i in range(-lookback + 1, 1):  # from oldest to newest
            ts = int(
                self.data.datetime.datetime(i)
                .replace(tzinfo=timezone.utc)
                .timestamp()
                * 1000
            )
            ohlcv.append([
                ts,
                self.data.open[i],
                self.data.high[i],
                self.data.low[i],
                self.data.close[i],
                self.data.volume[i],
            ])
        return ohlcv

    def _check_exits(self, ohlcv: list) -> None:
        """Check exit conditions for the open position."""
        if not self._current_trade:
            return

        current_price = self.data.close[0]
        direction = self._current_trade["direction"]
        entry_price = self._current_trade["entry_price"]
        sl = self._current_trade["stop_loss"]
        trailing = self._current_trade["trailing_stop"]

        exit_cfg = self.p.exit_config
        atr_period = exit_cfg.trailing_atr_period if exit_cfg else 14
        atr_mult = exit_cfg.trailing_atr_multiplier if exit_cfg else 1.5

        atr = calculate_atr(ohlcv, atr_period)

        should_exit = False
        exit_reason = ""

        # 1. Stop loss
        if direction == "long" and current_price <= sl:
            should_exit = True
            exit_reason = f"Stop loss: {current_price:.2f} <= {sl:.2f}"
        elif direction == "short" and current_price >= sl:
            should_exit = True
            exit_reason = f"Stop loss: {current_price:.2f} >= {sl:.2f}"

        # 2. Trailing stop update & check (only after sufficient profit)
        if not should_exit and atr > 0:
            trail_activation = atr * self.p.trail_after_atr
            if direction == "long":
                in_profit = current_price - entry_price
                if in_profit >= trail_activation:
                    # Only start trailing after price moved enough
                    new_trail = current_price - (atr * atr_mult)
                    if new_trail > trailing:
                        self._current_trade["trailing_stop"] = new_trail
                        trailing = new_trail
                    if current_price <= trailing and trailing > sl:
                        should_exit = True
                        exit_reason = (
                            f"Trailing stop: {current_price:.2f} <= {trailing:.2f}"
                        )
            else:
                in_profit = entry_price - current_price
                if in_profit >= trail_activation:
                    new_trail = current_price + (atr * atr_mult)
                    if new_trail < trailing or trailing == sl:
                        self._current_trade["trailing_stop"] = new_trail
                        trailing = new_trail
                    if current_price >= trailing and trailing < sl:
                        should_exit = True
                        exit_reason = (
                            f"Trailing stop: {current_price:.2f} >= {trailing:.2f}"
                        )

        # 3. Take profit check (fixed levels from exit_config)
        if not should_exit and exit_cfg:
            for _pct, target in exit_cfg.partial_tp_levels:
                if target == "trailing":
                    continue
                if direction == "long":
                    tp_price = entry_price * (1 + target)
                    if current_price >= tp_price:
                        should_exit = True
                        exit_reason = (
                            f"TP hit: {current_price:.2f} >= {tp_price:.2f}"
                        )
                        break
                else:
                    tp_price = entry_price * (1 - target)
                    if current_price <= tp_price:
                        should_exit = True
                        exit_reason = (
                            f"TP hit: {current_price:.2f} <= {tp_price:.2f}"
                        )
                        break

        # 4. Time exit
        if not should_exit:
            max_hold = (
                self.p.trading_config.max_hold_minutes
                if self.p.trading_config
                else 240
            )
            entry_time = self._current_trade["entry_time"]
            current_time = self.data.datetime.datetime(0).replace(
                tzinfo=timezone.utc
            )
            elapsed = (current_time - entry_time).total_seconds() / 60
            if elapsed >= max_hold:
                should_exit = True
                exit_reason = f"Time exit: {elapsed:.0f}min >= {max_hold}min"

        if should_exit:
            self._close_trade(exit_reason)

    def _close_trade(self, reason: str) -> None:
        """Close the current position and record the trade."""
        current_price = self.data.close[0]
        trade_info = self._current_trade

        if trade_info is None:
            return

        # Close position
        self.close()

        # Calculate PnL
        entry = trade_info["entry_price"]
        size = trade_info["size"]
        leverage = trade_info["leverage"]

        if trade_info["direction"] == "long":
            pnl = (current_price - entry) * size
            pnl_pct = (current_price - entry) / entry * 100
        else:
            pnl = (entry - current_price) * size
            pnl_pct = (entry - current_price) / entry * 100

        trade = BacktestTrade(
            pair=self.p.pair,
            direction=trade_info["direction"],
            entry_time=trade_info["entry_time"],
            exit_time=self.data.datetime.datetime(0).replace(tzinfo=timezone.utc),
            entry_price=entry,
            exit_price=current_price,
            size=size,
            leverage=leverage,
            pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct, 4),
            exit_reason=reason,
            conviction=trade_info["conviction"],
            scores=trade_info["scores"],
        )
        self._bt_trades.append(trade)
        self._current_trade = None

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def stop(self):
        """Called when backtest ends. Close any open position."""
        if self.position:
            self._close_trade("Backtest ended")

    # ------------------------------------------------------------------
    # Public read-only accessors (return copies for immutability)
    # ------------------------------------------------------------------

    @property
    def backtest_trades(self) -> list[BacktestTrade]:
        return list(self._bt_trades)

    @property
    def equity_curve(self) -> list[tuple[str, float]]:
        return list(self._equity_curve)

    @property
    def filtered_signals(self) -> int:
        return self._filtered_count
