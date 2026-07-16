"""Alpaca US-stock feed + paper trading client — optional, env-key gated.

If ALPACA_API_KEY / ALPACA_SECRET_KEY are not set, is_available() is False and
AlpacaFeed.start()/stop() are no-ops, so the rest of the system runs untouched.
Uses raw websockets/requests instead of the alpaca-trade-api SDK to avoid an
extra hard dependency for an optional feature.
"""
import asyncio
import json
import os
import threading
import time
from collections import defaultdict

import requests
import websockets

ALPACA_WS_URL = "wss://stream.data.alpaca.markets/v2/iex"
ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def is_available():
    return bool(os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"))


class AlpacaFeed:
    def __init__(self, symbols):
        self.symbols = list(symbols)
        self.connected = False
        self.last_message_time = {}
        self._ticks = defaultdict(list)
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self.api_key = os.environ.get("ALPACA_API_KEY")
        self.api_secret = os.environ.get("ALPACA_SECRET_KEY")

    def start(self):
        if not is_available():
            return  # no-op: keys not configured
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="alpaca-ws")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.connected = False

    def _run_loop(self):
        asyncio.run(self._main())

    async def _main(self):
        backoff = 1
        while not self._stop.is_set():
            try:
                async with websockets.connect(ALPACA_WS_URL) as ws:
                    await ws.send(json.dumps({
                        "action": "auth",
                        "key": self.api_key,
                        "secret": self.api_secret,
                    }))
                    await ws.recv()  # auth ack
                    await ws.send(json.dumps({
                        "action": "subscribe",
                        "trades": self.symbols,
                    }))
                    self.connected = True
                    backoff = 1
                    while not self._stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        self._handle_message(raw)
            except Exception as e:
                self.connected = False
                if not self._stop.is_set():
                    print(f"[alpaca_ws] disconnected ({e}), reconnecting in {backoff}s")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    def _handle_message(self, raw):
        try:
            messages = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(messages, list):
            return
        with self._lock:
            for m in messages:
                if m.get("T") != "t":  # trade message
                    continue
                symbol = m.get("S")
                price = float(m.get("p", 0))
                volume = float(m.get("s", 0))
                ts = time.time()
                self._ticks[symbol].append((ts, price, volume))
                self.last_message_time[symbol] = ts

    def drain_ticks(self, symbol):
        with self._lock:
            ticks = self._ticks.get(symbol, [])
            self._ticks[symbol] = []
        return ticks

    def status(self):
        return {
            "available": is_available(),
            "connected": self.connected,
            "symbols": self.symbols,
            "last_message_time": dict(self.last_message_time),
        }


class AlpacaTradingClient:
    """Thin REST wrapper around the Alpaca paper trading order endpoint."""

    def __init__(self):
        self.api_key = os.environ.get("ALPACA_API_KEY")
        self.api_secret = os.environ.get("ALPACA_SECRET_KEY")

    def _headers(self):
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    def submit_order(self, symbol, qty, side):
        resp = requests.post(
            f"{ALPACA_PAPER_BASE_URL}/v2/orders",
            headers=self._headers(),
            json={"symbol": symbol, "qty": qty, "side": side, "type": "market", "time_in_force": "day"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
