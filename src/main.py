"""
Crypto Sentinel - Sentiment + Whale Driven Automated Trading System

Main loop: Collect → Analyze → Score → Decide → Execute → Manage Exits
"""
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing config
load_dotenv(Path(__file__).parent.parent / ".env")

from src.config import load_config, AppConfig
from src.collectors.fear_greed import FearGreedCollector
from src.collectors.news_sentiment import NewsSentimentCollector
from src.collectors.whale_tracker import WhaleTracker
from src.collectors.price import PriceCollector
from src.collectors.orderbook import OrderbookCollector
from src.analyzers.sentiment import analyze_sentiment
from src.analyzers.whale import analyze_whale_activity
from src.analyzers.technical import analyze_technical
from src.strategy.signal_generator import generate_signal, should_enter
from src.strategy.risk_manager import calculate_position_size, check_risk_limits
from src.execution.exchange import create_exchange, close_exchange, get_balance
from src.execution.order_manager import open_position, close_position
from src.execution.exit_manager import ExitManager, calculate_stop_loss, calculate_tp_prices, calculate_atr
from src.storage.database import (
    init_db, save_trade, save_signal, get_daily_pnl,
    update_daily_pnl,
)
from src.models import Position, PositionStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/sentinel.log"),
    ],
)
logger = logging.getLogger("sentinel")


