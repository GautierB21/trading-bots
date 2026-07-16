"""CoinGecko data source for crypto prices and market data."""
import time
from typing import Optional

_LAST_CALL = 0
_MIN_INTERVAL = 2  # 30 calls/min = 2 seconds between calls

try:
    from pycoingecko import CoinGeckoAPI
    _cg = CoinGeckoAPI()
    HAS_PYCOINGECKO = True
except ImportError:
    HAS_PYCOINGECKO = False
    _cg = None


def _rate_limit():
    global _LAST_CALL
    elapsed = time.time() - _LAST_CALL
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _LAST_CALL = time.time()


def is_available():
    return HAS_PYCOINGECKO


def get_top_coins(limit=100, vs_currency="usd"):
    """Get top N coins by market cap with price, 24h change, market cap."""
    if not _cg:
        return []
    _rate_limit()
    try:
        coins = _cg.get_coins_markets(
            vs_currency=vs_currency,
            order="market_cap_desc",
            per_page=limit,
            page=1,
            sparkline=False,
            price_change_percentage="1h,24h,7d,30d",
        )
        result = []
        for c in coins:
            symbol = (c.get("symbol", "") + "-USD").upper()
            result.append({
                "id": c["id"],
                "symbol": symbol,
                "name": c["name"],
                "current_price": c.get("current_price"),
                "market_cap": c.get("market_cap"),
                "market_cap_rank": c.get("market_cap_rank"),
                "price_change_24h": c.get("price_change_percentage_24h_in_currency"),
                "price_change_7d": c.get("price_change_percentage_7d_in_currency"),
                "price_change_30d": c.get("price_change_percentage_30d_in_currency"),
                "total_volume": c.get("total_volume"),
                "circulating_supply": c.get("circulating_supply"),
                "ath": c.get("ath"),
                "ath_change_percentage": c.get("ath_change_percentage"),
            })
        return result
    except Exception as e:
        print(f"[coingecko] Error fetching top coins: {e}")
        return []


def get_market_chart(coin_id, vs_currency="usd", days=365):
    """Daily historical Close price series: list of (timestamp_ms, price).

    CoinGecko's free public tier caps historical range at 365 days (paid
    plans go further) — a strategy asking for period="2y" only gets 1y of
    real crypto history back, but that's still enough for any lookback
    window used here (14-50 days), unlike the single current-price point
    this client returned before."""
    if not _cg:
        return None
    _rate_limit()
    try:
        data = _cg.get_coin_market_chart_by_id(id=coin_id, vs_currency=vs_currency, days=days)
        return data.get("prices", [])
    except Exception as e:
        print(f"[coingecko] Error fetching market chart for {coin_id}: {e}")
        return None


def get_prices(coin_ids=None, vs_currency="usd"):
    """Get current prices for specific coins by ID.
    
    Args:
        coin_ids: list of CoinGecko IDs (e.g. ['bitcoin', 'ethereum'])
                 If None, returns top 100 prices.
    
    Returns:
        dict of coin_id -> price
    """
    if not _cg:
        return {}
    _rate_limit()
    try:
        if coin_ids:
            prices = _cg.get_price(ids=coin_ids, vs_currencies=vs_currency)
            return {k: v.get(vs_currency) for k, v in prices.items()}
        else:
            # Get top 100 prices
            top = get_top_coins(100, vs_currency)
            return {c["id"]: c["current_price"] for c in top if c.get("current_price")}
    except Exception as e:
        print(f"[coingecko] Error fetching prices: {e}")
        return {}


