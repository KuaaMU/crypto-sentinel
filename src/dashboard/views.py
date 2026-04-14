"""
Dashboard HTML page routes.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, render_template

DB_PATH = Path("data/trades.db")

views_bp = Blueprint("views", __name__)


def _get_db():
    """Get synchronous SQLite connection."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# Get available pairs from config (lazy loaded)
def _get_pairs():
    try:
        from src.config import load_config
        config = load_config("config.yaml")
        return list(config.exchange.pairs)
    except Exception:
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]


@views_bp.route("/")
def index():
    """Dashboard home page."""
    conn = _get_db()
    if not conn:
        return render_template("index.html", daily_pnl=0, trade_count=0,
                             open_positions=[], signals=[], closed_trades=[],
                             now=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    try:
        # Query data
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        pnl_row = conn.execute("SELECT total_pnl, trade_count FROM daily_pnl WHERE date = ?", (today,)).fetchone()
        daily_pnl = dict(pnl_row)["total_pnl"] if pnl_row else 0.0
        trade_count = dict(pnl_row)["trade_count"] if pnl_row else 0

        open_positions = [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE status != 'closed' ORDER BY opened_at DESC"
        ).fetchall()]

        signals = [dict(r) for r in conn.execute(
            "SELECT * FROM signals ORDER BY timestamp DESC LIMIT 10"
        ).fetchall()]

        closed_trades = [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE status = 'closed' ORDER BY closed_at DESC LIMIT 20"
        ).fetchall()]

        return render_template("index.html",
            daily_pnl=daily_pnl, trade_count=trade_count,
            open_positions=open_positions, signals=signals,
            closed_trades=closed_trades,
            now=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    finally:
        conn.close()


@views_bp.route("/live/<pair>")
def live(pair):
    """Live candlestick chart page."""
    pairs = _get_pairs()
    # Convert URL-safe pair format back (BTC-USDT:USDT -> BTC/USDT:USDT)
    actual_pair = pair.replace("-", "/")
    timeframe = "5m"  # Default
    return render_template("live.html", pair=actual_pair, pairs=pairs, timeframe=timeframe)


@views_bp.route("/backtest")
@views_bp.route("/backtest/<run_id>")
def backtest(run_id=None):
    """Backtest page - config form or results."""
    pairs = _get_pairs()
    backtest_result = None

    if run_id:
        conn = _get_db()
        if conn:
            try:
                import json
                row = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
                if row:
                    backtest_result = dict(row)
                    config = json.loads(backtest_result.get("config", "{}"))
                    backtest_result["config"] = config
                    backtest_result["equity_curve"] = config.get("equity_curve", [])

                    # Get trades
                    trades = [dict(r) for r in conn.execute(
                        "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY entry_time",
                        (run_id,)
                    ).fetchall()]
                    for t in trades:
                        t["scores"] = json.loads(t.get("scores", "{}"))
                    backtest_result["trades"] = trades
            finally:
                conn.close()

    return render_template("backtest.html", pairs=pairs, backtest_result=backtest_result)


@views_bp.route("/backtests")
def backtest_list():
    """Past backtest runs."""
    conn = _get_db()
    runs = []
    if conn:
        try:
            runs = [dict(r) for r in conn.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT 50"
            ).fetchall()]
        except Exception:
            pass
        finally:
            conn.close()
    return render_template("backtest_list.html", runs=runs)


@views_bp.route("/trades")
def trades():
    """Trade history page."""
    from flask import request
    pairs = _get_pairs()

    conn = _get_db()
    trade_list = []
    if conn:
        try:
            query = "SELECT * FROM trades WHERE 1=1"
            params = []

            pair_filter = request.args.get("pair")
            if pair_filter:
                query += " AND pair = ?"
                params.append(pair_filter)

            dir_filter = request.args.get("direction")
            if dir_filter:
                query += " AND direction = ?"
                params.append(dir_filter)

            status_filter = request.args.get("status")
            if status_filter:
                query += " AND status = ?"
                params.append(status_filter)

            query += " ORDER BY opened_at DESC LIMIT 100"
            trade_list = [dict(r) for r in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    return render_template("trades.html", trades=trade_list, pairs=pairs)


@views_bp.route("/signals")
def signals():
    """Signals log page."""
    from flask import request
    pairs = _get_pairs()

    conn = _get_db()
    signal_list = []
    if conn:
        try:
            query = "SELECT * FROM signals WHERE 1=1"
            params = []

            pair_filter = request.args.get("pair")
            if pair_filter:
                query += " AND pair = ?"
                params.append(pair_filter)

            dir_filter = request.args.get("direction")
            if dir_filter:
                query += " AND direction = ?"
                params.append(dir_filter)

            query += " ORDER BY timestamp DESC LIMIT 100"
            signal_list = [dict(r) for r in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    return render_template("signals.html", signals=signal_list, pairs=pairs)
