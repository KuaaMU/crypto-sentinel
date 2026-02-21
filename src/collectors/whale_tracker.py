import aiohttp
import logging
import ssl
from datetime import datetime, timezone

from src.collectors.base import BaseCollector
from src.models import WhaleTransaction

logger = logging.getLogger(__name__)


def _make_connector() -> aiohttp.TCPConnector:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ctx)

# Known exchange addresses (subset - extend as needed)
EXCHANGE_ADDRESSES = {
    # Binance hot wallets
    "0x28c6c06298d514db089934071355e5743bf21d60",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549",
    # OKX
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b",
    # Coinbase
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3",
    # Kraken
    "0x2910543af39aba0cd09dbb2d50200b3e800a63d2",
}


class WhaleTracker(BaseCollector):
    """Tracks large ETH transactions via Etherscan API (free, 5 calls/sec)."""

    def __init__(self, api_key: str, base_url: str, min_tx_usd: float = 1_000_000):
        self._api_key = api_key
        self._base_url = base_url
        self._min_tx_usd = min_tx_usd

    async def collect(self) -> list[WhaleTransaction]:
        if not self._api_key:
            logger.debug("No Etherscan API key, skipping whale tracking")
            return []

        try:
            txs = await self._fetch_large_transactions()
            return txs
        except Exception as e:
            logger.error("Whale tracking failed: %s", e)
            return []

    async def _fetch_large_transactions(self) -> list[WhaleTransaction]:
        """Fetch recent ETH transactions from the latest block."""
        params = {
            "module": "proxy",
            "action": "eth_blockNumber",
            "apikey": self._api_key,
        }
        async with aiohttp.ClientSession(connector=_make_connector()) as session:
            # Get latest block number
            async with session.get(self._base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                latest_block = int(data["result"], 16)

            # Get transactions from recent blocks (last ~5 min = ~25 blocks)
            transactions = []
            for block_offset in range(0, 5):
                block_num = hex(latest_block - block_offset)
                block_params = {
                    "module": "proxy",
                    "action": "eth_getBlockByNumber",
                    "tag": block_num,
                    "boolean": "true",
                    "apikey": self._api_key,
                }
                async with session.get(self._base_url, params=block_params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    block_data = await resp.json()

                if not block_data.get("result") or not block_data["result"].get("transactions"):
                    continue

                eth_price = await self._get_eth_price(session)

                for tx in block_data["result"]["transactions"]:
                    value_eth = int(tx.get("value", "0x0"), 16) / 1e18
                    value_usd = value_eth * eth_price

                    if value_usd >= self._min_tx_usd:
                        from_addr = tx.get("from", "").lower()
                        to_addr = tx.get("to", "").lower()

                        transactions.append(WhaleTransaction(
                            tx_hash=tx["hash"],
                            from_addr=from_addr,
                            to_addr=to_addr,
                            value_usd=value_usd,
                            token="ETH",
                            is_exchange_inflow=to_addr in EXCHANGE_ADDRESSES,
                            is_exchange_outflow=from_addr in EXCHANGE_ADDRESSES,
                            timestamp=datetime.now(tz=timezone.utc),
                        ))

            return transactions

    async def _get_eth_price(self, session: aiohttp.ClientSession) -> float:
        """Get current ETH price from CoinGecko."""
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return data["ethereum"]["usd"]
        except Exception:
            return 2000.0  # fallback

    async def health_check(self) -> bool:
        if not self._api_key:
            return False
        try:
            params = {"module": "proxy", "action": "eth_blockNumber", "apikey": self._api_key}
            async with aiohttp.ClientSession(connector=_make_connector()) as session:
                async with session.get(self._base_url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False
