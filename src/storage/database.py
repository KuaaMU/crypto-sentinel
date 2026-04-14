import aiosqlite
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.models import Position, Direction, PositionStatus

logger = logging.getLogger(__name__)

DB_PATH = Path("data/trades.db")

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size REAL NOT NULL,
    leverage INTEGER NOT NULL,
    conviction REAL NOT NULL,
    stop_loss REAL NOT NULL,
    status TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    realized_pnl REAL DEFAULT 0,
    exit_reason TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    pair TEXT NOT NULL,
    sentiment_score REAL,
    whale_score REAL,
    technical_score REAL,
    conviction REAL,
    direction TEXT,
    action TEXT
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    date TEXT PRIMARY KEY,
    total_pnl REAL DEFAULT 0,
    trade_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    initial_balance REAL NOT NULL,
    final_balance REAL NOT NULL,
    total_return_pct REAL,
    sharpe_ratio REAL,
    max_drawdown_pct REAL,
    win_rate REAL,
    total_trades INTEGER,
    profit_factor REAL,
    config TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    pair TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    size REAL NOT NULL,
    leverage INTEGER DEFAULT 1,
    pnl REAL NOT NULL,
    pnl_pct REAL NOT NULL,
    exit_reason TEXT,
    conviction REAL,
    scores TEXT DEFAULT '{}',
    FOREIGN KEY (run_id) REFERENCES backtest_runs(id)
);

CREATE TABLE IF NOT EXISTS ohlcv_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    UNIQUE(pair, timeframe, timestamp)
);

CREATE TABLE IF NOT EXISTS collector_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    fear_greed_value INTEGER,
    fear_greed_class TEXT,
    news_sentiment REAL,
    whale_score REAL,
    btc_price REAL,
    eth_price REAL,
    market_data TEXT DEFAULT '{}'
);
"""


def _get_attr_or_key(obj, name, default=None):
    """Retrieve a value from an object by attribute or dict key."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


async def init_db() -> None:
    """Initialize database and create tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.executescript(CREATE_TABLES)
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)


async def save_trade(position: Position) -> None:
    """Save or update a trade record."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """INSERT OR REPLACE INTO trades
            (id, pair, direction, entry_price, size, leverage, conviction,
             stop_loss, status, opened_at, closed_at, realized_pnl, exit_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                position.id, position.pair, position.direction.value,
                position.entry_price, position.size, position.leverage,
                position.conviction, position.stop_loss, position.status.value,
                position.opened_at.isoformat(),
                position.closed_at.isoformat() if position.closed_at else None,
                position.realized_pnl, position.exit_reason,
            ),
        )
        await db.commit()


async def save_signal(pair: str, sentiment: float, whale: float, technical: float,
                      conviction: float, direction: str, action: str) -> None:
    """Log a signal for analysis."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """INSERT INTO signals (timestamp, pair, sentiment_score, whale_score,
               technical_score, conviction, direction, action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(tz=timezone.utc).isoformat(), pair,
             sentiment, whale, technical, conviction, direction, action),
        )
        await db.commit()


async def get_daily_pnl(date: str | None = None) -> float:
    """Get total PnL for a given date (default: today)."""
    if date is None:
        date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "SELECT total_pnl FROM daily_pnl WHERE date = ?", (date,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0


async def update_daily_pnl(pnl_delta: float) -> None:
    """Add PnL to today's total."""
    date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """INSERT INTO daily_pnl (date, total_pnl, trade_count)
            VALUES (?, ?, 1)
            ON CONFLICT(date) DO UPDATE SET
                total_pnl = total_pnl + ?,
                trade_count = trade_count + 1""",
            (date, pnl_delta, pnl_delta),
        )
        await db.commit()


async def get_open_trades() -> list[dict]:
    """Get all open trades."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trades WHERE status != 'closed' ORDER BY opened_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_recent_signals(limit: int = 50) -> list[dict]:
    """Get recent signals for dashboard."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Backtest run functions
# ---------------------------------------------------------------------------


