"""Frozen dataclasses for backtest results and metrics computation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class BacktestTrade:
    """A single trade executed during a backtest."""

    pair: str
    direction: str  # "long" or "short"
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    size: float  # position size in base currency
    leverage: int
    pnl: float  # realized PnL in USDT
    pnl_pct: float  # PnL as percentage
    exit_reason: str
    conviction: float
    scores: dict = field(default_factory=dict)  # {"sentiment": x, "whale": y, "technical": z}


@dataclass(frozen=True)
class BacktestMetrics:
    """Aggregated performance metrics for a backtest run."""

    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    profit_factor: float
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    max_consecutive_wins: int
    max_consecutive_losses: int


@dataclass(frozen=True)
class BacktestResult:
    """Complete result of a single backtest run."""

    id: str
    pair: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    metrics: BacktestMetrics
    trades: tuple[BacktestTrade, ...] = field(default_factory=tuple)
    equity_curve: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    config: dict = field(default_factory=dict)


def compute_metrics(
    trades: list[BacktestTrade],
    initial_balance: float,
    equity_curve: list[tuple[str, float]],
) -> BacktestMetrics:
    """Compute aggregated backtest metrics from trades and equity curve."""

    final_balance = equity_curve[-1][1] if equity_curve else initial_balance
    total_return_pct = (final_balance - initial_balance) / initial_balance * 100 if initial_balance else 0.0

    total_trades = len(trades)

    winning_trades = [t for t in trades if t.pnl > 0]
    losing_trades = [t for t in trades if t.pnl < 0]

    win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0

    gross_profit = sum(t.pnl for t in winning_trades)
    gross_loss = abs(sum(t.pnl for t in losing_trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

    avg_trade_pnl = sum(t.pnl for t in trades) / total_trades if total_trades > 0 else 0.0
    avg_win = gross_profit / len(winning_trades) if winning_trades else 0.0
    avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0.0

    # Sharpe ratio from daily equity curve returns
    sharpe_ratio = _compute_sharpe(equity_curve)

    # Max drawdown from equity curve
    max_drawdown_pct = _compute_max_drawdown(equity_curve)

    # Consecutive win/loss streaks
    max_consecutive_wins, max_consecutive_losses = _compute_streaks(trades)

    return BacktestMetrics(
        total_return_pct=total_return_pct,
        sharpe_ratio=sharpe_ratio,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        total_trades=total_trades,
        profit_factor=profit_factor,
        avg_trade_pnl=avg_trade_pnl,
        avg_win=avg_win,
        avg_loss=avg_loss,
        max_consecutive_wins=max_consecutive_wins,
        max_consecutive_losses=max_consecutive_losses,
    )


def _compute_sharpe(equity_curve: list[tuple[str, float]]) -> float:
    """Annualized Sharpe ratio from equity curve daily returns."""

    if len(equity_curve) < 2:
        return 0.0

    balances = [point[1] for point in equity_curve]
    returns = [
        (balances[i] - balances[i - 1]) / balances[i - 1]
        for i in range(1, len(balances))
        if balances[i - 1] != 0
    ]

    if not returns:
        return 0.0

    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_return = math.sqrt(variance)

    if std_return == 0:
        return 0.0

    return (mean_return / std_return) * math.sqrt(365)


def _compute_max_drawdown(equity_curve: list[tuple[str, float]]) -> float:
    """Peak-to-trough max drawdown as a percentage."""

    if not equity_curve:
        return 0.0

    peak = equity_curve[0][1]
    max_dd = 0.0

    for _, balance in equity_curve:
        if balance > peak:
            peak = balance
        drawdown = (peak - balance) / peak * 100 if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd


def _compute_streaks(trades: list[BacktestTrade]) -> tuple[int, int]:
    """Return (max_consecutive_wins, max_consecutive_losses)."""

    max_wins = 0
    max_losses = 0
    current_wins = 0
    current_losses = 0

    for trade in trades:
        if trade.pnl > 0:
            current_wins += 1
            current_losses = 0
            max_wins = max(max_wins, current_wins)
        elif trade.pnl < 0:
            current_losses += 1
            current_wins = 0
            max_losses = max(max_losses, current_losses)
        else:
            current_wins = 0
            current_losses = 0

    return max_wins, max_losses
