"""Tests for backtester module."""
import pytest
from datetime import datetime, timezone

from src.backtester.results import (
    BacktestTrade, BacktestMetrics, BacktestResult, compute_metrics,
)


class TestBacktestTrade:
    def test_frozen(self):
        """BacktestTrade should be immutable."""
        trade = _make_trade(pnl=100)
        with pytest.raises(AttributeError):
            trade.pnl = 200

    def test_fields(self):
        trade = _make_trade(pnl=50, pnl_pct=5.0, direction="long")
        assert trade.direction == "long"
        assert trade.pnl == 50
        assert trade.pnl_pct == 5.0


class TestComputeMetrics:
    def test_no_trades(self):
        """Empty trade list should return zero metrics."""
        metrics = compute_metrics([], 10000, [(datetime.now(tz=timezone.utc).isoformat(), 10000)])
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.sharpe_ratio == 0.0

    def test_all_wins(self):
        trades = [_make_trade(pnl=100), _make_trade(pnl=200), _make_trade(pnl=50)]
        equity = _make_equity(10000, [100, 200, 50])
        metrics = compute_metrics(trades, 10000, equity)
        assert metrics.win_rate == 1.0
        assert metrics.total_trades == 3
        assert metrics.profit_factor > 0
        assert metrics.max_consecutive_wins == 3
        assert metrics.max_consecutive_losses == 0

    def test_mixed_trades(self):
        trades = [_make_trade(pnl=100), _make_trade(pnl=-50), _make_trade(pnl=80)]
        equity = _make_equity(10000, [100, -50, 80])
        metrics = compute_metrics(trades, 10000, equity)
        assert metrics.total_trades == 3
        assert 0 < metrics.win_rate < 1
        assert metrics.profit_factor > 1  # 180/50 = 3.6
        assert metrics.avg_win > 0
        assert metrics.avg_loss < 0

    def test_all_losses(self):
        trades = [_make_trade(pnl=-100), _make_trade(pnl=-200)]
        equity = _make_equity(10000, [-100, -200])
        metrics = compute_metrics(trades, 10000, equity)
        assert metrics.win_rate == 0.0
        assert metrics.total_return_pct < 0
        assert metrics.max_consecutive_losses == 2

    def test_drawdown(self):
        """Max drawdown should reflect peak-to-trough decline."""
        equity = [
            ("2025-01-01T00:00:00", 10000),
            ("2025-01-02T00:00:00", 12000),  # peak
            ("2025-01-03T00:00:00", 9000),   # trough (25% DD from 12000)
            ("2025-01-04T00:00:00", 11000),
        ]
        metrics = compute_metrics([], 10000, equity)
        assert metrics.max_drawdown_pct == pytest.approx(25.0, abs=1)

    def test_sharpe_zero_std(self):
        """If all returns are the same, sharpe should be 0."""
        equity = [
            ("2025-01-01T00:00:00", 10000),
            ("2025-01-02T00:00:00", 10000),
            ("2025-01-03T00:00:00", 10000),
        ]
        metrics = compute_metrics([], 10000, equity)
        assert metrics.sharpe_ratio == 0.0


# --- Helpers ---

def _make_trade(pnl=0, pnl_pct=None, direction="long"):
    if pnl_pct is None:
        pnl_pct = pnl / 100  # simplified
    return BacktestTrade(
        pair="BTC/USDT:USDT",
        direction=direction,
        entry_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        exit_time=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
        entry_price=50000,
        exit_price=50000 + pnl,
        size=0.1,
        leverage=2,
        pnl=pnl,
        pnl_pct=pnl_pct,
        exit_reason="test",
        conviction=0.7,
        scores={"sentiment": 50, "whale": 50, "technical": 65},
    )


def _make_equity(initial, pnl_steps):
    """Build equity curve from initial balance and PnL steps."""
    equity = [(datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(), initial)]
    balance = initial
    for i, pnl in enumerate(pnl_steps):
        balance += pnl
        ts = datetime(2025, 1, 1, i + 1, tzinfo=timezone.utc).isoformat()
        equity.append((ts, balance))
    return equity
