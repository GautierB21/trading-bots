#!/usr/bin/env python3
import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

import csv
import io
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory, Response
from src import db
from src.bot_manager import run_all_bots, run_bot, _collect_symbols, create_bot as bm_create_bot, reset_bot as bm_reset_bot
from src.universe import compute_universe
from src.data_fetcher import fetch_current_prices
from src import data_fetcher_alpha as alpha
from src.portfolio import get_portfolio_summary
from src.signal_analysis import analyze_bot_signals
from src.time_utils import days_since
from src.risk_metrics import bot_metrics
from src.backtest import backtest_strategy, backtest_compare
from src.intraday_backtest import run_intraday_backtest
from src.benchmark import fetch_spy_returns, alpha_beta, correlation_matrix
from strategies import STRATEGY_MAP

try:
    from intraday.scheduler import scheduler as intraday_scheduler
    from intraday import db as intraday_db
    HAS_INTRADAY = True
except ImportError as e:
    HAS_INTRADAY = False
    print(f"[server] intraday module unavailable: {e}")

app = Flask(__name__, static_folder="dashboard/static", static_url_path="/static")

# Read once, ahead of app.run(debug=...) below, so the reloader guard further
# down has a value to check (app.debug itself isn't set until app.run() runs).
DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

db.init_db()


