"""Live sandbox test: run 3 cycles, collect data, attempt trades."""
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("live_test")

from src.config import load_config
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
from src.execution.exit_manager import calculate_atr, calculate_stop_loss, calculate_tp_prices
from src.execution.order_manager import open_position
from src.storage.database import (
    init_db, save_trade, save_signal,
    save_collector_snapshot, save_ohlcv_cache,
)

config = load_config("config.yaml")


async def live_test():
    await init_db()
    exchange = await create_exchange(config.exchange)

    price_coll = PriceCollector(exchange, config.exchange.pairs)
    ob_coll = OrderbookCollector(exchange, config.exchange.pairs)
    fg_coll = FearGreedCollector(config.collectors.fear_greed_url, proxy=config.collectors.proxy)
    news_coll = NewsSentimentCollector(
        config.collectors.coingecko_base, config.collectors.crypto_news_api_key,
        proxy=config.collectors.proxy,
    )
    whale_coll = WhaleTracker(
        config.collectors.etherscan_api_key, config.collectors.etherscan_base,
        config.collectors.min_whale_tx_usd, proxy=config.collectors.proxy,
    )

    balance = await get_balance(exchange)
    print(f"\n{'='*60}")
    print(f"  SANDBOX LIVE TEST  |  Balance: {balance:.2f} USDT")
    print(f"  Pairs: {', '.join(config.exchange.pairs)}")
    print(f"  Interval: {config.collectors.interval_seconds}s  Threshold: {config.trading.entry_conviction_threshold}")
    print(f"  Weights: sent={config.scoring.sentiment} whale={config.scoring.whale} tech={config.scoring.technical}")
    print(f"{'='*60}\n")

    for cycle in range(3):
        print(f"\n--- CYCLE {cycle + 1}/3 ---")

        # Parallel data collection
        fg, news, whales, prices, obs = await asyncio.gather(
            fg_coll.collect(), news_coll.collect(), whale_coll.collect(),
            price_coll.collect(), ob_coll.collect(),
        )

        if fg:
            print(f"Fear&Greed: {fg.value} ({fg.classification})")
        print(f"Prices: {len(prices)} pairs loaded | Whale txs: {len(whales)}")

        # Save collector snapshot
        try:
            btc_p = prices.get("BTC/USDT:USDT")
            eth_p = prices.get("ETH/USDT:USDT")
            await save_collector_snapshot(
                fear_greed_value=fg.value if fg else None,
                fear_greed_class=fg.classification if fg else None,
                news_sentiment=news.get("sentiment_score") if isinstance(news, dict) else None,
                whale_score=float(len(whales)),
                btc_price=btc_p.price if btc_p else None,
                eth_price=eth_p.price if eth_p else None,
            )
        except Exception as e:
            logger.warning("Snapshot save error: %s", e)

        # Global scores
        sent_score = analyze_sentiment(fg, news)
        whale_score = analyze_whale_activity(whales, obs)
        print(f"Sentiment: {sent_score.value:.1f} ({sent_score.direction.value}) | "
              f"Whale: {whale_score.value:.1f} ({whale_score.direction.value})")

        # Per-pair analysis
        for pair in config.exchange.pairs:
            ohlcv = await price_coll.fetch_ohlcv(pair, "5m", 100)

            # Cache OHLCV
            if ohlcv:
                try:
                    await save_ohlcv_cache(pair, "5m", ohlcv)
                except Exception:
                    pass

            tech = analyze_technical(ohlcv, pair)
            signal = generate_signal(sent_score, whale_score, tech, config.scoring, pair)
            enter = should_enter(signal, config.trading.entry_conviction_threshold)
            action = "ENTER" if enter else "wait"

            await save_signal(
                pair, sent_score.value, whale_score.value, tech.value,
                signal.conviction, signal.direction.value, action.lower(),
            )

            price = prices.get(pair)
            price_val = f"${price.price:,.2f}" if price else "N/A"
            print(f"  {pair}: {price_val}  tech={tech.value:.1f}({tech.direction.value})  "
                  f"conv={signal.conviction:.3f}  dir={signal.direction.value}  -> {action}")

            if enter and price:
                print(f"  *** SIGNAL: {signal.direction.value.upper()} {pair} ***")
                size_usd, leverage = calculate_position_size(signal, balance, config.trading)
                atr = calculate_atr(ohlcv, config.exit_strategy.trailing_atr_period)
                if atr > 0:
                    sl = calculate_stop_loss(
                        price.price, signal.direction, atr,
                        config.exit_strategy.trailing_atr_multiplier,
                    )
                    tp = calculate_tp_prices(
                        price.price, signal.direction,
                        config.exit_strategy.partial_tp_levels,
                    )
                    print(f"  Size=${size_usd:.2f}  Lev={leverage}x  SL=${sl:.2f}")

                    try:
                        pos = await open_position(exchange, signal, size_usd, leverage, sl, tp)
                        if pos:
                            await save_trade(pos)
                            print(f"  >>> OPENED: id={pos.id} entry=${pos.entry_price:.2f} size={pos.size}")
                    except Exception as e:
                        print(f"  >>> OPEN FAILED: {e}")

        if cycle < 2:
            wait = config.collectors.interval_seconds
            print(f"\nWaiting {wait}s for next cycle...")
            await asyncio.sleep(wait)

    # Final status
    balance_after = await get_balance(exchange)
    print(f"\n{'='*60}")
    print(f"  TEST COMPLETE  |  Final Balance: {balance_after:.2f} USDT")
    print(f"{'='*60}")

    await close_exchange(exchange)


if __name__ == "__main__":
    asyncio.run(live_test())
