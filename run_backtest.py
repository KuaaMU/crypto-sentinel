"""Run backtest comparison: original vs optimized configurations."""
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Only show INFO for our backtest engine
logging.getLogger("src.backtester").setLevel(logging.INFO)

from src.config import load_config, ScoringWeights
from src.storage.database import init_db
from src.backtester.engine import BacktestEngine


CONFIGS = {
    "A: Original (no trend filter)": {
        "entry_threshold": 0.58,
        "atr_multiplier": 1.5,
        "trend_filter": False,
        "cooldown_bars": 0,
        "scoring_weights": None,  # Use config defaults
    },
    "B: Trend Filter + Wider Stops": {
        "entry_threshold": 0.58,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": None,
    },
    "C: High Threshold + Trend Filter": {
        "entry_threshold": 0.65,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": None,
    },
    "D: Tech-Heavy Weights + All Filters": {
        "entry_threshold": 0.65,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 12,
        "scoring_weights": ScoringWeights(
            sentiment=0.15,
            whale=0.05,
            technical=0.80,
        ),
    },
}


def print_result(name, result):
    m = result.metrics
    print("  {:<40s}".format(name))
    print("    Trades: {:>4d}  |  Win rate: {:>5.1f}%  |  Return: {:>+7.2f}%".format(
        m.total_trades, m.win_rate * 100, m.total_return_pct))
    print("    Sharpe: {:>5.2f}  |  MaxDD: {:>5.2f}%  |  PF: {:>5.2f}".format(
        m.sharpe_ratio, m.max_drawdown_pct, m.profit_factor))
    print("    AvgWin: ${:>8.2f}  |  AvgLoss: ${:>8.2f}".format(
        m.avg_win, m.avg_loss))
    print("    Final: ${:>10,.2f}  (from ${:>10,.2f})".format(
        result.final_balance, result.initial_balance))

    # Count directions
    long_count = sum(1 for t in result.trades if t.direction == "long")
    short_count = sum(1 for t in result.trades if t.direction == "short")
    print("    LONG: {}  |  SHORT: {}".format(long_count, short_count))

    # Exit reason breakdown
    reasons = {}
    for t in result.trades:
        key = t.exit_reason.split(":")[0].strip()
        reasons[key] = reasons.get(key, 0) + 1
    reason_str = " | ".join("{}: {}".format(k, v) for k, v in sorted(reasons.items(), key=lambda x: -x[1]))
    print("    Exits: {}".format(reason_str))


async def run():
    await init_db()
    config = load_config("config.yaml")
    engine = BacktestEngine(config)

    pair = "BTC/USDT:USDT"
    timeframe = "5m"
    start_date = "2025-12-01"
    end_date = "2026-01-31"

    print("\n" + "=" * 70)
    print("  BACKTEST COMPARISON: {} {} {} -> {}".format(
        pair, timeframe, start_date, end_date))
    print("=" * 70)

    results = {}
    for name, cfg in CONFIGS.items():
        print("\nRunning: {}...".format(name))
        result = await engine.run(
            pair=pair,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_balance=10000.0,
            scoring_weights=cfg["scoring_weights"],
            entry_threshold=cfg["entry_threshold"],
            atr_multiplier=cfg["atr_multiplier"],
            trend_filter=cfg["trend_filter"],
            cooldown_bars=cfg["cooldown_bars"],
        )
        results[name] = result

    # Summary table
    print("\n" + "=" * 70)
    print("  RESULTS COMPARISON")
    print("=" * 70)

    for name, result in results.items():
        print_result(name, result)
        print()

    # Find best config
    best_name = max(results, key=lambda n: results[n].metrics.total_return_pct)
    best = results[best_name]
    print("=" * 70)
    print("  BEST CONFIG: {}".format(best_name))
    print("  Return: {:.2f}%  |  Sharpe: {:.2f}  |  Trades: {}".format(
        best.metrics.total_return_pct, best.metrics.sharpe_ratio,
        best.metrics.total_trades))
    print("=" * 70)

    # Show trade details for best config
    print("\nBest config trade details (first 20):")
    for i, t in enumerate(best.trades[:20], 1):
        print("  {}. {} | {}->{} | ${:,.0f}->${:,.0f} | PnL=${:.2f} ({:.2f}%) | {}".format(
            i, t.direction.upper(),
            t.entry_time.strftime("%m/%d %H:%M"),
            t.exit_time.strftime("%m/%d %H:%M"),
            t.entry_price, t.exit_price,
            t.pnl, t.pnl_pct,
            t.exit_reason[:50],
        ))
    if len(best.trades) > 20:
        print("  ... and {} more trades".format(len(best.trades) - 20))


if __name__ == "__main__":
    asyncio.run(run())
