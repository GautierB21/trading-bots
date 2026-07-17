import signal
import sys
import threading
import time
from datetime import datetime, timezone

from . import config, db
from .kraken_ws import KrakenFeed
from .alpaca_ws import AlpacaFeed, is_available as alpaca_is_available
from .strategies import STRATEGY_CLASSES
from src.intraday_volume import get_24h_volume
from src import fx

CYCLE_SECONDS = 60
MIN_BUY_VOLUME_USD = 50_000
MAX_POSITION_VOLUME_FRACTION = 0.02
MICRO_VOLUME_THRESHOLD = 100_000  # 24h volume below this → value at cost
MAX_DRAWDOWN_PCT = 0.25  # pause a bot once pnl drops below -25% of its budget
PORTFOLIO_CIRCUIT_BREAKER_PCT = -10.0  # pause every bot once all 5 combined are down this much over 7 days


class IntradayScheduler:
    def __init__(self):
        db.init_db()

        self.kraken = KrakenFeed(config.CRYPTO_SYMBOLS)
        self.alpaca = AlpacaFeed(config.ALPACA_SYMBOLS)

        self.strategies = {}
        for bot_cfg in config.BOTS:
            cls = STRATEGY_CLASSES[bot_cfg["strategy"]]
            strat = cls(bot_cfg["name"], bot_cfg["budget"], bot_cfg["symbols"], bot_cfg["timeframe"])
            self._restore_state(strat)
            self.strategies[bot_cfg["name"]] = strat

        self._minute_count = 0
        self._last_run_epoch = {}   # bot name -> minute_epoch it last ran at
        self._last_higher_tf_epoch = {300: None, 900: None}
        self._thread = None
        self._stop = threading.Event()
        self.started_at = None

    def _restore_state(self, strat):
        # Calculate actual cash from trades: budget - total_buys + total_sells
        buys = db.get_trade_total(strat.name, "buy") or 0
        sells = db.get_trade_total(strat.name, "sell") or 0
        commission = db.get_commission_total(strat.name) or 0
        strat.cash = strat.budget - buys + sells - commission
        # Restore positions from DB
        for p in db.get_positions(strat.name):
            strat.positions[p["symbol"]] = {"quantity": p["quantity"], "avg_price": p["avg_price"]}

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        if self.is_running():
            return False
        self._stop.clear()
        self.kraken.start()
        self.alpaca.start()
        self.started_at = datetime.now(timezone.utc)
        self._thread = threading.Thread(target=self._run, daemon=True, name="intraday-scheduler")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=CYCLE_SECONDS)
        self.kraken.stop()
        self.alpaca.stop()
        return True

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def _run(self):
        next_tick = time.time()
        while not self._stop.is_set():
            next_tick += CYCLE_SECONDS
            try:
                self._cycle()
            except Exception as e:
                print(f"[scheduler] cycle error: {e}")
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                self._stop.wait(sleep_for)
            else:
                next_tick = time.time()

    # ── per-minute cycle ─────────────────────────────────────────────────────

    def _cycle(self):
        # Anchored to wall-clock minutes rather than a process-local counter:
        # the scheduler restarts often during development, and a counter that
        # resets to 0 each time almost never reaches the 15-multiple needed to
        # build 900s candles, so slower-timeframe bots (e.g. crypto_momentum)
        # would starve for data forever.
        minute_epoch = int(time.time() // 60)
        self._minute_count += 1
        self._finalize_1m_candles()

        # `minute_epoch == 0 mod N` can be true for more than one loop
        # iteration in a row if a previous _cycle() ran long (e.g. momentum
        # scanning ~700 symbols) and the loop falls behind — _last_*_epoch
        # tracking makes each rebuild/run idempotent per wall-clock bucket
        # instead of re-running (and duplicating trades) on every catch-up
        # iteration that still lands on the same bucket.
        if minute_epoch % 5 == 0 and self._last_higher_tf_epoch[300] != minute_epoch:
            self._build_higher_tf(source_seconds=60, target_seconds=300, count=5)
            self._last_higher_tf_epoch[300] = minute_epoch
        if minute_epoch % 15 == 0 and self._last_higher_tf_epoch[900] != minute_epoch:
            self._build_higher_tf(source_seconds=60, target_seconds=900, count=15)
            self._last_higher_tf_epoch[900] = minute_epoch

        for bot_cfg in config.BOTS:
            if minute_epoch % bot_cfg["timeframe"] != 0:
                continue
            if self._last_run_epoch.get(bot_cfg["name"]) == minute_epoch:
                continue
            self._last_run_epoch[bot_cfg["name"]] = minute_epoch
            self._run_strategy(bot_cfg)

        self._take_snapshots()
        self._print_status()

    def _all_symbols(self):
        return set(self.kraken.symbols) | set(self.alpaca.symbols)

    def _finalize_1m_candles(self):
        # Kraken/Alpaca ticks arrive in USD; every bot's budget and every
        # dashboard number here is EUR (see src/fx.py) — convert at the one
        # chokepoint where raw ticks become candles, so nothing downstream
        # (strategies, portfolio_value, snapshots) needs to know about it.
        usd_rate = fx.get_fx_rate("USD")
        minute_bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        open_time = minute_bucket.strftime("%Y-%m-%d %H:%M:%S")
        for feed in (self.kraken, self.alpaca):
            for symbol in feed.symbols:
                ticks = feed.drain_ticks(symbol)
                if not ticks:
                    continue
                prices = [t[1] * usd_rate for t in ticks]
                volume = sum(t[2] for t in ticks)
                db.insert_candle(symbol, 60, open_time, prices[0], max(prices), min(prices), prices[-1], volume)

    def _build_higher_tf(self, source_seconds, target_seconds, count):
        for symbol in self._all_symbols():
            db.aggregate_candles(symbol, source_seconds, target_seconds, count)

    def _run_strategy(self, bot_cfg):
        strat = self.strategies[bot_cfg["name"]]
        if strat.paused:
            return
        interval_seconds = bot_cfg["timeframe"] * 60
        candles_by_symbol = {s: db.get_candles(s, interval_seconds, limit=100) for s in bot_cfg["symbols"]}

        try:
            signals = strat.analyze(candles_by_symbol)
        except Exception as e:
            print(f"[scheduler] {strat.name} analyze error: {e}")
            signals = []

        strat.last_signals = signals
        strat.last_analyzed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        rate = config.COMMISSION_RATES.get(bot_cfg["data_source"], 0.001)
        # Dedup signals before execution to prevent double cash adjustments
        seen_signals = set()
        unique_signals = []
        for s in signals:
            key = (s[0], s[1], round(s[2], 6))  # (symbol, side, qty_rounded)
            if key not in seen_signals:
                seen_signals.add(key)
                unique_signals.append(s)

        for symbol, side, qty, price, reason in unique_signals:
            if side == "buy":
                volume = get_24h_volume(symbol)
                if volume < MIN_BUY_VOLUME_USD:
                    print(f"  [{strat.name}] SKIP {symbol}: 24h volume ${volume:,.0f} < min ${MIN_BUY_VOLUME_USD:,.0f}")
                    continue
                max_trade_usd = volume * MAX_POSITION_VOLUME_FRACTION
                if qty * price > max_trade_usd:
                    qty = max_trade_usd / price

            fill = strat.execute(symbol, side, qty, price, rate)
            if fill is None:
                print(f"  [{strat.name}] REJECTED {side.upper()} {qty:.6f} {symbol} @ {price:.4f} ({reason})")
                continue
            filled_qty, commission = fill
            total = filled_qty * price
            db.insert_trade(strat.name, symbol, side, filled_qty, price, total, commission, reason)
            print(f"  [{strat.name}] {side.upper()} {filled_qty:.6f} {symbol} @ {price:.4f} — {reason}")

    def _latest_price(self, symbol):
        candles = db.get_candles(symbol, 60, limit=1)
        return candles[-1]["close"] if candles else None

    def _valuation_price(self, strat, symbol, price):
        # If a symbol's 24h volume is tiny, the live price from a thin order
        # book can swing wildly producing insane unrealized P&L. Value illiquid
        # positions at avg_price (cost basis) instead.
        pos = strat.positions.get(symbol)
        if pos:
            vol = get_24h_volume(symbol)
            if vol < MICRO_VOLUME_THRESHOLD:
                return pos["avg_price"]
        return price

    def _take_snapshots(self):
        portfolio_total = 0.0
        for name, strat in self.strategies.items():
            prices = {s: self._valuation_price(strat, s, self._latest_price(s)) for s in strat.symbols}
            total_value = strat.portfolio_value(prices)
            portfolio_total += total_value
            holdings_value = total_value - strat.cash
            pnl = total_value - strat.budget
            db.insert_snapshot(name, total_value, strat.cash, holdings_value, pnl)

            if not strat.paused and strat.budget and pnl < -MAX_DRAWDOWN_PCT * strat.budget:
                strat.paused = True
                print(f"[scheduler] {name} PAUSED: drawdown {pnl / strat.budget * 100:.1f}% "
                      f"breached -{MAX_DRAWDOWN_PCT * 100:.0f}% limit")

            for symbol, pos in strat.positions.items():
                if pos["quantity"] <= 1e-9:
                    continue
                price = prices.get(symbol) or pos["avg_price"]
                current_value = pos["quantity"] * price
                unrealized_pnl = (price - pos["avg_price"]) * pos["quantity"]
                db.upsert_position(name, symbol, pos["quantity"], pos["avg_price"], current_value, unrealized_pnl)

        # Portfolio-level circuit breaker — catches a market-wide crypto
        # selloff where every bot is quietly losing together (a single
        # bot's own -25% stop doesn't fire on a correlated event that's
        # only -10% for each one individually but hits all 5 at once).
        week_ago_total = db.get_portfolio_total_before(24 * 7)
        if week_ago_total and (portfolio_total - week_ago_total) / week_ago_total * 100 <= PORTFOLIO_CIRCUIT_BREAKER_PCT:
            pnl_7d = (portfolio_total - week_ago_total) / week_ago_total * 100
            for name, strat in self.strategies.items():
                if not strat.paused:
                    strat.paused = True
                    print(f"[scheduler] {name} PAUSED by portfolio circuit breaker "
                          f"(all bots combined: {pnl_7d:.1f}% over 7 days)")

    def _print_status(self):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        parts = [f"kraken={'UP' if self.kraken.connected else 'DOWN'}"]
        if alpaca_is_available():
            parts.append(f"alpaca={'UP' if self.alpaca.connected else 'DOWN'}")
        for name, strat in self.strategies.items():
            prices = {s: self._latest_price(s) for s in strat.symbols}
            parts.append(f"{name}=€{strat.portfolio_value(prices):.2f}")
        print(f"[{ts}] cycle {self._minute_count} | " + " | ".join(parts))

    # ── read-only summaries for the API ──────────────────────────────────────

    def bot_summary(self, name):
        strat = self.strategies.get(name)
        if strat is None:
            return None
        prices = {s: self._latest_price(s) for s in strat.symbols}
        total_value = strat.portfolio_value(prices)
        pnl = total_value - strat.budget
        pnl_pct = (pnl / strat.budget * 100) if strat.budget else 0.0

        positions = []
        for symbol, pos in strat.positions.items():
            if pos["quantity"] <= 1e-9:
                continue
            price = prices.get(symbol) or pos["avg_price"]
            positions.append({
                "symbol": symbol,
                "quantity": round(pos["quantity"], 6),
                "avg_price": round(pos["avg_price"], 4),
                "current_price": round(price, 4),
                "market_value": round(pos["quantity"] * price, 2),
                "unrealized_pnl": round((price - pos["avg_price"]) * pos["quantity"], 2),
            })

        bot_cfg = [b for b in config.BOTS if b["name"] == name]
        display_name = bot_cfg[0].get("display_name", name) if bot_cfg else name
        description = bot_cfg[0].get("description", "") if bot_cfg else ""

        return {
            "name": name,
            "display_name": display_name,
            "description": description,
            "strategy": name,
            "budget": strat.budget,
            "timeframe": strat.timeframe,
            "symbols": strat.symbols,
            "cash": round(strat.cash, 2),
            "holdings_value": round(total_value - strat.cash, 2),
            "total_value": round(total_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "positions": positions,
            "status": "running" if self.is_running() else "stopped",
            "last_signals": [
                {"symbol": s, "side": side, "quantity": round(q, 6), "price": price, "reason": reason}
                for s, side, q, price, reason in strat.last_signals
            ],
            "last_analyzed_at": strat.last_analyzed_at,
            "last_trade_at": db.get_last_trade_time(name),
        }

    def all_bot_summaries(self):
        return [self.bot_summary(name) for name in self.strategies]

    def status(self):
        symbol_freshness = {}
        for feed in (self.kraken, self.alpaca):
            for symbol in feed.symbols:
                candles = db.get_candles(symbol, 60, limit=1)
                symbol_freshness[symbol] = candles[-1]["open_time"] if candles else None

        total_value = 0.0
        for strat in self.strategies.values():
            prices = {s: self._latest_price(s) for s in strat.symbols}
            total_value += strat.portfolio_value(prices)

        uptime_seconds = None
        if self.started_at:
            uptime_seconds = (datetime.now(timezone.utc) - self.started_at).total_seconds()

        return {
            "running": self.is_running(),
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "uptime_seconds": uptime_seconds,
            "kraken_connected": self.kraken.connected,
            "alpaca_available": alpaca_is_available(),
            "alpaca_connected": self.alpaca.connected,
            "total_portfolio_value": round(total_value, 2),
            "total_budget": config.TOTAL_BUDGET,
            "symbol_freshness": symbol_freshness,
        }

    def portfolio(self):
        bots = self.all_bot_summaries()
        total_value = sum(b["total_value"] for b in bots)
        total_cash = sum(b["cash"] for b in bots)
        total_pnl = sum(b["pnl"] for b in bots)
        return {
            "total_budget": config.TOTAL_BUDGET,
            "total_value": round(total_value, 2),
            "total_cash": round(total_cash, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / config.TOTAL_BUDGET) * 100, 2) if config.TOTAL_BUDGET else 0.0,
            "allocation": [
                {"name": b["name"], "total_value": b["total_value"], "budget": b["budget"]}
                for b in bots
            ],
        }


scheduler = IntradayScheduler()


if __name__ == "__main__":
    def _handle_signal(signum, frame):
        print(f"\n[scheduler] received signal {signum}, shutting down…")
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print("[scheduler] starting intraday scheduler (Ctrl+C to stop)…")
    scheduler.start()
    while scheduler.is_running():
        time.sleep(1)
