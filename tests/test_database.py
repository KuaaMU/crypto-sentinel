"""Tests for database operations (new tables)."""
import asyncio
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.storage.database import (
    init_db, save_backtest_run, get_backtest_run, get_backtest_runs,
    save_backtest_trades, get_backtest_trades,
    save_ohlcv_cache, load_ohlcv_cache,
    save_collector_snapshot,
    get_pnl_history, get_trades_filtered, get_signals_filtered,
    get_all_closed_trades,
)

# Use a temporary database for tests
TEST_DB = Path("data/test_trades.db")


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """Use a temp directory for test database."""
    test_db = tmp_path / "trades.db"
    with patch("src.storage.database.DB_PATH", test_db):
        asyncio.run(init_db())
        yield test_db
    if test_db.exists():
        test_db.unlink()


class TestBacktestRunCRUD:
    def test_save_and_get(self, setup_test_db):
        with patch("src.storage.database.DB_PATH", setup_test_db):
            run = {
                "id": "test123",
                "pair": "BTC/USDT:USDT",
                "timeframe": "5m",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
                "initial_balance": 10000,
                "final_balance": 11000,
                "total_return_pct": 10.0,
                "sharpe_ratio": 1.5,
                "max_drawdown_pct": 5.0,
                "win_rate": 0.6,
                "total_trades": 20,
                "profit_factor": 2.0,
                "config": {"test": True},
                "equity_curve": [["2025-01-01", 10000], ["2025-01-31", 11000]],
            }
            asyncio.run(save_backtest_run(run))

            result = asyncio.run(get_backtest_run("test123"))
            assert result is not None
            assert result["pair"] == "BTC/USDT:USDT"
            assert result["total_return_pct"] == 10.0

    def test_list_runs(self, setup_test_db):
        with patch("src.storage.database.DB_PATH", setup_test_db):
            for i in range(3):
                asyncio.run(save_backtest_run({
                    "id": f"run{i}",
                    "pair": "BTC/USDT:USDT",
                    "timeframe": "5m",
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-31",
                    "initial_balance": 10000,
                    "final_balance": 10000 + i * 100,
                    "config": {},
                }))

            runs = asyncio.run(get_backtest_runs(limit=10))
            assert len(runs) == 3


class TestOHLVCache:
    def test_save_and_load(self, setup_test_db):
        with patch("src.storage.database.DB_PATH", setup_test_db):
            candles = [
                [1704067200000, 42000, 42500, 41800, 42300, 1000],
                [1704067500000, 42300, 42800, 42100, 42600, 1200],
            ]
            asyncio.run(save_ohlcv_cache("BTC/USDT:USDT", "5m", candles))

            loaded = asyncio.run(load_ohlcv_cache(
                "BTC/USDT:USDT", "5m", "2024-01-01", "2025-01-02"
            ))
            assert len(loaded) == 2
            assert loaded[0][4] == 42300  # close price

    def test_deduplication(self, setup_test_db):
        with patch("src.storage.database.DB_PATH", setup_test_db):
            candles = [[1704067200000, 42000, 42500, 41800, 42300, 1000]]
            asyncio.run(save_ohlcv_cache("BTC/USDT:USDT", "5m", candles))
            asyncio.run(save_ohlcv_cache("BTC/USDT:USDT", "5m", candles))

            loaded = asyncio.run(load_ohlcv_cache(
                "BTC/USDT:USDT", "5m", "2024-01-01", "2025-01-02"
            ))
            assert len(loaded) == 1  # No duplicates


class TestCollectorSnapshots:
    def test_save_snapshot(self, setup_test_db):
        with patch("src.storage.database.DB_PATH", setup_test_db):
            asyncio.run(save_collector_snapshot(
                fear_greed_value=45,
                fear_greed_class="Fear",
                news_sentiment=55.0,
                whale_score=50.0,
                btc_price=42000.0,
                eth_price=2500.0,
                market_data={"test": True},
            ))
            # No assertion needed - just verify no exception


class TestBacktestTrades:
    def test_save_and_get(self, setup_test_db):
        with patch("src.storage.database.DB_PATH", setup_test_db):
            # First create a backtest run
            asyncio.run(save_backtest_run({
                "id": "run1",
                "pair": "BTC/USDT:USDT",
                "timeframe": "5m",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
                "initial_balance": 10000,
                "final_balance": 11000,
                "config": {},
            }))

            trades = [
                {
                    "pair": "BTC/USDT:USDT",
                    "direction": "long",
                    "entry_time": "2025-01-05T10:00:00",
                    "exit_time": "2025-01-05T12:00:00",
                    "entry_price": 42000,
                    "exit_price": 42500,
                    "size": 0.1,
                    "leverage": 2,
                    "pnl": 50,
                    "pnl_pct": 1.19,
                    "exit_reason": "TP hit",
                    "conviction": 0.72,
                    "scores": {"sentiment": 50, "whale": 50, "technical": 68},
                },
            ]
            asyncio.run(save_backtest_trades("run1", trades))

            loaded = asyncio.run(get_backtest_trades("run1"))
            assert len(loaded) == 1
            assert loaded[0]["pnl"] == 50
            assert loaded[0]["scores"]["technical"] == 68
