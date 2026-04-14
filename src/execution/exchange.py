import logging

import ccxt.async_support as ccxt

from src.config import ExchangeConfig

logger = logging.getLogger(__name__)


async def create_exchange(
    config: ExchangeConfig,
    trading_mode: str = "live",
    dry_run_balance: float = 10000.0,
) -> ccxt.Exchange:
    """Create and configure CCXT exchange instance for OKX futures.

    Args:
        config: Exchange configuration.
        trading_mode: "live", "paper", or "dry_run".
            - "live": Real orders on real exchange.
            - "paper"/"dry_run": Real market data, simulated orders.
        dry_run_balance: Virtual starting balance for dry-run mode.
    """
    is_dry_run = trading_mode in ("dry_run", "paper")

    options = {
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap",
        },
    }

    # Only set API keys if not dry-run, or if they exist (for authenticated data)
    if config.api_key:
        options["apiKey"] = config.api_key
        options["secret"] = config.api_secret
        options["password"] = config.api_passphrase

    if config.proxy:
        options["aiohttp_proxy"] = config.proxy
        options["aiohttp_trust_env"] = True
        logger.info("Exchange using proxy: %s", config.proxy)

    exchange = ccxt.okx(options)

    if config.sandbox and not is_dry_run:
        exchange.set_sandbox_mode(True)
        logger.info("Exchange running in SANDBOX (demo) mode")
    elif is_dry_run:
        # Skip fetch_currencies (private endpoint) - not needed for public data
        exchange.has["fetchCurrencies"] = False
        logger.info("Exchange running in DRY-RUN mode (real data, simulated orders)")
    else:
        logger.warning("Exchange running in LIVE mode")

    # Verify connection
    try:
        await exchange.load_markets()
        logger.info("Connected to %s, %d markets loaded", config.name, len(exchange.markets))
    except Exception as e:
        logger.error("Failed to connect to exchange: %s", e)
        raise

    # Wrap with DryRunExchange if needed
    if is_dry_run:
        from src.execution.dry_run import DryRunExchange
        exchange = DryRunExchange(exchange, initial_balance=dry_run_balance)

    return exchange


async def close_exchange(exchange: ccxt.Exchange) -> None:
    """Gracefully close exchange connection."""
    try:
        await exchange.close()
        logger.info("Exchange connection closed")
    except Exception as e:
        logger.error("Error closing exchange: %s", e)


async def get_balance(exchange: ccxt.Exchange) -> float:
    """Get USDT balance."""
    try:
        balance = await exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        free = usdt.get("free", 0) or 0
        logger.debug("USDT balance: %.2f", free)
        return float(free)
    except Exception as e:
        logger.error("Failed to fetch balance: %s", e)
        return 0.0
