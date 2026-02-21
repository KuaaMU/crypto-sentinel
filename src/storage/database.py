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
"""


async def init_db() -> None:
    """Initialize database and create tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
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
