import numpy as np
from .base import BaseStrategy


class PairsTradingStrategy(BaseStrategy):
    """Statistical arbitrage on correlated pairs using OLS hedge ratio.

    Important limitation, unchanged by this pass: the execution engine is
    long-only (no short-selling support), so this can never be truly
    market-neutral — it can only long the lagging leg and flatten the richer
    one, which is why the live beta vs SPY has measured +0.32, not ~0. Real
    market-neutrality needs short-selling added to the execution engine,
    which is a separate, bigger decision.

    What this pass does fix: sizing was a flat 40% of *remaining* cash per
    entry, same "collapses to 1-2 concurrent pairs" bug as the other equity
    bots had. Now equal-weighted across all configured pairs, tilted by
    |z-score| (stronger dislocation = bigger size, capped +/-10%), and
    additionally scaled down when the hedge ratio is far from 1 — a hedge
    ratio well away from 1 means the two legs aren't comparably volatile, so
    a long-only position in one leg is a weaker proxy for the pair's spread
    and warrants less size."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        pairs = config.get("pairs", [
            {"symbol_a": "XOM", "symbol_b": "CVX"},
            {"symbol_a": "KO", "symbol_b": "PEP"},
        ])
        entry_z = config.get("entry_zscore", 2.0)
        exit_z = config.get("exit_zscore", 0.5)
        lookback = config.get("lookback", 20)
        max_z_for_conviction = config.get("max_z_for_conviction", 4.0)
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        cash = bot["cash"]
        signals = []
        n_pairs = max(len(pairs), 1)

        for pair in pairs:
            sym_a = pair["symbol_a"]
            sym_b = pair["symbol_b"]

            df_a = market_data.get(sym_a)
            df_b = market_data.get(sym_b)
            if df_a is None or df_b is None:
                continue

            min_len = min(len(df_a), len(df_b))
            if min_len < lookback + 1:
                continue

            closes_a = df_a["Close"].values[-min_len:].astype(float)
            closes_b = df_b["Close"].values[-min_len:].astype(float)

            if (closes_a <= 0).any() or (closes_b <= 0).any():
                # Equity prices should never be <= 0 — a hit here means bad
                # data, not something to silently paper over with abs().
                print(f"[pairs_trading] {sym_a}/{sym_b}: non-positive price in window, skipping")
                continue

            log_a = np.log(closes_a)
            log_b = np.log(closes_b)

            # OLS hedge ratio over full window
            try:
                coeffs = np.polyfit(log_b, log_a, 1)
            except (np.linalg.LinAlgError, ValueError):
                continue
            hedge_ratio = coeffs[0]

            spread = log_a - hedge_ratio * log_b
            spread_window = spread[-lookback:]
            mean_spread = np.mean(spread_window)
            std_spread = np.std(spread_window, ddof=1)

            if std_spread == 0:
                continue

            current_spread = spread[-1]
            z = (current_spread - mean_spread) / std_spread

            price_a = float(closes_a[-1])
            price_b = float(closes_b[-1])
            qty_a = self.get_holding_quantity(bot, sym_a)
            qty_b = self.get_holding_quantity(bot, sym_b)

            # ATR hard stop, independent of the spread reverting — a pair
            # whose cointegration has broken can drift further and further
            # from the mean instead of reverting, and |z| < exit_zscore then
            # never fires. Only one leg is ever held at a time (long-only).
            if qty_a > 0 and self.atr_stop_triggered(bot, sym_a, market_data, multiplier=atr_stop_mult):
                signals.append((sym_a, "sell", qty_a, price_a))
                continue
            if qty_b > 0 and self.atr_stop_triggered(bot, sym_b, market_data, multiplier=atr_stop_mult):
                signals.append((sym_b, "sell", qty_b, price_b))
                continue

            # hedge ratio far from 1 => legs aren't comparably volatile =>
            # a long-only proxy position is weaker, size it down (never up)
            hedge_scale = min(1.0, 1.0 / max(abs(hedge_ratio), 1e-6))

            # Exit: |z| < exit_zscore — close any open positions
            if abs(z) < exit_z:
                if qty_a > 0:
                    signals.append((sym_a, "sell", qty_a, price_a))
                if qty_b > 0:
                    signals.append((sym_b, "sell", qty_b, price_b))
                continue

            conviction = 0.5 + 0.5 * min(1.0, (abs(z) - entry_z) / (max_z_for_conviction - entry_z))

            # Entry: z > entry_z → spread too high → long B (lagging leg), flatten A
            if z > entry_z:
                if qty_b == 0 and cash > 0:
                    alloc = self.sized_allocation(bot, market_data, n_pairs, conviction) * hedge_scale
                    alloc = min(alloc, cash)
                    quantity_b = alloc / price_b
                    if quantity_b > 0:
                        signals.append((sym_b, "buy", quantity_b, price_b))
                        cash -= alloc
                if qty_a > 0:
                    signals.append((sym_a, "sell", qty_a, price_a))

            # Entry: z < -entry_z → spread too low → long A (lagging leg), flatten B
            elif z < -entry_z:
                if qty_a == 0 and cash > 0:
                    alloc = self.sized_allocation(bot, market_data, n_pairs, conviction) * hedge_scale
                    alloc = min(alloc, cash)
                    quantity_a = alloc / price_a
                    if quantity_a > 0:
                        signals.append((sym_a, "buy", quantity_a, price_a))
                        cash -= alloc
                if qty_b > 0:
                    signals.append((sym_b, "sell", qty_b, price_b))

        return signals
