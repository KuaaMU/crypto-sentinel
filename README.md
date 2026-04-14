# Crypto Sentinel

Sentiment + whale activity driven automated crypto trading system. Collects market data in real-time, scores trading signals through multi-dimensional analysis, and executes trades with built-in risk management.

## How It Works

```
Collect → Analyze → Score → Decide → Execute → Manage Exits
```

1. **Collect** — Fear & Greed Index, news sentiment, whale transactions, price & orderbook data
2. **Analyze** — Sentiment scoring, whale activity detection, technical indicators (via `ta` library)
3. **Score** — Weighted conviction score (sentiment 20% + whale 20% + technical 60%)
4. **Decide** — Enter when conviction > threshold, respecting risk limits
5. **Execute** — OKX exchange via CCXT, supports dry-run mode
6. **Exit** — Partial take-profit ladder + ATR trailing stop

## Architecture

```
src/
├── collectors/       # Data collection (Fear&Greed, news, whale, price, orderbook)
├── analyzers/        # Sentiment, whale, technical analysis
├── strategy/         # Signal generation & risk management
├── execution/        # Exchange connection, order management, exit strategy
├── backtester/       # Historical backtesting engine
├── dashboard/        # Flask web dashboard (port 5000)
├── storage/          # SQLite database layer
├── config.py         # Configuration loader
└── main.py           # Main trading loop
```

## Quick Start

### Prerequisites

- Python 3.10+
- OKX API keys (for live/dry-run trading)

### Local Setup

```bash
git clone https://github.com/KuaaMU/crypto-sentinel.git
cd crypto-sentinel
pip install -r requirements.txt
```

Create a `.env` file:

```env
OKX_API_KEY=your_api_key
OKX_SECRET=your_secret
OKX_PASSPHRASE=your_passphrase
ETHERSCAN_API_KEY=your_etherscan_key
COINGECKO_API_KEY=your_coingecko_key
```

### Run

```bash
# Live trading (dry-run mode by default)
python -m src.main

# Backtesting
python run_backtest.py

# Dashboard only
flask --app src.dashboard.app run
```

### Docker

```bash
docker compose up -d
# Dashboard available at http://localhost:5000
```

## Configuration

Edit `config.yaml` to adjust:

- **Trading pairs** — BTC/USDT, SOL/USDT, ETH/USDT, XRP/USDT
- **Leverage** — 2x base, 5x max
- **Risk controls** — 30% max position size, -5% daily loss circuit breaker
- **Exit strategy** — 3-tier partial take-profit + ATR trailing stop
- **Scoring weights** — Tune sentiment/whale/technical balance

## Testing

```bash
pytest tests/
```

## Disclaimer

This software is for educational and research purposes. Cryptocurrency trading involves significant risk. Use at your own discretion.

## License

MIT
