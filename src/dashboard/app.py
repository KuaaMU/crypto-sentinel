"""
Crypto Sentinel Dashboard - Flask status page.

Shows live signals, open positions, PnL, and system health.
Run standalone: python -m src.dashboard.app
"""
import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template_string

DB_PATH = Path("data/trades.db")

app = Flask(__name__)

TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crypto Sentinel Dashboard</title>
<meta http-equiv="refresh" content="30">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; }
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 8px; }
  .subtitle { color: #8b949e; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }
  .card h3 { color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
  .card .value { font-size: 28px; font-weight: 700; }
  .positive { color: #3fb950; }
  .negative { color: #f85149; }
  .neutral { color: #d29922; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #21262d; font-size: 14px; }
  th { color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
  tr:hover { background: #1c2128; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; }
  .badge-long { background: #0d3320; color: #3fb950; }
  .badge-short { background: #3d1114; color: #f85149; }
  .badge-neutral { background: #3d2e00; color: #d29922; }
  .badge-enter { background: #0d3320; color: #3fb950; }
  .badge-wait { background: #1c1c1c; color: #8b949e; }
  .badge-open { background: #0d3320; color: #3fb950; }
  .badge-partial { background: #3d2e00; color: #d29922; }
  .section { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 24px; }
  .section h2 { color: #58a6ff; font-size: 18px; margin-bottom: 12px; }
  .empty { color: #484f58; font-style: italic; padding: 20px; text-align: center; }
  .timestamp { color: #484f58; font-size: 12px; text-align: right; margin-top: 16px; }
</style>
</head>
<body>
<div class="container">
  <h1>Crypto Sentinel</h1>
  <p class="subtitle">Sentiment + Whale Driven Trading Dashboard</p>

  <div class="grid">
    <div class="card">
      <h3>Today's PnL</h3>
      <div class="value {{ 'positive' if daily_pnl >= 0 else 'negative' }}">
        {{ '%.2f'|format(daily_pnl) }} USDT
      </div>
    </div>
    <div class="card">
      <h3>Trades Today</h3>
      <div class="value">{{ trade_count }}</div>
    </div>
    <div class="card">
      <h3>Open Positions</h3>
      <div class="value">{{ open_positions|length }}</div>
    </div>
    <div class="card">
      <h3>Recent Signals</h3>
      <div class="value">{{ signals|length }}</div>
    </div>
  </div>

  <div class="section">
    <h2>Open Positions</h2>
    {% if open_positions %}
    <table>
      <thead>
        <tr>
          <th>Pair</th>
          <th>Direction</th>
          <th>Entry Price</th>
          <th>Size</th>
          <th>Leverage</th>
          <th>Conviction</th>
          <th>Stop Loss</th>
          <th>Status</th>
          <th>Opened</th>
        </tr>
      </thead>
      <tbody>
        {% for p in open_positions %}
        <tr>
          <td><strong>{{ p.pair }}</strong></td>
          <td><span class="badge badge-{{ p.direction }}">{{ p.direction|upper }}</span></td>
          <td>{{ '%.4f'|format(p.entry_price) }}</td>
          <td>{{ '%.4f'|format(p.size) }}</td>
          <td>{{ p.leverage }}x</td>
          <td>{{ '%.2f'|format(p.conviction) }}</td>
          <td>{{ '%.4f'|format(p.stop_loss) }}</td>
          <td><span class="badge badge-{{ 'open' if p.status == 'open' else 'partial' }}">{{ p.status }}</span></td>
          <td>{{ p.opened_at[:19] }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="empty">No open positions</p>
    {% endif %}
  </div>

  <div class="section">
    <h2>Recent Signals (Last 30)</h2>
    {% if signals %}
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Pair</th>
          <th>Sentiment</th>
          <th>Whale</th>
          <th>Technical</th>
          <th>Conviction</th>
          <th>Direction</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {% for s in signals %}
        <tr>
          <td>{{ s.timestamp[:19] }}</td>
          <td><strong>{{ s.pair }}</strong></td>
          <td>{{ '%.1f'|format(s.sentiment_score) }}</td>
          <td>{{ '%.1f'|format(s.whale_score) }}</td>
          <td>{{ '%.1f'|format(s.technical_score) }}</td>
          <td class="{{ 'positive' if s.conviction >= 0.65 else ('neutral' if s.conviction >= 0.4 else 'negative') }}">
            {{ '%.3f'|format(s.conviction) }}
          </td>
          <td><span class="badge badge-{{ s.direction }}">{{ s.direction }}</span></td>
          <td><span class="badge badge-{{ s.action }}">{{ s.action }}</span></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="empty">No signals recorded yet. Start the trading engine first.</p>
    {% endif %}
  </div>

  <div class="section">
    <h2>Closed Trades (Last 20)</h2>
    {% if closed_trades %}
    <table>
      <thead>
        <tr>
          <th>Pair</th>
          <th>Direction</th>
          <th>Entry</th>
          <th>Leverage</th>
          <th>PnL</th>
          <th>Exit Reason</th>
          <th>Opened</th>
          <th>Closed</th>
        </tr>
      </thead>
      <tbody>
        {% for t in closed_trades %}
        <tr>
          <td><strong>{{ t.pair }}</strong></td>
          <td><span class="badge badge-{{ t.direction }}">{{ t.direction }}</span></td>
          <td>{{ '%.4f'|format(t.entry_price) }}</td>
          <td>{{ t.leverage }}x</td>
          <td class="{{ 'positive' if t.realized_pnl >= 0 else 'negative' }}">
            {{ '%.2f'|format(t.realized_pnl) }} USDT
          </td>
          <td>{{ t.exit_reason or '-' }}</td>
          <td>{{ t.opened_at[:19] }}</td>
          <td>{{ (t.closed_at[:19] if t.closed_at else '-') }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="empty">No closed trades yet</p>
    {% endif %}
  </div>

  <p class="timestamp">Last updated: {{ now }} | Auto-refresh every 30s</p>
</div>
</body>
</html>
"""


def _get_db():
    """Get a synchronous SQLite connection for the dashboard."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _query_open_positions(conn):
    cursor = conn.execute(
        "SELECT * FROM trades WHERE status != 'closed' ORDER BY opened_at DESC"
    )
    return [dict(r) for r in cursor.fetchall()]


def _query_closed_trades(conn, limit=20):
    cursor = conn.execute(
        "SELECT * FROM trades WHERE status = 'closed' ORDER BY closed_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in cursor.fetchall()]


def _query_recent_signals(conn, limit=30):
    cursor = conn.execute(
        "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in cursor.fetchall()]


def _query_daily_pnl(conn):
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    cursor = conn.execute(
        "SELECT total_pnl, trade_count FROM daily_pnl WHERE date = ?",
        (today,),
    )
    row = cursor.fetchone()
    if row:
        return dict(row)
    return {"total_pnl": 0.0, "trade_count": 0}


@app.route("/")
def index():
    conn = _get_db()
    if conn is None:
        return render_template_string(
            TEMPLATE,
            daily_pnl=0,
            trade_count=0,
            open_positions=[],
            signals=[],
            closed_trades=[],
            now=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

    try:
        open_positions = _query_open_positions(conn)
        closed_trades = _query_closed_trades(conn)
        signals = _query_recent_signals(conn)
        pnl_info = _query_daily_pnl(conn)

        return render_template_string(
            TEMPLATE,
            daily_pnl=pnl_info["total_pnl"],
            trade_count=pnl_info["trade_count"],
            open_positions=open_positions,
            signals=signals,
            closed_trades=closed_trades,
            now=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )
    finally:
        conn.close()


@app.route("/api/status")
def api_status():
    """JSON API endpoint for programmatic access."""
    conn = _get_db()
    if conn is None:
        return {"status": "no_database", "message": "Start the trading engine first"}

    try:
        open_positions = _query_open_positions(conn)
        pnl_info = _query_daily_pnl(conn)
        return {
            "status": "running",
            "daily_pnl": pnl_info["total_pnl"],
            "trade_count": pnl_info["trade_count"],
            "open_positions": len(open_positions),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