async def save_backtest_run(result) -> None:
    """Save a backtest run result.

    Accepts a BacktestResult-like object or dict.  The equity_curve, if
    present, is stored inside the config JSON under the key "equity_curve".
    """
    run_id = _get_attr_or_key(result, "id")
    pair = _get_attr_or_key(result, "pair")
    timeframe = _get_attr_or_key(result, "timeframe")
    start_date = _get_attr_or_key(result, "start_date")
    end_date = _get_attr_or_key(result, "end_date")
    initial_balance = _get_attr_or_key(result, "initial_balance")
    final_balance = _get_attr_or_key(result, "final_balance")
    total_return_pct = _get_attr_or_key(result, "total_return_pct")
    sharpe_ratio = _get_attr_or_key(result, "sharpe_ratio")
    max_drawdown_pct = _get_attr_or_key(result, "max_drawdown_pct")
    win_rate = _get_attr_or_key(result, "win_rate")
    total_trades = _get_attr_or_key(result, "total_trades")
    profit_factor = _get_attr_or_key(result, "profit_factor")

    raw_config = _get_attr_or_key(result, "config") or {}
    config = dict(raw_config) if isinstance(raw_config, dict) else json.loads(raw_config)

    equity_curve = _get_attr_or_key(result, "equity_curve")
    if equity_curve is not None:
        config["equity_curve"] = equity_curve

    config_json = json.dumps(config)
    created_at = datetime.now(tz=timezone.utc).isoformat()

    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """INSERT OR REPLACE INTO backtest_runs
            (id, pair, timeframe, start_date, end_date, initial_balance,
             final_balance, total_return_pct, sharpe_ratio, max_drawdown_pct,
             win_rate, total_trades, profit_factor, config, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, pair, timeframe, start_date, end_date,
                initial_balance, final_balance, total_return_pct,
                sharpe_ratio, max_drawdown_pct, win_rate, total_trades,
                profit_factor, config_json, created_at,
            ),
        )
        await db.commit()


async def get_backtest_run(run_id: str) -> dict | None:
    """Get a single backtest run by ID."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM backtest_runs WHERE id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["config"] = json.loads(result.get("config") or "{}")
        return result


async def get_backtest_runs(limit: int = 50) -> list[dict]:
    """Get recent backtest runs, ordered by created_at DESC."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            entry = dict(row)
            entry["config"] = json.loads(entry.get("config") or "{}")
            results.append(entry)
        return results


# ---------------------------------------------------------------------------
# Backtest trade functions
# ---------------------------------------------------------------------------


async def save_backtest_trades(run_id: str, trades: list) -> None:
    """Save backtest trades for a run.

    Each trade is a BacktestTrade-like object or dict with fields:
    pair, direction, entry_time, exit_time, entry_price, exit_price,
    size, leverage, pnl, pnl_pct, exit_reason, conviction, scores.
    """
    rows = []
    for trade in trades:
        scores_raw = _get_attr_or_key(trade, "scores") or {}
        scores_json = json.dumps(scores_raw) if isinstance(scores_raw, dict) else str(scores_raw)
        rows.append((
            run_id,
            _get_attr_or_key(trade, "pair"),
            _get_attr_or_key(trade, "direction"),
            _get_attr_or_key(trade, "entry_time"),
            _get_attr_or_key(trade, "exit_time"),
            _get_attr_or_key(trade, "entry_price"),
            _get_attr_or_key(trade, "exit_price"),
            _get_attr_or_key(trade, "size"),
            _get_attr_or_key(trade, "leverage", 1),
            _get_attr_or_key(trade, "pnl"),
            _get_attr_or_key(trade, "pnl_pct"),
            _get_attr_or_key(trade, "exit_reason"),
            _get_attr_or_key(trade, "conviction"),
            scores_json,
        ))

    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.executemany(
            """INSERT INTO backtest_trades
            (run_id, pair, direction, entry_time, exit_time, entry_price,
             exit_price, size, leverage, pnl, pnl_pct, exit_reason,
             conviction, scores)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await db.commit()


