# TradeVed Backtester

Full-stack quantitative backtesting and stress-testing platform for **crypto**, **US stocks**, and **Indian markets (NSE/BSE)**.

- **Backend:** FastAPI + SQLite + Python 3.11+
- **Frontend:** React 18 + Vite + TypeScript + Tailwind CSS
- **Strategies:** Grid, DCA, PLA (EMA crossover + cascading entries)
- **Markets:** Binance crypto, yfinance (US/NSE/BSE), CoinGecko

---

## Quick Start

```powershell
# Kill any old backend process
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue

# Terminal 1 — Backend (FastAPI on :8000)
cd backtester
python main.py

# Terminal 2 — Frontend (Vite on :5173)
cd backtester/frontend
npm run dev -- --port 5173
```

- **UI:** http://localhost:5173
- **API docs:** http://localhost:8000/docs

---

## Features

### Backtester
- **3 strategies:** Grid (price-level crossing), DCA (interval buys), PLA (EMA crossover + cascading)
- **3 markets:** Crypto (Binance/CoinGecko), US stocks (yfinance), Indian NSE/BSE
- **Indian cost model:** STT + NSE exchange charges + SEBI + GST (Budget 2024 rates)
- **Indian F&O:** Lot-size enforcement for futures/options (NIFTY50, BANKNIFTY, etc.)
- **Walk-forward validation:** Out-of-sample testing with configurable windows
- **Regime detection:** Timeframe-aware bull/bear/sideways labelling
- **Smart Fill:** Auto-fills capital and strategy params from current symbol/source
- **GRID auto-bounds:** Auto-detects price range when bounds are left at 0

### Stress Tester
- **13 scenario presets:** GFC 2008, COVID crash, LUNA collapse, slow bleed, pump & dump, and more
- **SSE streaming:** Live Monte Carlo paths building up in real time on a canvas chart
- **Monte Carlo:** 100+ runs with magnitude jitter (`severity × uniform(0.75, 1.25)`) per run
- **Delta mode:** Toggle between absolute equity and % impact vs baseline
- **All markets supported:** Crypto, US stocks, Indian NSE/BSE — all 3 strategies

---

## Project Structure

```
backtester/
├── main.py                    # FastAPI app — all routes
├── config.py                  # Paths, constants, logging
├── database.py                # SQLAlchemy models + session
├── models.py                  # Pydantic request/response schemas
├── run_backtest.py            # CLI entrypoint (no server needed)
├── test_all.py                # 37-test pytest suite
│
├── data/
│   ├── fetcher.py             # OHLCV: Binance, CoinGecko, yfinance
│   ├── indian_assets.py       # NSE/BSE symbols, FO_LOT_SIZES, INDEX_MAP
│   ├── validator.py           # Data quality checks
│   └── eda.py                 # Exploratory data analysis
│
├── strategies/
│   ├── base.py                # BaseStrategy ABC
│   ├── grid.py                # Grid strategy
│   ├── dca.py                 # DCA strategy
│   └── pla.py                 # PLA (EMA crossover + cascading)
│
├── engine/
│   ├── simulator.py           # TradeSimulator — WACB, partial fills, lot-size
│   ├── cost_models.py         # IndianCostModel (Budget 2024), SimpleCostModel
│   ├── metrics.py             # Sharpe, Sortino, Calmar, MDD, Profit Factor
│   ├── regimes.py             # Timeframe-aware regime detection
│   ├── stress.py              # Stress engine: 13 scenarios, Monte Carlo
│   └── validation.py          # Walk-forward / train-test split engine
│
├── frontend/
│   ├── charts.py              # Plotly chart generation (HTML reports)
│   ├── report.py              # HTML report generator
│   └── src/                   # React/Vite UI
│       ├── App.tsx            # Root — page routing (backtest | stress)
│       ├── api.ts             # API clients + SSE stream handler
│       ├── types.ts           # TypeScript types
│       └── components/
│           ├── Sidebar.tsx        # Backtest form
│           ├── MetricsGrid.tsx    # Performance metrics display
│           ├── TradeLog.tsx       # Trade table
│           ├── ChartsPanel.tsx    # Equity/drawdown/candlestick charts
│           ├── MCPathsCanvas.tsx  # Canvas-based MC spaghetti chart
│           ├── StressPage.tsx     # Stress page root + SSE state machine
│           ├── StressSidebar.tsx  # Stress form + Smart Fill
│           └── StressResults.tsx  # Verdict, compare cards, MC panels
│
├── optimizer_results/         # CSV + HTML output from optimizer runs
├── crypto_optimizer.py        # Grid/DCA/PLA sweep on BTC/ETH/BNB/SOL
└── indian_futures_optimizer.py# Grid/DCA/PLA sweep on NSE F&O (792 runs)
```

---

## API Reference

### Backtest
```
POST /api/backtest/run          — run a backtest
GET  /api/strategies            — list strategies + default params
GET  /api/strategies/grid/bounds — auto-detect GRID price range
GET  /api/india/cost_preview    — preview Indian transaction costs
```

### Stress Test
```
POST /api/stress/run            — sync stress test (all MC runs at once)
POST /api/stress/stream         — SSE streaming stress test (paths in real time)
GET  /api/stress/scenarios      — list all 13 scenario presets
```

### Data
```
GET /api/data/{symbol}          — fetch OHLCV data
GET /api/data/{symbol}/quality  — data quality score
```

---

## Strategies

### Grid
Buys when price drops through a level below `lower_bound`; sells when it rises through a level above `upper_bound`. Leave both at `0` to auto-detect from price history (±10% pad).

Key params: `lower_bound`, `upper_bound`, `num_levels`, `spacing` (linear/exponential), `invest_per_level_usd`

### DCA
Buys a fixed amount at regular intervals regardless of price.

Key params: `buy_interval_hours`, `invest_per_buy_usd`, `hold_days`, `exit_type` (time/profit), `profit_target_pct`

### PLA (EMA crossover + cascading)
Enters on golden cross (fast EMA > slow EMA). If price dips below entry after signal, fires cascading buys at configured levels (requires Daily candles to generate enough dips).

Key params: `fast_ema`, `slow_ema`, `entry_levels` [0, -1, -2.5, -4], `invest_per_level_usd` [L, L, 2L, 3L], `exit_type` (crossover/take_profit/stop_loss)

---

## Indian Market Notes

| Market type | STT | Lot size |
|-------------|-----|----------|
| `equity_delivery` | 0.1% both legs | 1 |
| `equity_intraday` | 0.025% sell only | 1 |
| `futures` | 0.02% sell only | per symbol (NIFTY50=50, BANKNIFTY=15) |
| `options` | 0.1% on sell premium | per symbol |

F&O: invest amount must cover at least 1 lot (lot_size × price). If not, the backend returns HTTP 422 with the minimum required amount.

---

## Metrics

| Metric | Formula |
|--------|---------|
| Sharpe | `mean_daily_return / std * √252` |
| Sortino | `mean_daily_return / downside_std * √252` |
| Calmar | `annualised_return / |max_drawdown|` |
| Max Drawdown | Rolling peak-to-trough on equity curve |
| Win Rate | % profitable trades (0–100 range, not 0–1) |
| Profit Factor | Gross profit / gross loss |

---

## Running Tests

```powershell
# Unit/integration tests (37 tests)
cd backtester
python -m pytest test_all.py -v
```

---

## CLI Runner (no server)

```powershell
python run_backtest.py --symbol BTC/USDT --strategy DCA --start 2022-01-01 --end 2024-01-01
python run_backtest.py --symbol NIFTY50  --strategy GRID --source nse --capital 500000
python run_backtest.py --all
```
