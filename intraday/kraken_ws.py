"""Kraken public WebSocket feed — no API key needed.

Subscribes to the "trade" channel for a list of pairs and buffers raw ticks
(price, volume, timestamp) in memory. The scheduler drains these buffers once
a minute to build 1-minute OHLCV candles.
"""
import asyncio
import json
import threading
import time
from collections import defaultdict

import websockets

KRAKEN_WS_URL = "wss://ws.kraken.com/"


class KrakenFeed:
    def __init__(self, symbols):
        self.symbols = list(symbols)
        self.connected = False
        self.last_message_time = {}
        self._ticks = defaultdict(list)
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="kraken-ws")
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
                async with websockets.connect(KRAKEN_WS_URL, ping_interval=20, ping_timeout=10) as ws:
                    await ws.send(json.dumps({
                        "event": "subscribe",
                        "pair": self.symbols,
                        "subscription": {"name": "trade"},
                    }))
                    self.connected = True
                    backoff = 1
                    while not self._stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        self._handle_message(raw)
            except Exception as e:
                self.connected = False
                if not self._stop.is_set():
                    print(f"[kraken_ws] disconnected ({e}), reconnecting in {backoff}s")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    def _handle_message(self, raw):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, list) or len(msg) < 4:
            return  # heartbeat / systemStatus / subscriptionStatus events are dicts or shorter

        payload, channel_name, pair = msg[1], msg[2], msg[3]
        if channel_name != "trade":
            return

        with self._lock:
            for trade in payload:
                price, volume, ts = float(trade[0]), float(trade[1]), float(trade[2])
                self._ticks[pair].append((ts, price, volume))
            self.last_message_time[pair] = time.time()

    def drain_ticks(self, symbol):
        """Pop and return all ticks buffered for symbol since the last drain."""
        with self._lock:
            ticks = self._ticks.get(symbol, [])
            self._ticks[symbol] = []
        return ticks

    def status(self):
        return {
            "connected": self.connected,
            "symbols": self.symbols,
            "last_message_time": dict(self.last_message_time),
        }
