"""Run refined backtest comparison after initial optimization."""
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
    "D1: TechHeavy th=0.62 cd=6 atr=2.5": {
        "entry_threshold": 0.62,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.15, whale=0.05, technical=0.80),
        "max_hold_minutes": 360,
    },
    "D2: TechHeavy th=0.60 cd=6 atr=2.0": {
        "entry_threshold": 0.60,
        "atr_multiplier": 2.0,
        "trend_filter": True,
        "cooldown_bars": 6,
        "scoring_weights": ScoringWeights(sentiment=0.15, whale=0.05, technical=0.80),
        "max_hold_minutes": 360,
    },
    "D3: TechHeavy th=0.62 cd=12 atr=3.0": {
        "entry_threshold": 0.62,
        "atr_multiplier": 3.0,
        "trend_filter": True,
        "cooldown_bars": 12,
        "scoring_weights": ScoringWeights(sentiment=0.15, whale=0.05, technical=0.80),
        "max_hold_minutes": 480,
    },
    "D4: TechHeavy th=0.60 cd=12 atr=2.5 hold=8h": {
        "entry_threshold": 0.60,
        "atr_multiplier": 2.5,
        "trend_filter": True,
        "cooldown_bars": 12,
        "scoring_weights": ScoringWeights(sentiment=0.15, whale=0.05, technical=0.80),
        "max_hold_minutes": 480,
    },
}


def print_result(name, result):
    m = result.metrics
    print("  {:<46s}".format(name))
    print("    Trades: {:>4d}  |  WinRate: {:>5.1f}%  |  Return: {:>+7.2f}%".format(
        m.total_trades, m.win_rate * 100, m.total_return_pct))
    print("    Sharpe: {:>5.2f}  |  MaxDD: {:>5.2f}%  |  PF: {:>5.2f}".format(
        m.sharpe_ratio, m.max_drawdown_pct, m.profit_factor))
    print("    AvgWin: ${:>8.2f}  |  AvgLoss: ${:>8.2f}  |  R:R={:.1f}".format(
        m.avg_win, abs(m.avg_loss), m.avg_win / abs(m.avg_loss) if m.avg_loss != 0 else 0))
    print("    ${:>10,.2f} -> ${:>10,.2f}".format(
        result.initial_balance, result.final_balance))

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
    print("  REFINED BACKTEST: {} {} {} -> {}".format(
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
            max_hold_minutes=cfg.get("max_hold_minutes"),
        )
        results[name] = result

    print("\n" + "=" * 70)
    print("  REFINED RESULTS")
    print("=" * 70)

    for name, result in results.items():
        print_result(name, result)
        print()

    # Best by profit factor (must have >= 5 trades)
    eligible = {n: r for n, r in results.items() if r.metrics.total_trades >= 5}
    if eligible:
        best_pf = max(eligible, key=lambda n: eligible[n].metrics.profit_factor)
        best_ret = max(eligible, key=lambda n: eligible[n].metrics.total_return_pct)
        print("  Best PF (>=5 trades): {}".format(best_pf))
        print("  Best Return (>=5 trades): {}".format(best_ret))

    # Show trades for best PF config
    if eligible:
        best = results[best_pf]
        print("\nTrade details for best PF config:")
        for i, t in enumerate(best.trades, 1):
            print("  {}. {} | {}->{} | ${:,.0f}->${:,.0f} | ${:.2f} ({:.2f}%) | {}".format(
                i, t.direction.upper(),
                t.entry_time.strftime("%m/%d %H:%M"),
                t.exit_time.strftime("%m/%d %H:%M"),
                t.entry_price, t.exit_price,
                t.pnl, t.pnl_pct,
                t.exit_reason[:50],
            ))


if __name__ == "__main__":
    asyncio.run(run())