def _acquire_scheduler_lock():
    """OS-level lock so only one process ever starts the intraday scheduler
    when this module is imported multiple times as a WSGI app (e.g. gunicorn
    with >1 worker — each worker is a separate process/import, and the
    scheduler's positions/cash live only in process memory)."""
    import fcntl
    lock_path = os.path.join(os.path.dirname(__file__), "data", ".intraday_scheduler.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    globals()["_scheduler_lock_fh"] = fh  # keep the fd open for the process lifetime
    return True


def _should_start_scheduler():
    if __name__ == "__main__":
        # Launched via `python server.py`: Flask's debug reloader re-execs this
        # whole module in a child process while the original stays alive as a
        # watcher — both import this file, so without this check two
        # independent scheduler threads (two Kraken WS connections) end up
        # trading against the same DB concurrently. Only the reloader's real
        # serving child (or a non-debug run, which never forks) should start it.
        return (not DEBUG) or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    # Imported as `server:app` (gunicorn): no reloader involved, but multiple
    # worker processes each import this module independently.
    return _acquire_scheduler_lock()


# Auto-start intraday scheduler on boot.
if HAS_INTRADAY and _should_start_scheduler():
    try:
        intraday_scheduler.start()
        print("[server] ✅ Intraday scheduler auto-started")
    except Exception as e:
        print(f"[server] ⚠️ Could not auto-start intraday: {e}")

STRATEGY_TEMPLATES = {
    "sma_crossover": {
        "fast_period": 20,
        "slow_period": 50,
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "JNJ", "WMT", "XOM", "PG", "KO", "PEP",
            "MC.PA", "OR.PA", "AIR.PA", "BNP.PA", "TTE.PA", "SAN.PA",
            "SAP.DE", "SIE.DE", "ALV.DE", "BMW.DE",
            "SHEL.L", "HSBA.L", "AZN.L", "ULVR.L",
            "7203.T", "6758.T", "9984.T", "6861.T", "8035.T",
            "0700.HK", "0001.HK", "0005.HK",
        ],
    },
    "rsi_mean_reversion": {
        "period": 14,
        "oversold": 30,
        "overbought": 70,
        "symbols": [
            "TSLA", "NVDA", "META", "AMZN", "NFLX", "GME", "COIN", "PLTR", "AMD", "DIS", "BA", "DAL", "UBER", "SQ", "PYPL", "MRNA", "BABA", "JD",
            "MC.PA", "AIR.PA", "BNP.PA", "KER.PA", "STMPA.PA", "DGE.L",
            "SIE.DE", "SAP.DE", "BMW.DE", "VOW3.DE",
            "SHEL.L", "BARC.L", "RIO.L", "LLOY.L",
            "9984.T", "6861.T", "8035.T", "6758.T",
            "0700.HK", "1299.HK", "2318.HK", "9988.HK",
        ],
    },
    "momentum": {
        "lookback": 20,
        "top_n": 3,
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD",
            "DIS", "NFLX", "ADBE", "CRM", "INTC", "CSCO", "ORCL", "IBM", "XOM", "CVX", "KO", "PEP", "PFE", "MRK", "ABBV",
            "BAC", "C", "GS", "MS", "AXP", "AIG", "CAT", "GE", "MCD", "SBUX", "NKE", "BA", "T", "VZ", "COST", "LLY",
            "NEE", "TMO", "SPGI", "BLK",
            "MC.PA", "OR.PA", "AIR.PA", "BNP.PA", "TTE.PA", "SAN.PA", "CS.PA", "SU.PA",
            "SAP.DE", "SIE.DE", "ALV.DE", "BMW.DE",
            "SHEL.L", "HSBA.L", "AZN.L", "ULVR.L",
            "7203.T", "6758.T", "9984.T",
            "0700.HK", "1299.HK", "0001.HK",
            "SPY", "QQQ", "EEM", "VWO",
        ],
    },
    "bollinger_bands": {
        "period": 20,
        "std_dev": 2,
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "BAC", "WMT", "JNJ", "XOM", "CVX", "KO",
            "PEP", "ORCL", "INTC", "CSCO", "PFE", "MRK", "MCD", "SBUX", "NKE", "BA",
            "MC.PA", "OR.PA", "AIR.PA", "BNP.PA",
            "SAP.DE", "SIE.DE",
            "SHEL.L", "AZN.L",
            "7203.T", "9984.T",
            "0700.HK", "1299.HK",
        ],
    },
    "dca": {
        "amount_per_period": 100,
        "symbols": ["SPY", "QQQ", "IWM", "EEM", "VNQ", "GLD", "TLT", "VWCE.DE", "CW8.PA", "ESE.PA", "2800.HK"],
        "max_position": 10,
    },
    "pairs_trading": {
        "pairs": [
            {"symbol_a": "JPM", "symbol_b": "BAC"},
            {"symbol_a": "GS", "symbol_b": "MS"},
            {"symbol_a": "AAPL", "symbol_b": "MSFT"},
            {"symbol_a": "GOOGL", "symbol_b": "AMZN"},
            {"symbol_a": "XOM", "symbol_b": "CVX"},
            {"symbol_a": "KO", "symbol_b": "PEP"},
            {"symbol_a": "BNP.PA", "symbol_b": "ACA.PA"},
            {"symbol_a": "SAP.DE", "symbol_b": "SIE.DE"},
            {"symbol_a": "SHEL.L", "symbol_b": "BP.L"},
            {"symbol_a": "7203.T", "symbol_b": "7267.T"},
        ],
        "entry_zscore": 2.0,
        "exit_zscore": 0.5,
        "lookback": 20,
    },
    "fundamental": {
        "symbols": [
            "AAPL", "MSFT", "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD", "COST", "LLY", "ABBV", "MRK", "PEP",
            "KO", "MCD", "SBUX", "NKE", "ORCL", "CSCO", "TXN", "LOW", "TGT", "CAT", "UPS", "HON", "AXP", "BLK", "SPGI",
            "VZ", "T",
            "MC.PA", "OR.PA", "AIR.PA", "BNP.PA", "TTE.PA", "SAN.PA", "CS.PA", "SU.PA", "VIE.PA",
            "SAP.DE", "SIE.DE", "ALV.DE", "DTE.DE",
            "SHEL.L", "AZN.L", "ULVR.L", "HSBA.L", "GSK.L",
            "9984.T", "9432.T", "8058.T",
        ],
        "min_market_cap": 10000000000,
        "max_pe_ratio": 25,
        "min_pe_ratio": 5,
        "min_roe": 10,
        "max_debt_to_equity": 1.5,
        "position_size_pct": 0.7,
    },
    "sentiment": {
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "NFLX", "DIS", "BA", "GM", "UBER", "XYZ",
            "PYPL", "COIN", "PLTR", "AMD", "INTC", "CSCO", "ORCL", "IBM", "XOM", "CVX", "WMT", "MCD", "NKE", "SBUX",
            "PFE", "MRNA",
            "MC.PA",
            "SAP.DE",
            "9984.T",
            "0700.HK",
        ],
        "min_positive_ratio": 0.6,
        "max_negative_ratio": 0.4,
        "min_articles": 3,
        "position_size_pct": 0.5,
    },
    "sentiment_av": {
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "V", "JNJ", "WMT", "HD", "PG", "MA", "DIS",
        ],
        "min_articles": 2,
        "position_size_pct": 0.5,
    },
    "donchian_breakout": {
        "entry_period": 55,
        "exit_period": 20,
        "max_positions": 5,
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "JNJ",
            "WMT", "PG", "MA", "UNH", "HD", "DIS", "NFLX", "ADBE", "CRM", "INTC",
        ],
    },
    "pead": {
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "V", "JNJ", "WMT", "HD", "PG", "MA", "DIS",
        ],
        "min_surprise_pct": 5.0,
        "max_days_since_earnings": 3,
        "hold_days": 30,
        "max_positions": 5,
    },
    "low_volatility": {
        "lookback": 60,
        "top_n": 5,
        "rebalance_days": 20,
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "JNJ", "PG", "KO", "WMT", "PEP",
            "V", "MA", "HD", "MCD", "COST", "UNH", "ABBV",
        ],
    },
    "reversal_1day": {
        "max_positions": 5,
        "hold_days": 3,
        "min_decline_pct": 3.0,
        "symbols": [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "V", "JNJ", "WMT", "HD", "PG", "MA", "DIS",
            "BAC", "XOM", "CVX", "KO", "PEP",
        ],
    },
    "sector_rotation": {
        "lookback": 60,
        "top_n": 3,
        "rate_tilt_pct": 0.03,
        "symbols": ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"],
    },
    "post_fomc_drift": {
        "symbols": ["SPY", "QQQ"],
        "reaction_window_days": 1,
        "min_reaction_pct": 1.0,
        "hold_days": 5,
        "max_positions": 2,
    },
}