class CryptoSentinel:
    """Main trading engine."""

    def __init__(self, config: AppConfig):
        self._config = config
        self._exchange = None
        self._positions: list[Position] = []
        self._exit_manager = ExitManager(
            atr_multiplier=config.exit_strategy.trailing_atr_multiplier,
            max_hold_minutes=config.trading.max_hold_minutes,
        )
        # Collectors
        self._fear_greed = FearGreedCollector(config.collectors.fear_greed_url)
        self._news = NewsSentimentCollector(
            config.collectors.coingecko_base,
            config.collectors.crypto_news_api_key,
        )
        self._whale = WhaleTracker(
            config.collectors.etherscan_api_key,
            config.collectors.etherscan_base,
            config.collectors.min_whale_tx_usd,
        )
        self._price_collector = None
        self._orderbook_collector = None

    async def start(self) -> None:
        """Initialize and start the main trading loop."""
        logger.info("=" * 60)
        logger.info("CRYPTO SENTINEL starting...")
        logger.info("Mode: %s", self._config.trading_mode)
        logger.info("Pairs: %s", ", ".join(self._config.exchange.pairs))
        logger.info("Leverage: %dx-%dx", self._config.trading.base_leverage, self._config.trading.max_leverage)
        logger.info("Entry threshold: %.2f", self._config.trading.entry_conviction_threshold)
        logger.info("=" * 60)

        await init_db()
        self._exchange = await create_exchange(self._config.exchange)
        self._price_collector = PriceCollector(self._exchange, self._config.exchange.pairs)
        self._orderbook_collector = OrderbookCollector(self._exchange, self._config.exchange.pairs)

        # Health check
        await self._health_check()

        try:
            while True:
                await self._run_cycle()
                logger.info(
                    "--- Sleeping %ds until next cycle ---",
                    self._config.collectors.interval_seconds,
                )
                await asyncio.sleep(self._config.collectors.interval_seconds)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await close_exchange(self._exchange)

    async def _health_check(self) -> None:
        """Check all data sources."""
        checks = {
            "Fear&Greed": self._fear_greed.health_check(),
            "News": self._news.health_check(),
            "Whale": self._whale.health_check(),
            "Price": self._price_collector.health_check(),
            "Orderbook": self._orderbook_collector.health_check(),
        }
        results = await asyncio.gather(*checks.values(), return_exceptions=True)
        for name, result in zip(checks.keys(), results):
            status = "OK" if result is True else f"FAIL ({result})"
            logger.info("Health check [%s]: %s", name, status)

    async def _run_cycle(self) -> None:
        """Execute one complete trading cycle."""
        logger.info("=== Cycle started at %s ===", datetime.now(tz=timezone.utc).strftime("%H:%M:%S"))

        # Step 1: Collect data in parallel
        fg_data, news_data, whale_txs, prices, orderbooks = await asyncio.gather(
            self._fear_greed.collect(),
            self._news.collect(),
            self._whale.collect(),
            self._price_collector.collect(),
            self._orderbook_collector.collect(),
        )

        if fg_data:
            logger.info("Fear & Greed: %d (%s)", fg_data.value, fg_data.classification)
        logger.info("Whale txs: %d found", len(whale_txs))
        logger.info("Prices: %d pairs loaded", len(prices))

        # Step 2: Manage existing positions first
        await self._manage_positions(prices, orderbooks)

        # Step 3: Analyze and generate signals for each pair
        balance = await get_balance(self._exchange)
        daily_pnl = await get_daily_pnl()
        daily_pnl_pct = daily_pnl / balance if balance > 0 else 0

        # Sentiment and whale scores are global (same for all pairs)
        sentiment_score = analyze_sentiment(fg_data, news_data)
        whale_score = analyze_whale_activity(whale_txs, orderbooks)

        logger.info("Sentiment: %.1f (%s) | Whale: %.1f (%s)",
                     sentiment_score.value, sentiment_score.direction.value,
                     whale_score.value, whale_score.direction.value)

        for pair in self._config.exchange.pairs:
            # Skip if we already have a position in this pair
            if any(p.pair == pair and p.status != PositionStatus.CLOSED for p in self._positions):
                continue

            # Technical score is per-pair
            ohlcv = await self._price_collector.fetch_ohlcv(pair, "5m", 100)
            tech_score = analyze_technical(ohlcv, pair)

            # Generate combined signal
            signal = generate_signal(
                sentiment_score, whale_score, tech_score,
                self._config.scoring, pair,
            )

            # Log signal
            await save_signal(
                pair, sentiment_score.value, whale_score.value, tech_score.value,
                signal.conviction, signal.direction.value,
                "enter" if should_enter(signal, self._config.trading.entry_conviction_threshold) else "wait",
            )

            logger.info(
                "%s: conviction=%.3f dir=%s | sent=%.0f whale=%.0f tech=%.0f",
                pair, signal.conviction, signal.direction.value,
                sentiment_score.value, whale_score.value, tech_score.value,
            )

            # Check if we should enter
            if not should_enter(signal, self._config.trading.entry_conviction_threshold):
                continue

            # Risk check
            open_count = len([p for p in self._positions if p.status != PositionStatus.CLOSED])
            allowed, reason = check_risk_limits(open_count, daily_pnl_pct, self._config.trading)
            if not allowed:
                logger.info("Skipping %s: %s", pair, reason)
                continue

            # Calculate position size and leverage
            size_usd, leverage = calculate_position_size(signal, balance, self._config.trading)

            # Calculate stop loss and take-profit
            atr = calculate_atr(ohlcv, self._config.exit_strategy.trailing_atr_period)
            if atr <= 0:
                logger.warning("ATR is 0 for %s, skipping", pair)
                continue

            sl = calculate_stop_loss(
                prices[pair].price if pair in prices else 0,
                signal.direction,
                atr,
                self._config.exit_strategy.trailing_atr_multiplier,
            )
            tp_prices = calculate_tp_prices(
                prices[pair].price if pair in prices else 0,
                signal.direction,
                self._config.exit_strategy.partial_tp_levels,
            )

            # Execute!
            position = await open_position(
                self._exchange, signal, size_usd, leverage, sl, tp_prices,
            )
            if position:
                self._positions.append(position)
                await save_trade(position)

    async def _manage_positions(self, prices: dict, orderbooks: dict) -> None:
        """Check and manage all open positions."""
        for position in self._positions:
            if position.status == PositionStatus.CLOSED:
                continue

            pair = position.pair
            if pair not in prices:
                continue

            current_price = prices[pair].price
            ohlcv = await self._price_collector.fetch_ohlcv(pair, "5m", 30)
            atr = calculate_atr(ohlcv, self._config.exit_strategy.trailing_atr_period)

            # Get current conviction for decay check
            # (simplified: use orderbook imbalance as proxy)
            ob = orderbooks.get(pair, {})
            current_conviction = 0.5 + ob.get("imbalance", 0) * 0.3

            # Check all exit conditions
            actions = self._exit_manager.check_exits(
                position, current_price, atr,
                current_conviction,
                self._config.trading.exit_conviction_threshold,
            )

            for action in actions:
                pnl = await close_position(
                    self._exchange, position,
                    amount=action["amount"],
                    reason=action["reason"],
                )
                if pnl != 0:
                    await update_daily_pnl(pnl)
                await save_trade(position)


async def main():
    config = load_config("config.yaml")
    sentinel = CryptoSentinel(config)
    await sentinel.start()


if __name__ == "__main__":
    asyncio.run(main())
