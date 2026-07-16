# Paper Trading Bot System

6 concurrent paper trading bots with SQLite persistence, Flask API, and HTML dashboard.

## Quick Start

```bash
pip install -r requirements.txt
python cli.py init
python cli.py run
```

## CLI Commands

| Command | Description |
|---|---|
| `python cli.py init` | Create DB + default bots |
| `python cli.py run` | Run all bots |
| `python cli.py run --bot sma_crossover` | Run one bot |
| `python cli.py status` | Portfolio status table |
| `python cli.py leaderboard` | Ranked by P&L % |
| `python cli.py report` | Daily summary |
| `python cli.py report --bot momentum --days 7` | Bot report |
| `python cli.py history --bot dca` | Trade/order history |
| `python cli.py reset --bot pairs` | Reset one bot |
| `python cli.py reset` | Reset all bots |
| `python cli.py add-bot mybot --strategy momentum --capital 5000 --config '{"lookback":10,"top_n":2,"symbols":["AAPL","TSLA"]}'` | Custom bot |
| `python cli.py server` | Start dashboard server |

## Dashboard

```bash
python cli.py server  # starts on http://localhost:5000
```

Open `dashboard/index.html` in a browser (or visit http://localhost:5000).

## Strategies

| Name | Key | Description |
|---|---|---|
| SMA Crossover | `sma_crossover` | Fast/slow SMA cross signals |
| RSI Mean Reversion | `rsi_mean_reversion` | Buy oversold, sell overbought |
| Momentum | `momentum` | Top-N performers by lookback return |
| Bollinger Bands | `bollinger_bands` | Buy lower band, sell upper band |
| DCA | `dca` | Fixed dollar amount each run |
| Pairs Trading | `pairs_trading` | OLS spread z-score arbitrage |

## Cron (daily automation)

```bash
# Run daily at market close (4pm ET = 21:00 UTC)
0 21 * * 1-5 cd /root/trading-bots && python cli.py run >> logs/trading.log 2>&1

# Daily report (traded/not-traded breakdown, biggest movers, days since last trade)
15 21 * * 1-5 cd /root/trading-bots && python cli.py report >> logs/daily_report.log 2>&1
```

## Architecture

```
cli.py          → argparse entry point
server.py       → Flask REST API
src/
  db.py         → SQLite CRUD (trading.db)
  data_fetcher.py → yfinance + disk cache
  portfolio.py  → order execution (commission + slippage)
  bot_manager.py → orchestrates strategy runs
  reporter.py   → markdown reports
strategies/
  base.py       → AbstractBaseStrategy
  *.py          → concrete implementations
dashboard/
  index.html    → standalone SPA (Chart.js)
data/
  trading.db    → SQLite database
  cache/        → yfinance parquet cache (1h TTL)
```

## Costs & Realism

- **Commission**: 0.1% per trade
- **Slippage**: 0.05% (buy executes 0.05% above signal price, sell 0.05% below)
- **Data**: Daily OHLCV from yfinance (free, ~1y history)
- **Capital**: $10,000 per bot (configurable)
