"""Lookup product names and info from tickers."""
import yfinance as yf
from functools import lru_cache

# Static mapping for speed (avoid yfinance calls)
TICKER_NAMES = {
    # 🇺🇸 US Big Tech
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.", "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.", "NVDA": "NVIDIA Corp.", "META": "Meta Platforms",
    "TSLA": "Tesla Inc.", "NFLX": "Netflix Inc.",
    # 🇺🇸 US Finance
    "JPM": "JPMorgan Chase", "GS": "Goldman Sachs", "MS": "Morgan Stanley",
    "BAC": "Bank of America", "BRK-B": "Berkshire Hathaway B",
    "V": "Visa Inc.", "MA": "Mastercard Inc.", "BLK": "BlackRock Inc.",
    "AXP": "American Express", "C": "Citigroup Inc.",
    # 🇺🇸 US Large Caps
    "WMT": "Walmart Inc.", "JNJ": "Johnson & Johnson", "PG": "Procter & Gamble",
    "KO": "Coca-Cola Co.", "PEP": "PepsiCo Inc.", "MCD": "McDonald's Corp.",
    "DIS": "Walt Disney Co.", "BA": "Boeing Co.", "CAT": "Caterpillar Inc.",
    "GE": "General Electric", "XOM": "Exxon Mobil", "CVX": "Chevron Corp.",
    "UNH": "UnitedHealth Group", "HD": "Home Depot Inc.", "INTC": "Intel Corp.",
    "CSCO": "Cisco Systems", "ORCL": "Oracle Corp.", "IBM": "IBM Corp.",
    "ADBE": "Adobe Inc.", "CRM": "Salesforce Inc.", "AMD": "Advanced Micro Devices",
    "COST": "Costco Wholesale", "SBUX": "Starbucks Corp.", "NKE": "Nike Inc.",
    # 🇫🇷 France
    "MC.PA": "LVMH Moët Hennessy", "TTE.PA": "TotalEnergies SE",
    "SAN.PA": "Sanofi SA", "AIR.PA": "Airbus SE", "BNP.PA": "BNP Paribas SA",
    "SU.PA": "Schneider Electric", "OR.PA": "L'Oréal SA",
    "CS.PA": "AXA SA", "DG.PA": "Vinci SA", "BN.PA": "Danone SA",
    "RNO.PA": "Renault SA", "CAP.PA": "Capgemini SE",
    "SAF.PA": "Safran SA", "KER.PA": "Kering SA", "VIE.PA": "Veolia Environnement",
    "GLE.PA": "Société Générale", "ACA.PA": "Crédit Agricole SA",
    "ENGI.PA": "Engie SA", "ORA.PA": "Orange SA",
    "ML.PA": "Michelin SCA", "STLAP.PA": "Stellantis N.V.",
    "HO.PA": "Thales SA", "LR.PA": "Legrand SA", "DSY.PA": "Dassault Systèmes",
    "PUB.PA": "Publicis Groupe", "RMS.PA": "Hermès International",
    "SGO.PA": "Saint-Gobain", "EDF.PA": "EDF SA",
    # 🇩🇪 Germany
    "SAP.DE": "SAP SE", "SIE.DE": "Siemens AG", "ALV.DE": "Allianz SE",
    "BMW.DE": "Bayerische Motoren Werke", "VOW3.DE": "Volkswagen AG",
    "DTE.DE": "Deutsche Telekom", "DB1.DE": "Deutsche Börse AG",
    "LIN.DE": "Linde plc", "ADS.DE": "Adidas AG",
    # 🇬🇧 UK
    "SHEL.L": "Shell plc", "HSBA.L": "HSBC Holdings", "AZN.L": "AstraZeneca plc",
    "ULVR.L": "Unilever plc", "BP.L": "BP plc", "GSK.L": "GSK plc",
    "RIO.L": "Rio Tinto Group", "BARC.L": "Barclays plc",
    "LLOY.L": "Lloyds Banking Group",
    # 🇳🇱 Netherlands
    "ASML.AS": "ASML Holding", "ADYEN.AS": "Adyen N.V.",
    # 🇨🇭 Switzerland
    "NESN.SW": "Nestlé SA", "NOVN.SW": "Novartis AG", "UBSG.SW": "UBS Group AG",
    # 🇯🇵 Japan
    "7203.T": "Toyota Motor Corp.", "6758.T": "Sony Group Corp.",
    "9984.T": "SoftBank Group Corp.",
    # 🇭🇰 Hong Kong
    "0700.HK": "Tencent Holdings", "1299.HK": "AIA Group Ltd.",
    "0005.HK": "HSBC Holdings", "2318.HK": "Ping An Insurance",
    "9988.HK": "Alibaba Group",
    # ETFs
    "SPY": "SPDR S&P 500 ETF", "QQQ": "Invesco QQQ Trust (Nasdaq)",
    "IWM": "iShares Russell 2000 ETF", "EEM": "iShares MSCI Emerging Markets",
    "VWO": "Vanguard FTSE Emerging Markets", "VNQ": "Vanguard Real Estate ETF",
    "GLD": "SPDR Gold Trust", "TLT": "iShares 20+ Year Treasury Bond",
    "DIA": "SPDR Dow Jones Industrial Average",
    "VWCE.DE": "Vanguard FTSE All-World UCITS",
    "CW8.PA": "Amundi MSCI World UCITS", "ESE.PA": "Lyxor CAC 40 UCITS",
    # Cryptos
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "XRP-USD": "Ripple", "ADA-USD": "Cardano", "DOGE-USD": "Dogecoin",
    "DOT-USD": "Polkadot", "AVAX-USD": "Avalanche", "LINK-USD": "Chainlink",
    "UNI-USD": "Uniswap", "ATOM-USD": "Cosmos", "MATIC-USD": "Polygon",
    "BNB-USD": "BNB (Binance Coin)", "SHIB-USD": "Shiba Inu",
    "TRX-USD": "Tron", "ETC-USD": "Ethereum Classic",
    "XLM-USD": "Stellar", "BCH-USD": "Bitcoin Cash",
    "LTC-USD": "Litecoin", "NEAR-USD": "NEAR Protocol",
    "APT-USD": "Aptos", "SUI-USD": "Sui", "SEI-USD": "Sei",
    "OP-USD": "Optimism", "ARB-USD": "Arbitrum",
    "AAVE-USD": "Aave", "CRV-USD": "Curve DAO Token",
    "MKR-USD": "Maker", "COMP-USD": "Compound",
    "PEPE-USD": "Pepe", "WIF-USD": "Dogwifcoin",
    "INJ-USD": "Injective", "FET-USD": "Fetch.ai",
    "GRT-USD": "The Graph", "RUNE-USD": "THORChain",
    "EGLD-USD": "Elrond eGold", "FTM-USD": "Fantom",
    "EOS-USD": "EOS.IO", "KAS-USD": "Kaspa",
    "ALGO-USD": "Algorand", "ICP-USD": "Internet Computer",
    "FIL-USD": "Filecoin", "NEAR-USD": "NEAR Protocol",
    "APT-USD": "Aptos", "SAND-USD": "The Sandbox",
    "MANA-USD": "Decentraland", "AXS-USD": "Axie Infinity",
    "USDT-USD": "Tether USD", "USDC-USD": "USD Coin",
    "DAI-USD": "Dai Stablecoin",
    # Cryptos Kraken WS
    "XBT/USD": "Bitcoin", "ETH/USD": "Ethereum", "SOL/USD": "Solana",
    "XRP/USD": "Ripple", "ADA/USD": "Cardano", "AVAX/USD": "Avalanche",
    "DOT/USD": "Polkadot", "LINK/USD": "Chainlink", "MATIC/USD": "Polygon",
    "ATOM/USD": "Cosmos", "NEAR/USD": "NEAR Protocol", "APT/USD": "Aptos",
    "SUI/USD": "Sui", "AAVE/USD": "Aave", "UNI/USD": "Uniswap",
    "DOGE/USD": "Dogecoin", "SHIB/USD": "Shiba Inu", "BCH/USD": "Bitcoin Cash",
    "LTC/USD": "Litecoin", "ETC/USD": "Ethereum Classic",
    "FIL/USD": "Filecoin", "ICP/USD": "Internet Computer",
    "KAS/USD": "Kaspa", "TRX/USD": "Tron", "FLOKI/USD": "Floki",
    "BONK/USD": "Bonk", "PEPE/USD": "Pepe", "WIF/USD": "Dogwifhat",
    "JUP/USD": "Jupiter", "TAO/USD": "Bittensor", "RENDER/USD": "Render",
    "ONDO/USD": "Ondo", "ENA/USD": "Ethena", "SEI/USD": "Sei",
    "WLD/USD": "Worldcoin", "SAND/USD": "The Sandbox", "MANA/USD": "Decentraland",
    "CHZ/USD": "Chiliz", "GALA/USD": "Gala", "IMX/USD": "Immutable X",
    "CRV/USD": "Curve DAO", "LDO/USD": "Lido DAO", "EGLD/USD": "Elrond",
    "MINA/USD": "Mina", "ZEC/USD": "Zcash", "XMR/USD": "Monero",
    "DASH/USD": "Dash", "KSM/USD": "Kusama", "BLUR/USD": "Blur",
    "ASTR/USD": "Astar", "STX/USD": "Stacks", "COMP/USD": "Compound",
    "YFI/USD": "Yearn Finance", "SNX/USD": "Synthetix",
    "SUSHI/USD": "SushiSwap", "CAKE/USD": "PancakeSwap",
    "FXS/USD": "Frax Share", "GNO/USD": "Gnosis", "BAT/USD": "Basic Attention",
    "ZRX/USD": "0x", "VET/USD": "VeChain", "THETA/USD": "Theta Network",
    "KAVA/USD": "Kava", "OCEAN/USD": "Ocean Protocol",
    "HNT/USD": "Helium", "QTUM/USD": "Qtum", "ICX/USD": "ICON",
    "WAXP/USD": "WAX", "MASK/USD": "Mask Network",
    "STORJ/USD": "Storj", "RLC/USD": "iExec RLC",
    "1INCH/USD": "1inch", "ENJ/USD": "Enjin Coin", "ALGO/USD": "Algorand",
    "FLOW/USD": "Flow", "ANKR/USD": "Ankr", "BAND/USD": "Band Protocol",
    "NMR/USD": "Numeraire", "GRT/USD": "The Graph", "RUNE/USD": "THORChain",
    "XLM/USD": "Stellar", "DYDX/USD": "dYdX", "UMA/USD": "UMA",
    "PAXG/USD": "PAX Gold", "XAUT/USD": "Tether Gold",
    "BNB/USD": "BNB", "CRO/USD": "Cronos", "OKB/USD": "OKB",
    "TON/USD": "Toncoin", "STRK/USD": "StarkNet", "TIA/USD": "Celestia",
    "MNT/USD": "Mantle", "POL/USD": "POL (ex-MATIC)",
    "HBAR/USD": "Hedera", "FET/USD": "Fetch.ai", "ARB/USD": "Arbitrum",
    "OP/USD": "Optimism", "INJ/USD": "Injective", "EOS/USD": "EOS",
    "XTZ/USD": "Tezos", "ALGO/USD": "Algorand",
    "XDC/USD": "XDC Network", "FLR/USD": "Flare", "JTO/USD": "Jito",
    "PYTH/USD": "Pyth Network", "WEN/USD": "Wen", "TNSR/USD": "Tensor",
    "STRD/USD": "Stride", "OSMO/USD": "Osmosis", "JUNO/USD": "Juno",
    "SCRT/USD": "Secret", "AKT/USD": "Akash Network",
    "EIGEN/USD": "EigenLayer", "ETHFI/USD": "Ether.fi",
    "PENDLE/USD": "Pendle", "GMX/USD": "GMX", "JOE/USD": "Trader Joe",
    "SPELL/USD": "Spell", "HFT/USD": "Hashflow",
    "LSETH/USD": "Liquid Staked ETH", "MSOL/USD": "Marinade Staked SOL",
    "TBTC/USD": "tBTC", "WBTC/USD": "Wrapped Bitcoin",
    "DAI/USD": "Dai", "USDC/USD": "USD Coin", "USDT/USD": "Tether",
}


