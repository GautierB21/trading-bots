from src.bot_manager import _collect_symbols

_ETF_TICKERS = {"SPY", "QQQ", "IWM", "EEM", "VWO", "VNQ", "GLD", "TLT", "DIA"}

_SUFFIX_MARKETS = [
    (".PA", "🇫🇷 France"),
    (".DE", "🇩🇪 Germany"),
    (".L", "🇬🇧 UK"),
    (".AS", "🇳🇱 Netherlands"),
    (".SW", "🇨🇭 Switzerland"),
    (".SIX", "🇨🇭 Switzerland"),
    (".MI", "🇮🇹 Italy"),
    (".MC", "🇪🇺 Other EU"),
    (".AX", "🇪🇺 Other EU"),
    (".T", "🇯🇵 Japan"),
    (".HK", "🇭🇰 Hong Kong"),
    (".KS", "🇰🇷 South Korea"),
    (".KQ", "🇰🇷 South Korea"),
    (".TO", "🇨🇦 Canada"),
]


def classify_symbol(symbol):
    s = symbol.upper()
    if s in _ETF_TICKERS:
        return "📊 ETFs"
    if "-USD" in s:
        return "🪙 Crypto"
    for suffix, market in _SUFFIX_MARKETS:
        if s.endswith(suffix):
            return market
    return "🇺🇸 US Stocks"


def compute_universe(bot):
    symbols = _collect_symbols(bot)
    groups = {}
    for sym in symbols:
        groups.setdefault(classify_symbol(sym), []).append(sym)

    markets = [
        {"name": name, "count": len(syms), "examples": sorted(syms)[:6]}
        for name, syms in groups.items()
    ]
    markets.sort(key=lambda m: -m["count"])

    return {
        "total": len(symbols),
        "total_unique": len(set(symbols)),
        "markets": markets,
    }
