"""
Dashboard JSON API endpoints.
"""
import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

DB_PATH = Path("data/trades.db")

api_bp = Blueprint("api", __name__)


def _get_db():
    """Get synchronous SQLite connection."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@api_bp.route("/status")
def status():
    """System status endpoint."""
    conn = _get_db()
    if not conn:
        return jsonify({"status": "no_database", "message": "Start the trading engine first"})
    try:
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        pnl_row = conn.execute("SELECT total_pnl, trade_count FROM daily_pnl WHERE date = ?", (today,)).fetchone()
        open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status != 'closed'").fetchone()[0]
        return jsonify({
            "status": "running",
            "daily_pnl": dict(pnl_row)["total_pnl"] if pnl_row else 0.0,
            "trade_count": dict(pnl_row)["trade_count"] if pnl_row else 0,
            "open_positions": open_count,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })
    finally:
        conn.close()


@api_bp.route("/ohlcv/<pair>")
def ohlcv(pair):
    """Get OHLCV data for a pair. Tries cache first, falls back to live exchange."""
    actual_pair = pair.replace("-", "/")
    timeframe = request.args.get("timeframe", "5m")
    limit = request.args.get("limit", 500, type=int)

    # Try cache first
    conn = _get_db()
    if conn:
        try:
            rows = conn.execute(
                """SELECT timestamp, open, high, low, close, volume
                   FROM ohlcv_cache
                   WHERE pair = ? AND timeframe = ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (actual_pair, timeframe, limit),
            ).fetchall()
            if rows:
                candles = [[r["timestamp"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in rows]
                return jsonify(candles)
        finally:
            conn.close()

    # Cache empty — fetch live from exchange
    try:
        candles = asyncio.run(_fetch_ohlcv_live(actual_pair, timeframe, limit))
        return jsonify(candles)
    except Exception as exc:
        return jsonify({"error": f"Failed to fetch OHLCV: {exc}"}), 500


async def _fetch_ohlcv_live(pair: str, timeframe: str, limit: int) -> list:
    """Fetch OHLCV directly from exchange (fallback when cache is empty)."""
    from src.config import load_config
    from src.execution.exchange import create_exchange, close_exchange

    config = load_config("config.yaml")
    exchange = await create_exchange(config.exchange, trading_mode="paper")
    try:
        # DryRunExchange wraps real exchange, so fetch_ohlcv works
        candles = await exchange.fetch_ohlcv(pair, timeframe, limit=limit)
        return candles or []
    finally:
        await close_exchange(exchange)


@api_bp.route("/trades")
def trades():
    """Get trades with optional filters."""
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        query = "SELECT * FROM trades WHERE 1=1"
        params = []

        pair = request.args.get("pair")
        if pair:
            query += " AND pair = ?"
            params.append(pair)

        direction = request.args.get("direction")
        if direction:
            query += " AND direction = ?"
            params.append(direction)

        status_val = request.args.get("status")
        if status_val:
            query += " AND status = ?"
            params.append(status_val)

        limit = request.args.get("limit", 100, type=int)
        query += " ORDER BY opened_at DESC LIMIT ?"
        params.append(limit)

        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        return jsonify(rows)
    finally:
        conn.close()


@api_bp.route("/signals")
def signals():
    """Get signals with optional filters."""
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        query = "SELECT * FROM signals WHERE 1=1"
        params = []

        pair = request.args.get("pair")
        if pair:
            query += " AND pair = ?"
            params.append(pair)

        direction = request.args.get("direction")
        if direction:
            query += " AND direction = ?"
            params.append(direction)

        limit = request.args.get("limit", 50, type=int)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        return jsonify(rows)
    finally:
        conn.close()


@api_bp.route("/daily-pnl")
def daily_pnl():
    """Get daily PnL history."""
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        days = request.args.get("days", 30, type=int)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM daily_pnl ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()]
        return jsonify(rows)
    finally:
        conn.close()


@api_bp.route("/backtest/run", methods=["POST"])
def run_backtest():
    """Run a new backtest. Accepts JSON config, returns result."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    pair = data.get("pair", "BTC/USDT:USDT")
    timeframe = data.get("timeframe", "5m")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    initial_balance = data.get("initial_balance", 10000.0)

    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    # Optional: custom scoring weights
    scoring_weights = None
    weights = data.get("scoring_weights")
    if weights:
        from src.config import ScoringWeights
        scoring_weights = ScoringWeights(
            sentiment=weights.get("sentiment", 0.35),
            whale=weights.get("whale", 0.35),
            technical=weights.get("technical", 0.30),
        )

    entry_threshold = data.get("entry_threshold")

    try:
        from src.config import load_config
        from src.backtester.engine import BacktestEngine

        config = load_config("config.yaml")
        engine = BacktestEngine(config)

        # Run async backtest in sync Flask context
        result = asyncio.run(engine.run(
            pair=pair,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_balance=float(initial_balance),
            scoring_weights=scoring_weights,
            entry_threshold=float(entry_threshold) if entry_threshold else None,
        ))

        # Serialize result
        return jsonify({
            "id": result.id,
            "pair": result.pair,
            "timeframe": result.timeframe,
            "start_date": result.start_date,
            "end_date": result.end_date,
            "initial_balance": result.initial_balance,
            "final_balance": result.final_balance,
            "metrics": {
                "total_return_pct": result.metrics.total_return_pct,
                "sharpe_ratio": result.metrics.sharpe_ratio,
                "max_drawdown_pct": result.metrics.max_drawdown_pct,
                "win_rate": result.metrics.win_rate,
                "total_trades": result.metrics.total_trades,
                "profit_factor": result.metrics.profit_factor,
                "avg_trade_pnl": result.metrics.avg_trade_pnl,
            },
            "trades": [
                {
                    "direction": t.direction,
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "size": t.size,
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                    "exit_reason": t.exit_reason,
                    "conviction": t.conviction,
                } for t in result.trades
            ],
            "equity_curve": list(result.equity_curve),
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Backtest failed: {str(e)}"}), 500


@api_bp.route("/backtest/<run_id>")
def get_backtest(run_id):
    """Get a past backtest run."""
    conn = _get_db()
    if not conn:
        return jsonify({"error": "No database"}), 404

    try:
        row = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404

        result = dict(row)
        result["config"] = json.loads(result.get("config", "{}"))
        return jsonify(result)
    finally:
        conn.close()


@api_bp.route("/backtest/<run_id>/trades")
def get_backtest_trades(run_id):
    """Get trades for a backtest run."""
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY entry_time",
            (run_id,)
        ).fetchall()]
        for r in rows:
            r["scores"] = json.loads(r.get("scores", "{}"))
        return jsonify(rows)
    finally:
        conn.close()


@api_bp.route("/backtest/<run_id>/equity")
def get_backtest_equity(run_id):
    """Get equity curve for a backtest run."""
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        row = conn.execute("SELECT config FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return jsonify([])

        config = json.loads(dict(row).get("config", "{}"))
        equity_curve = config.get("equity_curve", [])
        return jsonify(equity_curve)
    finally:
        conn.close()


@api_bp.route("/backtests")
def list_backtests():
    """List past backtest runs."""
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        limit = request.args.get("limit", 50, type=int)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()]
        return jsonify(rows)
    finally:
        conn.close()