STRATEGY_META = {
    "sma_crossover": {
        "display_name": "SMA Crossover",
        "description": "Moyennes Mobiles (SMA = Simple Moving Average). Calcule la moyenne du prix sur 20 jours (court terme) et sur 50 jours (moyen terme). Achète quand la moyenne court terme dépasse la moyenne long terme (signal haussier). Vend quand l'inverse se produit (signal baissier). Idéal pour suivre les tendances.",
    },
    "rsi_mean_reversion": {
        "display_name": "RSI Mean Reversion",
        "description": "RSI (Relative Strength Index) mesure la force d'un prix sur 14 jours, noté de 0 à 100. Quand le RSI passe sous 30, l'actif est considéré 'survendu' → opportunité d'achat. Quand il dépasse 70, il est 'suracheté' → risque de baisse, on vend. Stratégie de retour à la moyenne.",
    },
    "momentum": {
        "display_name": "Momentum",
        "description": "Momentum = élan. Calcule la performance des 20 derniers jours pour 20 actions. Achète les 3 meilleures performers (les plus fortes) et vend celles qui ne sont plus dans le top. Stratégie de 'course au leader' : on parie que les plus forts continuent de monter.",
    },
    "bollinger_bands": {
        "display_name": "Bollinger Bands",
        "description": "Bandes de Bollinger : 3 lignes tracées autour du prix. Celle du milieu = moyenne mobile 20 jours. Les 2 bandes extérieures sont écartées de ±2 écarts-types (mesure de volatilité). Achète quand le prix touche la bande basse (actif 'pas cher'). Vend quand il touche la bande haute (actif 'cher').",
    },
    "dca": {
        "display_name": "Dollar Cost Average",
        "description": "DCA = Dollar Cost Averaging. Achète pour 100$ de SPY (S&P 500) et QQQ (Nasdaq) à chaque exécution, sans jamais vendre. Stratégie d'investissement passif : on lisse le prix d'achat dans le temps. Ne cherche pas à timer le marché.",
    },
    "pairs_trading": {
        "display_name": "Pairs Trading",
        "description": "Trading de paires. Repère 2 actions historiquement corrélées (Exxon/Chevron, Coca/Pepsi). Quand l'écart entre elles devient anormal (écart > 2 écarts-types), on achète la moins chère et on vend la plus chère. On parie sur le retour à la normale de la relation entre les 2.",
    },
    "fundamental": {
        "display_name": "Fundamental",
        "description": "Analyse fondamentale. Achète des actions de grandes entreprises (min 10 milliards $) qui sont : pas trop chères (P/E entre 5 et 25), rentables (ROE > 10%), et peu endettées (Dette/Equité < 1.5). Vend si le P/E devient excessif (> 50). Style 'value investing'.",
    },
    "sentiment": {
        "display_name": "Sentiment",
        "description": "Trading basé sur le sentiment des news. Analyse les titres d'articles Yahoo Finance pour chaque action. Compte les mots positifs (record, profit, partenariat…) et négatifs (perte, procès, licenciement…). Achète si > 60% des news sont positives, vend si > 40% sont négatives. Backtest non fiable : Yahoo ne fournit que les news du jour, rejouées telles quelles sur tout l'historique.",
    },
    "sentiment_av": {
        "display_name": "Sentiment (Alpha Vantage)",
        "description": "Même idée que Sentiment, mais avec des news datées (Alpha Vantage NEWS_SENTIMENT, time_from/time_to) au lieu du snapshot du jour — le backtest voit le sentiment qui existait réellement à chaque date simulée. 15 valeurs US large-cap, quota Alpha Vantage limité (25 requêtes/jour).",
    },
    "lesechos_news": {
        "display_name": "Les Echos News",
        "description": "Analyse les articles des Échos (paywall) pour trader les actions du CAC 40. Compte les mots-clés positifs/négatifs en français, génère un score de sentiment par entreprise. Achète les sociétés avec des articles majoritairement positifs, vend les négatives. Sources : Les Echos, données en temps réel.",
    },
    "donchian_breakout": {
        "display_name": "Donchian Breakout",
        "description": "Canal de Donchian (style 'Turtle Traders'). Achète quand le prix dépasse son plus haut sur 55 jours (cassure haussière confirmée). Vend quand il repasse sous son plus bas sur 20 jours. Contrairement au SMA Crossover qui suit une tendance déjà établie, ici on entre au moment même de la cassure — signal différent malgré l'air de famille.",
    },
    "pead": {
        "display_name": "PEAD (Post-Earnings Drift)",
        "description": "Dérive post-annonce de résultats : le marché sous-réagit historiquement aux surprises de bénéfices, le prix continue de dériver dans le même sens pendant plusieurs semaines après l'annonce. Achète une action qui vient de battre ses estimations de résultats (>5%) dans les 3 jours suivant l'annonce, garde 30 jours. Données via yfinance (gratuit), Finnhub en secours si FINNHUB_API_KEY configuré. Signal 'événementiel', totalement différent des signaux techniques/sentiment des autres bots.",
    },
    "low_volatility": {
        "display_name": "Low Volatility",
        "description": "Anomalie de faible volatilité (Ang et al.) : les actions les moins volatiles battent historiquement le marché ajusté au risque. Achète le quintile le moins volatil de l'univers (volatilité réalisée sur 60 jours), rebalance toutes les 20 séances. Pari inverse du Momentum, qui lui chasse les gagnants les plus volatils.",
    },
    "reversal_1day": {
        "display_name": "Reversal 1-Day",
        "description": "Retournement à très court terme (overreaction). Classe tout l'univers par performance de la veille, achète les plus fortes baisses (≥3%), sort après 3 jours ou stop ATR. Différent du RSI Mean Reversion (indicateur multi-jours sur une seule action) : ici c'est un signal cross-sectionnel sur 1 jour, horizon de détention très court.",
    },
    "sector_rotation": {
        "display_name": "Sector Rotation",
        "description": "Momentum sectoriel via les ETF SPDR US (Tech, Finance, Énergie, Santé...). Classe les 11 secteurs par performance relative sur 60 jours, surpondère les 3 plus forts. Tilté par la tendance des taux 10 ans (^TNX) : taux qui montent → penche vers les défensifs (XLP/XLU/XLV), taux qui baissent → penche vers la croissance (XLK/XLY/XLC). Même mécanique que Momentum mais l'axe du pari est différent : quel secteur plutôt que quelle action.",
    },
    "post_fomc_drift": {
        "display_name": "Post-FOMC/BCE Drift",
        "description": "Dérive post-annonce banque centrale : le marché continue historiquement de dériver dans le sens de sa réaction initiale à une décision Fed/BCE pendant plusieurs jours. Mesure la réaction du jour sur SPY/QQQ après une date FOMC/BCE (src/macro_calendar.py) ; si réaction positive >1%, suit la tendance 5 jours. Moteur long-only : ne peut réagir qu'aux réactions positives, jamais shorter une réaction négative.",
    },
}