def get_market(symbol):
    """Return market flag and name for a symbol."""
    if symbol.endswith("-USD"):
        if symbol in ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD",
                       "DOGE-USD", "DOT-USD", "AVAX-USD", "LINK-USD", "BNB-USD"]:
            return "🪙", "Crypto (Large Cap)"
        return "🪙", "Crypto"
    if symbol.endswith(".PA"):
        return "🇫🇷", "France (Euronext Paris)"
    if symbol.endswith(".DE"):
        return "🇩🇪", "Germany (Xetra)"
    if symbol.endswith(".L"):
        return "🇬🇧", "UK (London Stock Exchange)"
    if symbol.endswith(".AS"):
        return "🇳🇱", "Netherlands (Euronext Amsterdam)"
    if symbol.endswith(".SW") or symbol.endswith(".SIX"):
        return "🇨🇭", "Switzerland (SIX Swiss Exchange)"
    if symbol.endswith(".MI"):
        return "🇮🇹", "Italy (Borsa Italiana)"
    if symbol.endswith(".MC") or symbol.endswith(".AX") or symbol.endswith(".PA"):
        return "🇪🇺", "Europe"
    if symbol.endswith(".T"):
        return "🇯🇵", "Japan (Tokyo Stock Exchange)"
    if symbol.endswith(".HK"):
        return "🇭🇰", "Hong Kong Stock Exchange"
    if symbol.endswith(".TO") or symbol.endswith(".V"):
        return "🇨🇦", "Canada (TSX)"
    if symbol in ["SPY", "QQQ", "IWM", "EEM", "VWO", "VNQ", "GLD", "TLT", "DIA"]:
        return "📦", "ETF US"
    if symbol.endswith(".DE") or symbol.endswith(".PA"):
        return "📦", "ETF Europe"
    return "🇺🇸", "US Stock"


def get_product_info(symbol):
    """Return full product info: name, market, sector."""
    name = TICKER_NAMES.get(symbol, symbol)
    flag, market = get_market(symbol)
    return {
        "symbol": symbol,
        "name": name,
        "market_flag": flag,
        "market_name": market,
        "display": f"{flag} {name} ({symbol})",
    }


def enrich_trades(trades):
    """Add product info to each trade."""
    enriched = []
    for t in trades:
        info = get_product_info(t.get("symbol", ""))
        enriched.append({**t, **info})
    return enriched
