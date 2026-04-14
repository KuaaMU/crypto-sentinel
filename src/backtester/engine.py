"""
Backtest engine: orchestrates historical data fetching and Backtrader execution.
"""
import logging
import uuid
from datetime import datetime, timezone

import backtrader as bt

from src.backtester.data_feed import HistoricalDataFeed
from src.backtester.strategy import CryptoSentinelStrategy
from src.backtester.results import BacktestResult, compute_metrics
from src.backtester.historical_sentiment import fetch_historical_fear_greed
from src.config import AppConfig, load_config, ScoringWeights, TradingConfig, ExitConfig
from src.execution.exchange import create_exchange, close_exchange
from src.storage.database import (
    save_backtest_run, save_backtest_trades,
    save_ohlcv_cache, load_ohlcv_cache,
)

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Orchestrate backtest runs using historical data and Backtrader."""

    def __init__(self, config: AppConfig):
        self._config = config

    async def run(
        self,
        pair: str,
        timeframe: str,
        start_date: str,         # "2025-01-01"
        end_date: str,           # "2025-01-31"
        initial_balance: float = 10000.0,
        scoring_weights: ScoringWeights | None = None,
        entry_threshold: float | None = None,
        atr_multiplier: float | None = None,
        trend_filter: bool = True,
        cooldown_bars: int = 6,
        max_hold_minutes: int | None = None,
        trail_after_atr: float = 1.0,
        commission: float = 0.001,
    ) -> BacktestResult:
        """Run a backtest.

        Steps:
        1. Fetch historical OHLCV data (with caching)
        2. Load data into Backtrader
        3. Run CryptoSentinelStrategy
        4. Collect results
        5. Save to database
        6. Return BacktestResult
        """
        run_id = uuid.uuid4().hex[:12]
        logger.info("Starting backtest %s: %s %s %s→%s", run_id, pair, timeframe, start_date, end_date)

        # Use provided weights or defaults from config
        weights = scoring_weights or self._config.scoring

        # Override entry threshold if provided
        trading_config = self._config.trading
        if entry_threshold is not None or max_hold_minutes is not None:
            trading_config = TradingConfig(
                base_leverage=trading_config.base_leverage,
                max_leverage=trading_config.max_leverage,
                max_positions=trading_config.max_positions,
                max_position_pct=trading_config.max_position_pct,
                daily_loss_limit=trading_config.daily_loss_limit,
                entry_conviction_threshold=(
                    entry_threshold
                    if entry_threshold is not None
                    else trading_config.entry_conviction_threshold
                ),
                exit_conviction_threshold=trading_config.exit_conviction_threshold,
                max_hold_minutes=(
                    max_hold_minutes
                    if max_hold_minutes is not None
                    else trading_config.max_hold_minutes
                ),
            )

        # 1. Fetch OHLCV data (use paper mode for public-only access)
        exchange = await create_exchange(self._config.exchange, trading_mode="paper")
        try:
            feed = HistoricalDataFeed(exchange)
            ohlcv_data = await feed.fetch_ohlcv_cached(
                pair, timeframe, start_date, end_date,
                db_save_fn=_save_cache_wrapper,
                db_load_fn=load_ohlcv_cache,
            )
        finally:
            await close_exchange(exchange)

        if not ohlcv_data or len(ohlcv_data) < 60:
            raise ValueError(f"Insufficient data for backtest: {len(ohlcv_data or [])} candles (need >= 60)")

        logger.info("Loaded %d candles for %s", len(ohlcv_data), pair)

        # 2. Fetch historical Fear & Greed data for realistic sentiment
        proxy = self._config.exchange.proxy or self._config.collectors.proxy or ""
        fg_history = fetch_historical_fear_greed(days=365, proxy=proxy)
        if fg_history:
            logger.info("Loaded %d days of historical F&G for sentiment", len(fg_history))
        else:
            logger.warning("No historical F&G data - using neutral sentiment defaults")

        # Override ATR multiplier if provided
        exit_config = self._config.exit_strategy
        if atr_multiplier is not None:
            exit_config = ExitConfig(
                partial_tp_levels=exit_config.partial_tp_levels,
                trailing_atr_multiplier=atr_multiplier,
                trailing_atr_period=exit_config.trailing_atr_period,
            )

        # 3. Set up Backtrader
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(initial_balance)
        cerebro.broker.setcommission(commission=commission)

        # Convert OHLCV to pandas DataFrame for bt.feeds.PandasData
        import pandas as pd
        df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('datetime', inplace=True)
        df = df[['open', 'high', 'low', 'close', 'volume']]

        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)

        # 4. Add strategy
        cerebro.addstrategy(
            CryptoSentinelStrategy,
            pair=pair,
            scoring_weights=weights,
            trading_config=trading_config,
            exit_config=exit_config,
            lookback=100,
            fg_history=fg_history,
            trend_filter=trend_filter,
            cooldown_bars=cooldown_bars,
            trail_after_atr=trail_after_atr,
        )

        # 5. Run backtest (tradehistory=False avoids Python 3.10+ incompatibility)
        results = cerebro.run(tradehistory=False)
        strategy = results[0]

        # 5. Collect results
        trades = strategy.backtest_trades
        equity = strategy.equity_curve
        final_balance = cerebro.broker.getvalue()

        metrics = compute_metrics(trades, initial_balance, equity)

        config_snapshot = {
            "scoring_weights": {
                "sentiment": weights.sentiment,
                "whale": weights.whale,
                "technical": weights.technical,
            },
            "entry_threshold": trading_config.entry_conviction_threshold,
            "exit_threshold": trading_config.exit_conviction_threshold,
            "leverage": f"{trading_config.base_leverage}-{trading_config.max_leverage}x",
            "atr_multiplier": exit_config.trailing_atr_multiplier,
            "trend_filter": trend_filter,
            "cooldown_bars": cooldown_bars,
            "commission": f"{commission * 100:.2f}%",
        }

        result = BacktestResult(
            id=run_id,
            pair=pair,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_balance=initial_balance,
            final_balance=round(final_balance, 2),
            metrics=metrics,
            trades=tuple(trades),
            equity_curve=tuple(equity),
            config=config_snapshot,
        )

        # 6. Save to database
        # save_backtest_run expects top-level metric fields via _get_attr_or_key,
        # so build a flat dict that includes both result fields and metrics.
        try:
            run_record = _build_run_record(result)
            await save_backtest_run(run_record)
            await save_backtest_trades(run_id, trades)
            logger.info("Backtest %s saved: %.2f%% return, %d trades", run_id, metrics.total_return_pct, metrics.total_trades)
        except Exception as e:
            logger.warning("Failed to save backtest results: %s", e)

        return result


def _build_run_record(result: BacktestResult) -> dict:
    """Flatten BacktestResult into a dict matching save_backtest_run expectations.

    save_backtest_run reads total_return_pct, sharpe_ratio, etc. at the top
    level via _get_attr_or_key.  BacktestResult nests those inside .metrics,
    so we project them outward here.
    """
    return {
        "id": result.id,
        "pair": result.pair,
        "timeframe": result.timeframe,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "initial_balance": result.initial_balance,
        "final_balance": result.final_balance,
        "total_return_pct": result.metrics.total_return_pct,
        "sharpe_ratio": result.metrics.sharpe_ratio,
        "max_drawdown_pct": result.metrics.max_drawdown_pct,
        "win_rate": result.metrics.win_rate,
        "total_trades": result.metrics.total_trades,
        "profit_factor": result.metrics.profit_factor,
        "config": result.config,
        "equity_curve": list(result.equity_curve),
    }


async def _save_cache_wrapper(pair: str, timeframe: str, start_date: str, end_date: str, data: list) -> None:
    """Adapter for HistoricalDataFeed's db_save_fn signature."""
    await save_ohlcv_cache(pair, timeframe, data)