# Same-origin dashboard doesn't need CORS at all; this only exists for the
# rare case of hitting the API from another allowed origin. Defaults to the
# deployed host — override with ALLOWED_ORIGIN if serving the dashboard
# elsewhere. Was "*", which let any site's JS trigger state-changing POSTs
# (create/run/reset bots) via a visitor's browser.
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://trading.bookpass.fr")


def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    return response


@app.after_request
def after_request(response):
    return _cors(response)


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def options_handler(_any):
    return "", 204


# ── Strategies ────────────────────────────────────────────────────────────────

@app.route("/api/strategies")
def list_strategies():
    return jsonify([
        {
            "id": name,
            "display_name": STRATEGY_META.get(name, {}).get("display_name", name),
            "description": STRATEGY_META.get(name, {}).get("description", ""),
            "default_config": STRATEGY_TEMPLATES.get(name, {}),
        }
        for name in STRATEGY_MAP.keys()
    ])


# ── Bots ──────────────────────────────────────────────────────────────────────

@app.route("/api/bots")
def list_bots():
    bots = db.get_all_bots(active_only=False)
    # Collect all symbols across all bots
    all_symbols = set()
    for bot in bots:
        config = bot.get("config", {})
        syms = config.get("symbols", [])
        pairs = config.get("pairs", [])
        all_symbols.update(syms)
        for p in pairs:
            all_symbols.update([p.get("symbol_a", ""), p.get("symbol_b", "")])
    all_symbols.discard("")
    # allow_stale: this endpoint backs the dashboard's main page load — a
    # price a few hours old beats blocking page render on a live fetch
    # across hundreds of symbols. Cache still gets refreshed by the daily
    # cron run and by any accuracy-sensitive call (backtests, reports).
    prices = fetch_current_prices(list(all_symbols), allow_stale=True) if all_symbols else {}

    result = []
    for bot in bots:
        b = {k: v for k, v in bot.items() if k not in ("holdings",)}
        b["config"] = bot["config"]
        meta = STRATEGY_META.get(bot["strategy"], {})
        b["strategy_display_name"] = meta.get("display_name", bot["strategy"])
        b["strategy_description"] = meta.get("description", "")

        # Compute total_value from holdings + cash
        holdings_value = 0.0
        for h in bot.get("holdings", []):
            px = prices.get(h["symbol"])
            if px is not None and px > 0:
                holdings_value += float(h["quantity"]) * float(px)
        b["holdings_value"] = round(holdings_value, 2)
        b["total_value"] = round(bot["cash"] + holdings_value, 2)

        b["universe"] = compute_universe(bot)
        result.append(b)
    return jsonify(result)


