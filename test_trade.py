"""Quick test: open and close a contract position on OKX sandbox."""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
import ccxt.async_support as ccxt

load_dotenv(Path(__file__).parent / ".env")


async def test_trading():
    exchange = ccxt.okx({
        "apiKey": os.getenv("OKX_API_KEY", ""),
        "secret": os.getenv("OKX_API_SECRET", ""),
        "password": os.getenv("OKX_API_PASSPHRASE", ""),
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
        "aiohttp_proxy": "http://127.0.0.1:7890",
    })
    exchange.set_sandbox_mode(True)

    try:
        await exchange.load_markets()
        print("=== Markets loaded:", len(exchange.markets))

        # 1. Check balance
        balance = await exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        free = usdt.get("free", 0)
        total = usdt.get("total", 0)
        print("=== USDT balance: free={} total={}".format(free, total))

        # 2. Get BTC price
        ticker = await exchange.fetch_ticker("BTC/USDT:USDT")
        btc_price = ticker["last"]
        print("=== BTC/USDT price: {}".format(btc_price))

        # 3. Set leverage to 2x and position mode to net (one-way)
        try:
            await exchange.set_position_mode(False, "BTC/USDT:USDT")
            print("=== Position mode set to net (one-way)")
        except Exception as e:
            print("=== Position mode note: {}".format(e))

        try:
            await exchange.set_leverage(2, "BTC/USDT:USDT", params={"mgnMode": "isolated"})
            print("=== Leverage set to 2x")
        except Exception as e:
            print("=== Leverage set note: {}".format(e))

        # 4. Open LONG: 1 contract = 0.01 BTC
        amount = 0.01
        cost = btc_price * amount
        print("=== Opening LONG 0.01 BTC (~{:.2f} USDT) with 2x leverage...".format(cost))

        order = await exchange.create_market_order(
            "BTC/USDT:USDT", "buy", amount,
            params={"tdMode": "isolated"},
        )
        print("=== Order placed! ID={} status={}".format(order["id"], order["status"]))
        print("    filled={} avg_price={}".format(order.get("filled"), order.get("average")))

        # 5. Check position
        await asyncio.sleep(1)
        positions = await exchange.fetch_positions(["BTC/USDT:USDT"])
        for p in positions:
            contracts = float(p.get("contracts", 0) or 0)
            if contracts > 0:
                print("=== Position: {} side={} contracts={} entry={} unrealizedPnl={}".format(
                    p["symbol"], p["side"], p["contracts"], p["entryPrice"], p.get("unrealizedPnl", 0)
                ))

        # 6. Close position
        print("=== Closing position...")
        close_order = await exchange.create_market_order(
            "BTC/USDT:USDT", "sell", amount,
            params={"tdMode": "isolated", "reduceOnly": True},
        )
        print("=== Close order: ID={} status={}".format(close_order["id"], close_order["status"]))
        print("    filled={} avg_price={}".format(close_order.get("filled"), close_order.get("average")))

        print()
        print("=" * 50)
        print("ALL TESTS PASSED - Contract trading works!")
        print("=" * 50)

    except Exception as e:
        print("ERROR: {}".format(e))
        import traceback
        traceback.print_exc()
    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(test_trading())
