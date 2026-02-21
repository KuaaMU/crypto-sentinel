import logging

import ccxt.async_support as ccxt

from src.config import ExchangeConfig

logger = logging.getLogger(__name__)


async def create_exchange(config: ExchangeConfig) -> ccxt.Exchange:
    """Create and configure CCXT exchange instance for OKX futures."""
    exchange = ccxt.okx({
        "apiKey": config.api_key,
        "secret": config.api_secret,
        "password": config.api_passphrase,
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap",
        },
    })

    if config.sandbox:
        exchange.set_sandbox_mode(True)
        logger.info("Exchange running in SANDBOX (demo) mode")
    else:
        logger.warning("Exchange running in LIVE mode")

    # Verify connection
    try:
        await exchange.load_markets()
        logger.info("Connected to %s, %d markets loaded", config.name, len(exchange.markets))
    except Exception as e:
        logger.error("Failed to connect to exchange: %s", e)
        raise

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
