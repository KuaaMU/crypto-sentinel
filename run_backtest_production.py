"""Final production-ready backtest with optimal config."""
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

# Optimal configuration found through iterative optimization
OPTIMAL = {
    "scoring_weights": ScoringWeights(sentiment=0.0, whale=0.0, technical=1.0),
    "entry_threshold": 0.65,
    "atr_multiplier": 2.5,
    "trend_filter": True,
    "cooldown_bars": 12,
    "trail_after_atr": 1.0,
    "max_hold_minutes": 480,
}


def print_result(name, result):
    m = result.metrics
    long_ct = sum(1 for t in result.trades if t.direction == "long")
    short_ct = sum(1 for t in result.trades if t.direction == "short")
    print("  {}".format(name))
    print("    Trades:{:>4d} (L:{} S:{})  Win:{:>5.1f}%  Return:{:>+7.2f}%".format(
        m.total_trades, long_ct, short_ct, m.win_rate * 100, m.total_return_pct))
    print("    Sharpe:{:>6.2f}  DD:{:>5.2f}%  PF:{:>5.2f}  R:R={:.1f}".format(
        m.sharpe_ratio, m.max_drawdown_pct, m.profit_factor,
        m.avg_win / abs(m.avg_loss) if m.avg_loss != 0 else 0))
    print("    AvgWin:${:>7.2f}  AvgLoss:${:>7.2f}  ${:,.0f}->${:,.0f}".format(
        m.avg_win, abs(m.avg_loss), result.initial_balance, result.final_balance))

    reasons = {}
    for t in result.trades:
        key = t.exit_reason.split(":")[0].strip()
        reasons[key] = reasons.get(key, 0) + 1
    print("    Exits: {}".format(
        " | ".join("{}: {}".format(k, v)
                    for k, v in sorted(reasons.items(), key=lambda x: -x[1]))))


async def run():
    await init_db()
    config = load_config("config.yaml")
    engine = BacktestEngine(config)

    pair = "BTC/USDT:USDT"
    timeframe = "5m"
    start_date = "2025-12-01"
    end_date = "2026-01-31"

    print("\n" + "=" * 75)
    print("  FINAL RESULTS: Optimal Config at Different Commission Levels")
    print("  {} {} {} -> {}".format(pair, timeframe, start_date, end_date))
    print("  Config: PureTech th=0.65 TrendFilter ATR=2.5 Cooldown=12")
    print("=" * 75)

    commissions = [
        ("0.10% (standard taker)", 0.001),
        ("0.06% (VIP taker)", 0.0006),
        ("0.02% (maker rebate)", 0.0002),
    ]

    results = {}
    for label, comm in commissions:
        print("\nRunning: commission={}...".format(label))
        result = await engine.run(
            pair=pair, timeframe=timeframe,
            start_date=start_date, end_date=end_date,
            initial_balance=10000.0,
            commission=comm,
            **OPTIMAL,
        )
        results[label] = result

    print("\n" + "=" * 75)
    print("  COMMISSION SENSITIVITY ANALYSIS")
    print("=" * 75)

    for label, result in results.items():
        print("\n  Commission: {}".format(label))
        print_result("  ", result)

    # Now test the same config on a different (trending) period
    print("\n" + "=" * 75)
    print("  MULTI-PERIOD TEST (comm=0.06% VIP)")
    print("=" * 75)

    periods = [
        ("2025-12-01", "2026-01-31", "Dec-Jan (sideways/down)"),
        ("2025-10-01", "2025-12-01", "Oct-Nov (pre-pump)"),
    ]

    for start, end, label in periods:
        print("\n  Period: {} ({})".format(label, start))
        try:
            result = await engine.run(
                pair=pair, timeframe=timeframe,
                start_date=start, end_date=end,
                initial_balance=10000.0,
                commission=0.0006,
                **OPTIMAL,
            )
            print_result("  " + label, result)
        except Exception as e:
            print("  FAILED: {}".format(e))

    print("\n" + "=" * 75)


if __name__ == "__main__":
    asyncio.run(run())