def get_coin_id_from_symbol(symbol):
    """Convert ticker like BTC-USD to CoinGecko ID like 'bitcoin'."""
    mapping = {
        "BTC-USD": "bitcoin",
        "ETH-USD": "ethereum",
        "SOL-USD": "solana",
        "XRP-USD": "ripple",
        "ADA-USD": "cardano",
        "DOGE-USD": "dogecoin",
        "DOT-USD": "polkadot",
        "AVAX-USD": "avalanche-2",
        "LINK-USD": "chainlink",
        "UNI-USD": "uniswap",
        "ATOM-USD": "cosmos",
        "MATIC-USD": "matic-network",
        "SHIB-USD": "shiba-inu",
        "TRX-USD": "tron",
        "ETC-USD": "ethereum-classic",
        "XLM-USD": "stellar",
        "BCH-USD": "bitcoin-cash",
        "LTC-USD": "litecoin",
        "NEAR-USD": "near",
        "APT-USD": "aptos",
        "INJ-USD": "injective-protocol",
        "OP-USD": "optimism",
        "ARB-USD": "arbitrum",
        "PEPE-USD": "pepe",
        "FIL-USD": "filecoin",
        "AAVE-USD": "aave",
        "ALGO-USD": "algorand",
        "AXS-USD": "axie-infinity",
        "SAND-USD": "the-sandbox",
        "MANA-USD": "decentraland",
        "CRV-USD": "curve-dao-token",
        "ICP-USD": "internet-computer",
        "SUI-USD": "sui",
        "SEI-USD": "sei-network",
        "FET-USD": "fetch-ai",
        "GRT-USD": "the-graph",
        "RUNE-USD": "thorchain",
        "EGLD-USD": "elrond-erd-2",
        "FTM-USD": "fantom",
        "EOS-USD": "eos",
        "KAS-USD": "kaspa",
        "MKR-USD": "maker",
        "COMP-USD": "compound-governance-token",
        "YFI-USD": "yearn-finance",
        "SNX-USD": "synthetix-network-token",
        "DYDX-USD": "dydx",
        "ENS-USD": "ethereum-name-service",
        "IMX-USD": "immutable-x",
        "STX-USD": "blockstack",
        "AR-USD": "arweave",
        "RNDR-USD": "render-token",
        "ROSE-USD": "oasis-network",
        "BONK-USD": "bonk",
        "WIF-USD": "dogwifcoin",
        "ORDI-USD": "ordinals",
        "TIA-USD": "celestia",
        "PENDLE-USD": "pendle",
        "JTO-USD": "jito-governance-token",
        "PYTH-USD": "pyth-network",
        "STRK-USD": "starknet",
        "FLOW-USD": "flow",
        "GALA-USD": "gala",
        "CHZ-USD": "chiliz",
        "ENJ-USD": "enjincoin",
        "ZIL-USD": "zilliqa",
        "IOTA-USD": "iota",
        "XMR-USD": "monero",
        "DASH-USD": "dash",
        "ZEC-USD": "zcash",
        "WAVES-USD": "waves",
        "KSM-USD": "kusama",
        "BAT-USD": "basic-attention-token",
        "ZRX-USD": "0x",
        "UMA-USD": "uma",
        "BAL-USD": "balancer",
        "ANKR-USD": "ankr",
        "CELO-USD": "celo",
        "MINA-USD": "mina-protocol",
        "LDO-USD": "lido-dao",
        "FXS-USD": "frax-share",
        "CVX-USD": "convex-finance",
        "1INCH-USD": "1inch",
        "CAKE-USD": "pancakeswap-token",
        "KAVA-USD": "kava",
        "NEO-USD": "neo",
        "VET-USD": "vechain",
        "THETA-USD": "theta-token",
        "XDC-USD": "xdce-crowd-sale",
        "QTUM-USD": "qtum",
        "ZEN-USD": "zencash",
        "ONT-USD": "ontology",
        "IOST-USD": "iostoken",
        "WOO-USD": "woo-network",
        "JOE-USD": "joe",
        "BOBA-USD": "boba-network",
        "AUDIO-USD": "audius",
        "RPL-USD": "rocket-pool",
        "API3-USD": "api3",
        "AGIX-USD": "singularitynet",
        "OCEAN-USD": "ocean-protocol",
    }
    return mapping.get(symbol)


if __name__ == "__main__":
    # Test
    top = get_top_coins(10)
    print(f"Top {len(top)} coins:")
    for c in top:
        print(f"  #{c['market_cap_rank']:3d} {c['symbol']:10s} ${c['current_price']:>8,.2f} | 24h: {c.get('price_change_24h',0):+.2f}%")
    
    # Show the top 100 symbols for reference
    top100 = get_top_coins(100)
    symbols = [c['symbol'] for c in top100]
    print(f"\nTop 100 symbols: {symbols[:10]}...{symbols[-3:]}")
