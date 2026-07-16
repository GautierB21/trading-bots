import requests

from .base import IntradayStrategy

TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"

# Kraken uses XBT instead of BTC on its WS feed (same override applied when
# building the crypto_momentum/crypto_dip_buyer symbol lists in config.py).
COINGECKO_TO_KRAKEN_OVERRIDES = {"BTC": "XBT"}


def _to_kraken_symbol(coingecko_symbol):
    base = COINGECKO_TO_KRAKEN_OVERRIDES.get(coingecko_symbol.upper(), coingecko_symbol.upper())
    return f"{base}/USD"


class SocialMomentum(IntradayStrategy):
    """CoinGecko trending list as a proxy for X.com/Twitter social buzz.

    Buys coins jumping into (or up) the trending ranks, sells coins falling
    out of (or down) the ranks. Ranks are 1-indexed (1 = most trending).
    """

    MAX_POSITIONS = 5
    POSITION_PCT = 0.12
    TOP_ENTRY = 5
    RANK_JUMP_ENTRY = 3
    TOP_EXIT = 20
    RANK_DROP_EXIT = 5
    MAX_MARKET_CAP_RANK = 1000

    def __init__(self, name, budget, symbols, timeframe_minutes):
        super().__init__(name, budget, symbols, timeframe_minutes)
        self.prev_ranks = {}  # kraken symbol -> trending rank from last check

    def _fetch_trending(self):
        try:
            resp = requests.get(TRENDING_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"[social_momentum] trending fetch error: {e}")
            return {}

        ranks = {}
        for rank, entry in enumerate(data.get("coins") or [], start=1):
            item = entry.get("item") or {}
            cg_symbol = item.get("symbol")
            mcap_rank = item.get("market_cap_rank")
            if not cg_symbol or mcap_rank is None or mcap_rank >= self.MAX_MARKET_CAP_RANK:
                continue
            symbol = _to_kraken_symbol(cg_symbol)
            if symbol not in self.symbols:
                continue
            # Trending list can list the same base coin twice (different chains);
            # keep the best (lowest) rank seen.
            if symbol not in ranks or rank < ranks[symbol]:
                ranks[symbol] = rank
        return ranks

    def analyze(self, candles_by_symbol):
        signals = []
        current_ranks = self._fetch_trending()
        prev_ranks = self.prev_ranks
        open_positions = sum(1 for p in self.positions.values() if p["quantity"] > 1e-9)

        def last_price(symbol):
            candles = candles_by_symbol.get(symbol) or []
            return candles[-1]["close"] if candles else None

        # Exits: trending rank lost, dropped out of top-20, or fell 5+ places.
        for symbol, pos in self.positions.items():
            if pos["quantity"] <= 1e-9:
                continue
            new_rank = current_ranks.get(symbol)
            old_rank = prev_ranks.get(symbol)
            left_top_exit = new_rank is None or new_rank > self.TOP_EXIT
            dropped_hard = (
                new_rank is not None and old_rank is not None
                and new_rank - old_rank >= self.RANK_DROP_EXIT
            )
            if left_top_exit or dropped_hard:
                price = last_price(symbol) or pos["avg_price"]
                reason = ("left trending" if new_rank is None
                          else f"rank #{new_rank} (was #{old_rank})")
                signals.append((symbol, "sell", pos["quantity"], price, f"social momentum fading: {reason}"))
                open_positions -= 1

        # Entries: new top-5 trending, or jumped 3+ places since last check.
        for symbol, rank in current_ranks.items():
            if open_positions >= self.MAX_POSITIONS:
                break
            pos = self.get_position(symbol)
            if pos and pos["quantity"] > 1e-9:
                continue

            old_rank = prev_ranks.get(symbol)
            entered_top = rank <= self.TOP_ENTRY
            jumped = old_rank is not None and old_rank - rank >= self.RANK_JUMP_ENTRY
            if not (entered_top or jumped):
                continue

            price = last_price(symbol)
            if not price:
                continue
            qty = (self.cash * self.POSITION_PCT) / price
            if qty <= 0:
                continue

            reason = (f"entered top {self.TOP_ENTRY} trending (#{rank})" if entered_top
                       else f"jumped to #{rank} (was #{old_rank})")
            signals.append((symbol, "buy", qty, price, reason))
            open_positions += 1

        self.prev_ranks = current_ranks
        return signals
