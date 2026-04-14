"""Multi-period backtest: fetch fresh data for different market conditions."""
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
logging.getLogger("src.backtester").setLevel(logging.INFO)

from src.config import load_config, ScoringWeights
from src.storage.database import init_db
from src.backtester.engine import BacktestEngine

OPTIMAL = {
    "scoring_weights": ScoringWeights(sentiment=0.0, whale=0.0, technical=1.0),
    "entry_threshold": 0.65,
    "atr_multiplier": 2.5,
    "trend_filter": True,
    "cooldown_bars": 12,
    "trail_after_atr": 1.0,
    "max_hold_minutes": 480,
    "commission": 0.0006,
}


def print_result(label, result):
    m = result.metrics
    long_ct = sum(1 for t in result.trades if t.direction == "long")
    short_ct = sum(1 for t in result.trades if t.direction == "short")
    print("  {}".format(label))
    print("    Trades:{:>4d} (L:{} S:{})  Win:{:>5.1f}%  Return:{:>+7.2f}%".format(
        m.total_trades, long_ct, short_ct, m.win_rate * 100, m.total_return_pct))
    print("    Sharpe:{:>6.2f}  DD:{:>5.2f}%  PF:{:>5.2f}  ${:,.0f}->${:,.0f}".format(
        m.sharpe_ratio, m.max_drawdown_pct, m.profit_factor,
        result.initial_balance, result.final_balance))


async def run():
    await init_db()
    config = load_config("config.yaml")
    engine = BacktestEngine(config)

    # Test multiple periods to validate robustness
    periods = [
        ("BTC/USDT:USDT", "5m", "2025-09-01", "2025-11-01", "Sep-Oct 2025"),
        ("BTC/USDT:USDT", "5m", "2025-11-01", "2026-01-01", "Nov-Dec 2025"),
        ("BTC/USDT:USDT", "5m", "2026-01-01", "2026-02-01", "Jan 2026"),
        ("ETH/USDT:USDT", "5m", "2025-12-01", "2026-01-31", "ETH Dec-Jan"),
    ]

    print("\n" + "=" * 75)
    print("  MULTI-PERIOD ROBUSTNESS TEST (VIP 0.06% commission)")
    print("  Config: PureTech th=0.65 TrendFilter ATR=2.5 Cooldown=12")
    print("=" * 75)

    total_trades = 0
    total_wins = 0
    total_pnl = 0.0

    for pair, tf, start, end, label in periods:
        print("\n  Fetching {} {} {}->{} ...".format(pair, tf, start, end))
        try:
            result = await engine.run(
                pair=pair, timeframe=tf,
                start_date=start, end_date=end,
                initial_balance=10000.0,
                **OPTIMAL,
            )
            print_result(label, result)
            total_trades += result.metrics.total_trades
            total_wins += sum(1 for t in result.trades if t.pnl > 0)
            total_pnl += (result.final_balance - result.initial_balance)
        except Exception as e:
            print("  {} FAILED: {}".format(label, e))

    if total_trades > 0:
        print("\n" + "=" * 75)
        print("  AGGREGATE")
        print("  Total trades: {}  |  Overall win rate: {:.1f}%".format(
            total_trades, total_wins / total_trades * 100))
        print("  Total PnL: ${:+,.2f} (across all periods)".format(total_pnl))
        print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run())