@app.route("/api/bots", methods=["POST"])
def add_bot():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    strategy = data.get("strategy")
    capital = data.get("capital", 10000)
    config = data.get("config", {})

    if not name or not strategy:
        return jsonify({"error": "name and strategy are required"}), 400
    if strategy not in STRATEGY_MAP:
        return jsonify({"error": f"unknown strategy '{strategy}'"}), 400
    if db.get_bot(name=name) is not None:
        return jsonify({"error": f"bot '{name}' already exists"}), 409

    try:
        capital = float(capital)
    except (TypeError, ValueError):
        return jsonify({"error": "capital must be a number"}), 400

    bot = bm_create_bot(name, strategy, capital, config)
    return jsonify(bot), 201


@app.route("/api/bots/<int:bot_id>/run", methods=["POST"])
def run_single_bot(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    result = run_bot(bot_id)
    return jsonify({"status": "ok", "result": str(result)})


@app.route("/api/bots/<int:bot_id>/universe")
def bot_universe(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    universe = compute_universe(bot)
    return jsonify({
        "bot_id": bot_id,
        "name": bot["name"],
        **universe,
    })


@app.route("/api/bots/<int:bot_id>")
def bot_detail(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    meta = STRATEGY_META.get(bot["strategy"], {})
    bot["strategy_display_name"] = meta.get("display_name", bot["strategy"])
    bot["strategy_description"] = meta.get("description", "")
    return jsonify(bot)


@app.route("/api/bots/<int:bot_id>", methods=["DELETE"])
def delete_bot(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM holdings WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM orders WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM portfolio_snapshots WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM trades WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM bots WHERE id=?", (bot_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/bots/<int:bot_id>/reset", methods=["POST"])
def reset_bot_endpoint(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    ok = bm_reset_bot(bot_id=bot_id)
    return jsonify({"ok": ok, "bot": db.get_bot(bot_id)})


@app.route("/api/bots/<int:bot_id>/config", methods=["POST"])
def update_bot_config(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    config = data.get("config")
    if config is None:
        return jsonify({"error": "config is required"}), 400
    conn = db.get_conn()
    try:
        conn.execute("UPDATE bots SET config=? WHERE id=?", (json.dumps(config), bot_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "bot": db.get_bot(bot_id)})


@app.route("/api/bots/<int:bot_id>/history")
def bot_history(bot_id):
    days = request.args.get("days", 30, type=int)
    snapshots = db.get_snapshots(bot_id, days)
    return jsonify(snapshots)


@app.route("/api/bots/<int:bot_id>/snapshots")
def bot_snapshots(bot_id):
    days = request.args.get("days", 30, type=int)
    snapshots = db.get_snapshots(bot_id, days)
    return jsonify(snapshots)


@app.route("/api/snapshots/<int:bot_id>")
def snapshots_for_chart(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    days = request.args.get("days", 30, type=int)
    snapshots = db.get_snapshots(bot_id, days)
    return jsonify(snapshots)


@app.route("/api/bots/<int:bot_id>/trades")
def bot_trades(bot_id):
    limit = request.args.get("limit", 500, type=int)
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    trades = db.get_trades(bot_id, limit, start_date=start_date, end_date=end_date)
    try:
        from src.product_info import enrich_trades
        trades = enrich_trades(trades)
    except ImportError:
        pass
    return jsonify(trades)


@app.route("/api/bots/<int:bot_id>/orders")
def bot_orders(bot_id):
    limit = request.args.get("limit", 50, type=int)
    orders = db.get_orders(bot_id, limit)
    return jsonify(orders)


@app.route("/api/bots/<int:bot_id>/portfolio")
def bot_portfolio(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    symbols = _collect_symbols(bot)
    prices = fetch_current_prices(symbols) if symbols else {}
    summary = get_portfolio_summary(bot_id, prices)
    return jsonify(summary)


@app.route("/api/leaderboard")
def leaderboard():
    rows = db.get_leaderboard()
    for r in rows:
        meta = STRATEGY_META.get(r.get("strategy"), {})
        r["strategy_display_name"] = meta.get("display_name", r.get("strategy"))
        r["strategy_description"] = meta.get("description", "")
        days = days_since(r.get("last_trade_date"))
        r["days_since_trade"] = days if days is not None else "never"
    return jsonify(rows)


@app.route("/api/bots/<int:bot_id>/metrics")
def bot_risk_metrics(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(bot_metrics(bot_id))


@app.route("/api/bots/<int:bot_id>/export/csv")
def bot_export_csv(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    trades = db.get_trades(bot_id, limit=100000)
    try:
        from src.product_info import enrich_trades
        trades = enrich_trades(trades)
    except ImportError:
        pass

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "symbol", "name", "market", "side", "quantity", "entry_price", "exit_price", "pnl"])
    for t in trades:
        writer.writerow([
            t.get("entry_date"),
            t.get("symbol"),
            t.get("name", t.get("symbol")),
            t.get("market_name", ""),
            t.get("side"),
            t.get("quantity"),
            t.get("entry_price"),
            t.get("exit_price"),
            t.get("pnl"),
        ])

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={bot['name']}_trades.csv"},
    )


@app.route("/api/backtest/compare", methods=["POST"])
def backtest_compare_api():
    data = request.get_json(force=True, silent=True) or {}
    strategies = data.get("strategies")
    period = data.get("period", "1y")
    capital = data.get("capital", 10000)

    if not strategies:
        strategies = list(STRATEGY_MAP.keys())

    # Build configs dict
    configs = {}
    for s in strategies:
        cfg = STRATEGY_TEMPLATES.get(s, {})
        if cfg:
            configs[s] = cfg

    try:
        results = backtest_compare(configs, period=period, capital=capital)
        # Add display names
        for r in results:
            meta = STRATEGY_META.get(r["strategy"], {})
            r["display_name"] = meta.get("display_name", r["strategy"])
        return jsonify({"results": results, "errors": [], "period": period})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/benchmark")
def benchmark_api():
    period = request.args.get("period", "6mo")

    try:
        spy = fetch_spy_returns(period=period)
        spy_returns = spy["return"]
        spy_returns.index = pd.to_datetime(spy_returns.index)
    except Exception as e:
        return jsonify({"error": f"failed to fetch SPY benchmark: {e}"}), 500

    configs = {}
    for s in STRATEGY_MAP.keys():
        cfg = STRATEGY_TEMPLATES.get(s, {})
        if cfg:
            configs[s] = cfg

    results = backtest_compare(configs, period=period, capital=10000)

    per_strategy = {}
    bot_histories = {}
    for r in results:
        name = r["strategy"]
        meta = STRATEGY_META.get(name, {})
        pnl_history = r.get("pnl_history", [])
        bot_histories[name] = {p["date"]: p["value"] for p in pnl_history}

        values = pd.Series({p["date"]: p["value"] for p in pnl_history})
        values.index = pd.to_datetime(values.index)
        bot_returns = values.pct_change().dropna()

        try:
            metrics = alpha_beta(bot_returns, spy_returns)
            per_strategy[name] = {
                "display_name": meta.get("display_name", name),
                "alpha_daily": float(metrics["alpha_daily"]),
                "beta": float(metrics["beta"]),
                "information_ratio": float(metrics["information_ratio"]),
                "tracking_error": float(metrics["tracking_error"]),
            }
        except Exception as e:
            per_strategy[name] = {"display_name": meta.get("display_name", name), "error": str(e)}

    try:
        corr = correlation_matrix(bot_histories).round(4)
        corr_matrix = {row: {col: (None if pd.isna(v) else float(v)) for col, v in corr.loc[row].items()} for row in corr.index}
    except Exception:
        corr_matrix = {}

    return jsonify({
        "period": period,
        "benchmark": "SPY",
        "strategies": per_strategy,
        "correlation_matrix": corr_matrix,
    })


@app.route("/api/backtest", methods=["POST"])
def run_backtest():
    data = request.get_json(force=True, silent=True) or {}
    strategy_name = data.get("strategy")
    config = data.get("config", {})
    capital = data.get("capital", 10000)
    period = data.get("period", "2y")

    if not strategy_name:
        return jsonify({"error": "strategy is required"}), 400
    if strategy_name not in STRATEGY_MAP:
        return jsonify({"error": f"unknown strategy '{strategy_name}'"}), 400
    try:
        capital = float(capital)
    except (TypeError, ValueError):
        return jsonify({"error": "capital must be a number"}), 400

    try:
        # Use default template config if empty config provided
        if not config or not config.get("symbols"):
            template = STRATEGY_TEMPLATES.get(strategy_name, {})
            if template:
                config = template
        try:
            result = backtest_strategy(strategy_name, config, period=period, capital=capital)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"backtest failed: {e}"}), 500

    return jsonify(result)


@app.route("/api/bots/<int:bot_id>/signal-check")
def bot_signal_check(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        return jsonify({"error": "not found"}), 404
    result = analyze_bot_signals(bot)
    return jsonify(result)


# ── Aggregate portfolio ───────────────────────────────────────────────────────

@app.route("/api/portfolio")
def aggregate_portfolio():
    bots = db.get_all_bots(active_only=False)
    all_symbols = set()
    for bot in bots:
        all_symbols.update(_collect_symbols(bot))
    # Same reasoning as /api/bots: loaded together on every dashboard visit,
    # a stale-but-instant price beats blocking the page on a live fetch.
    prices = fetch_current_prices(list(all_symbols), allow_stale=True) if all_symbols else {}

    total_value = 0.0
    total_cash = 0.0
    total_invested = 0.0
    total_holdings_value = 0.0
    by_strategy = {}
    all_holdings = []

    for bot in bots:
        summary = get_portfolio_summary(bot["id"], prices)
        total_value += summary["total_value"]
        total_cash += summary["cash"]
        total_invested += summary["capital"]
        total_holdings_value += summary["holdings_value"]

        strat = bot["strategy"]
        entry = by_strategy.setdefault(strat, {"total_value": 0.0, "count": 0})
        entry["total_value"] += summary["total_value"]
        entry["count"] += 1

        for h in summary["holdings"]:
            all_holdings.append({
                "bot_id": bot["id"],
                "bot_name": bot["name"],
                "strategy": strat,
                **h,
            })

    total_pnl = total_value - total_invested
    total_pnl_percent = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

    allocation_by_strategy = [
        {"strategy": strat, "total_value": round(v["total_value"], 2), "count": v["count"]}
        for strat, v in by_strategy.items()
    ]

    return jsonify({
        "total_value": round(total_value, 2),
        "total_cash": round(total_cash, 2),
        "total_invested": round(total_invested, 2),
        "total_holdings_value": round(total_holdings_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_percent, 2),
        "allocation_by_strategy": allocation_by_strategy,
        "holdings": all_holdings,
        "bot_count": len(bots),
    })


@app.route("/api/run", methods=["POST"])
def run_bots():
    results = run_all_bots()
    safe = {}
    for name, r in results.items():
        if "summary" in r:
            r["summary"].pop("holdings", None)
        safe[name] = r
    return jsonify(safe)


@app.route("/api/status")
def status():
    bots = db.get_all_bots(active_only=False)
    all_symbols = set()
    for bot in bots:
        all_symbols.update(_collect_symbols(bot))

    return jsonify({
        "alpha_vantage_configured": alpha.is_available(),
        "bot_count": len(bots),
        "symbol_count": len(all_symbols),
        "last_run_time": db.get_last_run_time(),
    })


# ── Intraday ─────────────────────────────────────────────────────────────────

@app.route("/api/intraday/bots")
def intraday_bots():
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    return jsonify(intraday_scheduler.all_bot_summaries())


@app.route("/api/intraday/bots/<name>")
def intraday_bot_detail(name):
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    summary = intraday_scheduler.bot_summary(name)
    if summary is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(summary)


@app.route("/api/intraday/bots/<name>/trades")
def intraday_bot_trades(name):
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    limit = request.args.get("limit", 500, type=int)
    trades = intraday_db.get_trades(name, limit)
    # Calculate P&L per sell trade (FIFO match with buys)
    trade_list = []
    buy_queue = {}  # symbol -> list of (qty, price)
    for t in trades:
        d = dict(t)
        sym = d["symbol"]
        side = d["side"]
        if side == "buy":
            buy_queue.setdefault(sym, []).append((d["quantity"], d["price"]))
            d["pnl"] = None
        else:
            pnl = 0.0
            qty_to_sell = d["quantity"]
            while qty_to_sell > 1e-9 and sym in buy_queue and buy_queue[sym]:
                b_qty, b_price = buy_queue[sym][0]
                matched = min(qty_to_sell, b_qty)
                pnl += matched * (d["price"] - b_price)
                qty_to_sell -= matched
                if b_qty <= matched + 1e-9:
                    buy_queue[sym].pop(0)
                else:
                    buy_queue[sym][0] = (b_qty - matched, b_price)
            d["pnl"] = round(pnl, 2)
        trade_list.append(d)
    try:
        from src.product_info import enrich_trades
        trade_list = enrich_trades(trade_list)
    except ImportError:
        pass
    return jsonify(trade_list)


@app.route("/api/intraday/bots/<name>/snapshots")
def intraday_bot_snapshots(name):
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    limit = request.args.get("limit", 200, type=int)
    return jsonify(intraday_db.get_snapshots(name, limit))


@app.route("/api/intraday/status")
def intraday_status():
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    return jsonify(intraday_scheduler.status())


@app.route("/api/intraday/start", methods=["POST"])
def intraday_start():
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    started = intraday_scheduler.start()
    return jsonify({"ok": True, "started": started, "running": intraday_scheduler.is_running()})


@app.route("/api/intraday/stop", methods=["POST"])
def intraday_stop():
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    intraday_scheduler.stop()
    return jsonify({"ok": True, "running": intraday_scheduler.is_running()})


@app.route("/api/intraday/candles/<path:symbol>/<int:interval>")
def intraday_candles(symbol, interval):
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    limit = request.args.get("limit", 100, type=int)
    return jsonify(intraday_db.get_candles(symbol, interval, limit))


@app.route("/api/intraday/portfolio")
def intraday_portfolio():
    if not HAS_INTRADAY:
        return jsonify({"error": "intraday not available"}), 503
    return jsonify(intraday_scheduler.portfolio())


PERIOD_HOURS = {"1d": 24, "1w": 168, "1m": 720, "3m": 2160}


@app.route("/api/intraday/backtest", methods=["POST"])
def intraday_backtest_api():
    data = request.get_json(force=True, silent=True) or {}
    strategy_name = data.get("strategy")
    symbols = data.get("symbols")
    timeframe_minutes = data.get("timeframe_minutes")
    period = data.get("period", "1w")
    capital = data.get("capital", 1000)

    if not strategy_name:
        return jsonify({"error": "strategy is required"}), 400
    if not symbols:
        return jsonify({"error": "symbols is required"}), 400
    if not timeframe_minutes:
        return jsonify({"error": "timeframe_minutes is required"}), 400
    try:
        capital = float(capital)
    except (TypeError, ValueError):
        return jsonify({"error": "capital must be a number"}), 400

    period_hours = PERIOD_HOURS.get(period)
    if period_hours is None:
        try:
            period_hours = float(data["period_hours"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": f"period must be one of {list(PERIOD_HOURS)} or period_hours must be set"}), 400

    try:
        result = run_intraday_backtest(strategy_name, symbols, int(timeframe_minutes), period_hours=period_hours, capital=capital)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"intraday backtest failed: {e}"}), 500

    return jsonify(result)


# ── Static / SPA ──────────────────────────────────────────────────────────────

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "dashboard")


@app.route("/manifest.json")
def manifest():
    return send_from_directory(DASHBOARD_DIR, "manifest.json")


@app.route("/sw.js")
def service_worker():
    return send_from_directory(DASHBOARD_DIR, "sw.js")


@app.route("/static/<path:filename>")
def static_assets(filename):
    return send_from_directory(app.static_folder, filename)


@app.route("/dashboard/<path:filename>")
def dashboard_assets(filename):
    return send_from_directory(DASHBOARD_DIR, filename)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path):
    if path.startswith("api/"):
        return jsonify({"error": "not found"}), 404

    full_path = os.path.join(DASHBOARD_DIR, path)
    if path and os.path.isfile(full_path):
        return send_from_directory(DASHBOARD_DIR, path)

    _, ext = os.path.splitext(path)
    if not ext:
        return send_from_directory(DASHBOARD_DIR, "index.html")

    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=DEBUG)
