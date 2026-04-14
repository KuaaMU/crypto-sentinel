"""Diagnostic backtest: test pure technical vs biased sentiment."""
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
    "A: Original w/Sentiment (baseline)": {
        "entry_threshold": 0.58,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.20, whale=0.20, technical=0.60),
        "trail_after_atr": 1.0,
        "max_hold_minutes": 360,
    },
    "B: Pure Technical (no sent bias)": {
        "entry_threshold": 0.62,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.0, whale=0.0, technical=1.0),
        "trail_after_atr": 1.0,
        "max_hold_minutes": 360,
    },
    "C: PureTech th=0.58 wider": {
        "entry_threshold": 0.58,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.0, whale=0.0, technical=1.0),
        "trail_after_atr": 1.0,
        "max_hold_minutes": 480,
    },
    "D: PureTech th=0.65 selective": {
        "entry_threshold": 0.65,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 12,
        "scoring_weights": ScoringWeights(sentiment=0.0, whale=0.0, technical=1.0),
        "trail_after_atr": 1.0,
        "max_hold_minutes": 480,
    },
    "E: PureTech th=0.70 ultra-selective": {
        "entry_threshold": 0.70,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 12,
        "scoring_weights": ScoringWeights(sentiment=0.0, whale=0.0, technical=1.0),
        "trail_after_atr": 1.0,
        "max_hold_minutes": 480,
    },
}


def print_result(name, result):
    m = result.metrics
    long_ct = sum(1 for t in result.trades if t.direction == "long")
    short_ct = sum(1 for t in result.trades if t.direction == "short")
    print("  {}".format(name))
    print("    Trades:{:>4d} (L:{} S:{})  Win:{:>5.1f}%  Return:{:>+7.2f}%".format(
        m.total_trades, long_ct, short_ct, m.win_rate * 100, m.total_return_pct))
    print("    Sharpe:{:>5.2f}  DD:{:>5.2f}%  PF:{:>5.2f}  R:R={:.1f}".format(
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
    print("  DIAGNOSTIC: Pure Technical vs Sentiment Bias")
    print("  {} {} {} -> {}".format(pair, timeframe, start_date, end_date))
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
    print("  RESULTS")
    print("=" * 75)

    for name, result in results.items():
        print_result(name, result)
        print()

    eligible = {n: r for n, r in results.items() if r.metrics.total_trades >= 5}
    if eligible:
        best_ret = max(eligible, key=lambda n: eligible[n].metrics.total_return_pct)
        best_pf = max(eligible, key=lambda n: eligible[n].metrics.profit_factor)
        print("=" * 75)
        print("  BEST RETURN: {}  ({:+.2f}%)".format(
            best_ret, eligible[best_ret].metrics.total_return_pct))
        print("  BEST PF:     {}  (PF={:.2f})".format(
            best_pf, eligible[best_pf].metrics.profit_factor))
        print("=" * 75)

    # Show trades for best return config
    if eligible:
        best = results[best_ret]
        print("\nTrades for best config (first 30):")
        for i, t in enumerate(best.trades[:30], 1):
            print("  {}. {:>5s} {}->{} ${:,.0f}->${:,.0f} ${:>+8.2f} ({:>+.2f}%) {}".format(
                i, t.direction.upper(),
                t.entry_time.strftime("%m/%d %H:%M"),
                t.exit_time.strftime("%m/%d %H:%M"),
                t.entry_price, t.exit_price,
                t.pnl, t.pnl_pct,
                t.exit_reason[:45],
            ))
        if len(best.trades) > 30:
            print("  ... and {} more trades".format(len(best.trades) - 30))


if __name__ == "__main__":
    asyncio.run(run())
