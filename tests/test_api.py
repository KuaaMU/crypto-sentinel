"""Tests for dashboard API endpoints."""
import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch

from src.dashboard.app import create_app
from src.storage.database import init_db, save_backtest_run


@pytest.fixture
def app(tmp_path):
    """Create Flask test app with temp database."""
    test_db = tmp_path / "trades.db"
    with patch("src.storage.database.DB_PATH", test_db):
        asyncio.run(init_db())

    with patch("src.dashboard.views.DB_PATH", test_db), \
         patch("src.dashboard.api.DB_PATH", test_db):
        app = create_app()
        app.config["TESTING"] = True
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


class TestStatusEndpoint:
    def test_status_no_db(self, client):
        """Status returns no_database when DB doesn't exist."""
        with patch("src.dashboard.api.DB_PATH", Path("/nonexistent/db")):
            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "no_database"

    def test_status_with_db(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "daily_pnl" in data
        assert "timestamp" in data


class TestTradesEndpoint:
    def test_empty_trades(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_trades_with_filters(self, client):
        resp = client.get("/api/trades?pair=BTC/USDT:USDT&direction=long")
        assert resp.status_code == 200


class TestSignalsEndpoint:
    def test_empty_signals(self, client):
        resp = client.get("/api/signals")
        assert resp.status_code == 200
        assert resp.get_json() == []


class TestDailyPnlEndpoint:
    def test_empty_pnl(self, client):
        resp = client.get("/api/daily-pnl")
        assert resp.status_code == 200
        assert resp.get_json() == []


class TestOHLCVEndpoint:
    def test_ohlcv_returns_data(self, client):
        """OHLCV endpoint falls back to live exchange when cache is empty."""
        resp = client.get("/api/ohlcv/BTC-USDT:USDT")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        # Live fallback should return candles (each is [ts, o, h, l, c, v])
        if data:
            assert len(data[0]) == 6


class TestBacktestEndpoints:
    def test_backtest_run_no_body(self, client):
        resp = client.post("/api/backtest/run", content_type="application/json")
        assert resp.status_code == 400

    def test_backtest_missing_dates(self, client):
        resp = client.post("/api/backtest/run",
                          data=json.dumps({"pair": "BTC/USDT:USDT"}),
                          content_type="application/json")
        assert resp.status_code == 400
        assert "required" in resp.get_json()["error"]

    def test_get_nonexistent_backtest(self, client):
        resp = client.get("/api/backtest/nonexistent")
        assert resp.status_code == 404

    def test_list_backtests_empty(self, client):
        resp = client.get("/api/backtests")
        assert resp.status_code == 200
        assert resp.get_json() == []


class TestHTMLPages:
    def test_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_live(self, client):
        resp = client.get("/live/BTC-USDT:USDT")
        assert resp.status_code == 200

    def test_backtest(self, client):
        resp = client.get("/backtest")
        assert resp.status_code == 200

    def test_backtests(self, client):
        resp = client.get("/backtests")
        assert resp.status_code == 200

    def test_trades_page(self, client):
        resp = client.get("/trades")
        assert resp.status_code == 200

    def test_signals_page(self, client):
        resp = client.get("/signals")
        assert resp.status_code == 200
