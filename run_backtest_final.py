"""Final optimized backtest comparison with trailing stop activation."""
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


CONFIGS = {
    "A: Original (baseline)": {
        "entry_threshold": 0.58,
        "atr_multiplier": 1.5,
        "trend_filter": False,
        "cooldown_bars": 0,
        "scoring_weights": None,
        "trail_after_atr": 0.0,
    },
    "B: Best v1 (trend+stops)": {
        "entry_threshold": 0.62,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.15, whale=0.05, technical=0.80),
        "trail_after_atr": 0.0,
        "max_hold_minutes": 360,
    },
    "C: v2 + Trail Activation 1xATR": {
        "entry_threshold": 0.62,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.15, whale=0.05, technical=0.80),
        "trail_after_atr": 1.0,
        "max_hold_minutes": 360,
    },
    "D: v2 + Trail Activation 1.5xATR": {
        "entry_threshold": 0.62,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.15, whale=0.05, technical=0.80),
        "trail_after_atr": 1.5,
        "max_hold_minutes": 360,
    },
    "E: v2 + Trail 1.5x + ATR 3.0": {
        "entry_threshold": 0.62,
        "atr_multiplier": 3.0,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.15, whale=0.05, technical=0.80),
        "trail_after_atr": 1.5,
        "max_hold_minutes": 480,
    },
}


def print_result(name, result):
    m = result.metrics
    print("  {}".format(name))
    print("    Trades:{:>4d}  Win:{:>5.1f}%  Return:{:>+7.2f}%  Sharpe:{:>5.2f}  DD:{:>5.2f}%  PF:{:>5.2f}".format(
        m.total_trades, m.win_rate * 100, m.total_return_pct,
        m.sharpe_ratio, m.max_drawdown_pct, m.profit_factor))
    print("    AvgWin:${:>7.2f}  AvgLoss:${:>7.2f}  R:R={:.1f}  ${:,.0f}->${:,.0f}".format(
        m.avg_win, abs(m.avg_loss),
        m.avg_win / abs(m.avg_loss) if m.avg_loss != 0 else 0,
        result.initial_balance, result.final_balance))

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
    print("  FINAL OPTIMIZATION: {} {} {} -> {}".format(
        pair, timeframe, start_date, end_date))
    print("=" * 75)

    results = {}
    for name, cfg in CONFIGS.items():
        print("\nRunning: {}...".format(name))
        result = await engine.run(
            pair=pair, timeframe=timeframe,
            start_date=start_date, end_date=end_date,
            initial_balance=10000.0,
            scoring_weights=cfg["scoring_weights"],
            entry_threshold=cfg["entry_threshold"],
            atr_multiplier=cfg["atr_multiplier"],
            trend_filter=cfg["trend_filter"],
            cooldown_bars=cfg["cooldown_bars"],
            max_hold_minutes=cfg.get("max_hold_minutes"),
            trail_after_atr=cfg.get("trail_after_atr", 1.0),
        )
        results[name] = result

    print("\n" + "=" * 75)
    print("  RESULTS COMPARISON")
    print("=" * 75)

    for name, result in results.items():
        print_result(name, result)
        print()

    eligible = {n: r for n, r in results.items() if r.metrics.total_trades >= 5}
    if eligible:
        best_ret = max(eligible, key=lambda n: eligible[n].metrics.total_return_pct)
        best_pf = max(eligible, key=lambda n: eligible[n].metrics.profit_factor)
        best_sharpe = max(eligible, key=lambda n: eligible[n].metrics.sharpe_ratio)
        print("=" * 75)
        print("  Best Return  : {}".format(best_ret))
        print("  Best PF      : {}".format(best_pf))
        print("  Best Sharpe  : {}".format(best_sharpe))
        print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run())