async def get_backtest_trades(run_id: str) -> list[dict]:
    """Get all trades for a backtest run."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY entry_time",
            (run_id,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            entry = dict(row)
            entry["scores"] = json.loads(entry.get("scores") or "{}")
            results.append(entry)
        return results


# ---------------------------------------------------------------------------
# OHLCV cache functions
# ---------------------------------------------------------------------------


async def save_ohlcv_cache(pair: str, timeframe: str, candles: list[list]) -> None:
    """Cache OHLCV data. Uses INSERT OR IGNORE for deduplication.

    Each candle is expected as [timestamp, open, high, low, close, volume].
    """
    rows = [
        (pair, timeframe, int(c[0]), float(c[1]), float(c[2]),
         float(c[3]), float(c[4]), float(c[5]))
        for c in candles
    ]
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.executemany(
            """INSERT OR IGNORE INTO ohlcv_cache
            (pair, timeframe, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await db.commit()


async def load_ohlcv_cache(
    pair: str, timeframe: str, start_date: str, end_date: str,
) -> list[list]:
    """Load cached OHLCV data for a date range.

    start_date and end_date are ISO date strings (e.g. "2024-01-01").
    They are converted to millisecond timestamps for querying.
    Returns a list of [timestamp, open, high, low, close, volume] lists.
    """
    start_ms = int(
        datetime.fromisoformat(start_date)
        .replace(tzinfo=timezone.utc)
        .timestamp() * 1000
    )
    end_ms = int(
        datetime.fromisoformat(end_date)
        .replace(tzinfo=timezone.utc)
        .timestamp() * 1000
    )

    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            """SELECT timestamp, open, high, low, close, volume
            FROM ohlcv_cache
            WHERE pair = ? AND timeframe = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp""",
            (pair, timeframe, start_ms, end_ms),
        )
        rows = await cursor.fetchall()
        return [list(row) for row in rows]


# ---------------------------------------------------------------------------
# Collector snapshot functions
# ---------------------------------------------------------------------------


async def save_collector_snapshot(
    fear_greed_value: int | None,
    fear_greed_class: str | None,
    news_sentiment: float | None,
    whale_score: float | None,
    btc_price: float | None,
    eth_price: float | None,
    market_data: dict | None = None,
) -> None:
    """Save a collector data snapshot."""
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    market_data_json = json.dumps(market_data) if market_data else "{}"

    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """INSERT INTO collector_snapshots
            (timestamp, fear_greed_value, fear_greed_class, news_sentiment,
             whale_score, btc_price, eth_price, market_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp, fear_greed_value, fear_greed_class,
                news_sentiment, whale_score, btc_price, eth_price,
                market_data_json,
            ),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Additional query functions
# ---------------------------------------------------------------------------


async def get_pnl_history(days: int = 30) -> list[dict]:
    """Get daily PnL history for the last N days."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM daily_pnl ORDER BY date DESC LIMIT ?", (days,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_trades_filtered(
    pair: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Get trades with optional filters."""
    conditions: list[str] = []
    params: list = []

    if pair is not None:
        conditions.append("pair = ?")
        params.append(pair)
    if direction is not None:
        conditions.append("direction = ?")
        params.append(direction)
    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"SELECT * FROM trades{where_clause} ORDER BY opened_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_signals_filtered(
    pair: str | None = None,
    direction: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Get signals with optional filters."""
    conditions: list[str] = []
    params: list = []

    if pair is not None:
        conditions.append("pair = ?")
        params.append(pair)
    if direction is not None:
        conditions.append("direction = ?")
        params.append(direction)

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"SELECT * FROM signals{where_clause} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_closed_trades(limit: int = 100) -> list[dict]:
    """Get all closed trades."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trades WHERE status = 'closed' ORDER BY closed_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_backtest_equity(run_id: str) -> list[dict]:
    """Get equity curve for a backtest run from the backtest_runs table.

    The equity curve is stored as a JSON field inside the backtest_runs config
    under the key "equity_curve".  This retrieves it and returns as a list of
    {timestamp, balance} dicts.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "SELECT config FROM backtest_runs WHERE id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return []

        config = json.loads(row[0] or "{}")
        equity_curve = config.get("equity_curve", [])

        if not isinstance(equity_curve, list):
            return []

        return [
            {"timestamp": point.get("timestamp"), "balance": point.get("balance")}
            for point in equity_curve
            if isinstance(point, dict)
        ]
