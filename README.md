# TradeVed Backtester

Full-stack quantitative backtesting and stress-testing platform for **crypto**, **US stocks**, and **Indian markets (NSE/BSE)**.

- **Backend:** FastAPI + SQLite + Python 3.11+
- **Frontend:** React 18 + Vite + TypeScript + Tailwind CSS
- **Strategies:** Grid, DCA, PLA (EMA crossover + cascading entries)
- **Markets:** Binance (crypto), yfinance (US stocks / NSE / BSE), CoinGecko

---

## Features

### Backtester
- **3 strategies** — Grid (price-level crossing), DCA (interval buys), PLA (EMA crossover + cascading)
- **3 markets** — Crypto (Binance / CoinGecko), US stocks (yfinance), Indian NSE/BSE
- **Indian cost model** — STT + NSE exchange charges + SEBI + GST at Budget 2024 rates
- **Indian F&O** — Lot-size enforcement for futures/options (NIFTY50, BANKNIFTY, FINNIFTY, etc.)
- **Walk-forward validation** — Out-of-sample testing with configurable windows
- **Regime detection** — Timeframe-aware bull / bear / sideways labelling
- **Smart Fill** — Auto-fills capital and strategy params from the current symbol
- **GRID auto-bounds** — Detects price range automatically when bounds are left at 0

### Stress Tester
- **17 scenario presets** — 13 global (GFC 2008, COVID crash, LUNA collapse, slow bleed, pump & dump…) + 4 Indian-specific (Demonetization 2016, COVID NIFTY, Yes Bank Collapse, F&O Expiry Gamma Squeeze)
- **SSE streaming** — Live Monte Carlo paths building up in real time on a canvas chart
- **Monte Carlo** — 100+ runs with per-run magnitude jitter (`severity × uniform(0.75, 1.25)`)
- **Delta mode** — Toggle between absolute equity and % impact vs baseline
- **All markets supported** — works with all 3 strategies across every data source

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Node.js 18+
- Git

### 2. Clone & set up Python environment

```bash
git clone <repo-url>
cd "TradeVed Backtester"

# Create and activate virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r backtester/requirements.txt
```

### 3. Configure environment variables

```bash
cp backtester/.env.example backtester/.env
```

Edit `backtester/.env` and fill in your credentials (see [Environment Variables](#environment-variables) below).

> **Note:** Fyers and TradingView credentials are optional. The platform works without them using Binance and yfinance as data sources.

### 4. Install frontend dependencies

```bash
cd backtester/frontend
npm install
```

### 5. Run the app

Open two terminals:

```bash
# Terminal 1 — Backend (FastAPI on :8000)
cd backtester
python main.py
```

```bash
# Terminal 2 — Frontend (Vite on :5173)
cd backtester/frontend
npm run dev -- --port 5173
```

- **UI:** http://localhost:5173
- **API docs (Swagger):** http://localhost:8000/docs

> If port 8000 is already in use, kill the old process first:
> ```powershell
> Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue
> ```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values. All fields are optional — the platform runs without them.

| Variable | Required | Description |
|----------|----------|-------------|
| `TV_USERNAME` | No | TradingView email |
| `TV_PASSWORD` | No | TradingView password |
| `TV_SESSIONID` | No | TradingView sessionid cookie (for Google OAuth accounts) |
| `FYERS_CLIENT_ID` | No | Fyers API client ID (free NSE/BSE intraday data) |
| `FYERS_SECRET_KEY` | No | Fyers API secret key |
| `FYERS_REDIRECT_URI` | No | Fyers redirect URI (default: `https://fyers.in`) |
| `FYERS_ACCESS_TOKEN` | No | Fyers access token — expires daily, regenerate as needed |

---

## Project Structure

```
backtester/
├── main.py                    # FastAPI app — all routes and orchestration
├── config.py                  # Paths, constants, logging setup
├── database.py                # SQLAlchemy models + session
├── models.py                  # Pydantic request/response schemas
├── run_backtest.py            # CLI entrypoint (no server required)
├── test_all.py                # 37-test pytest suite
├── .env.example               # Environment variable template
│
├── data/
│   ├── fetcher.py             # OHLCV fetch: Binance, CoinGecko, yfinance
│   ├── indian_assets.py       # NSE/BSE symbols, FO_LOT_SIZES, INDEX_MAP
│   ├── validator.py           # Data quality checks
│   └── eda.py                 # Exploratory data analysis helpers
│
├── strategies/
│   ├── base.py                # BaseStrategy ABC
│   ├── grid.py                # Grid strategy
│   ├── dca.py                 # DCA strategy
│   └── pla.py                 # PLA (EMA crossover + cascading entries)
│
├── engine/
│   ├── simulator.py           # TradeSimulator — WACB, partial fills, lot-size
│   ├── cost_models.py         # IndianCostModel (Budget 2024), SimpleCostModel
│   ├── metrics.py             # Sharpe, Sortino, Calmar, MDD, Profit Factor
│   ├── regimes.py             # Timeframe-aware regime detection
│   ├── stress.py              # Stress engine: 13 scenarios + Monte Carlo
│   └── validation.py          # Walk-forward / out-of-sample engine
│
├── optimizer_results/         # CSV + HTML output from optimizer runs
├── crypto_optimizer.py        # Grid/DCA/PLA sweep on BTC/ETH/BNB/SOL
├── indian_futures_optimizer.py# Grid/DCA/PLA sweep on NSE F&O (792 runs)
│
├── qa_reports/                # QA Excel reports (test coverage, defect log)
│
└── frontend/
    ├── src/
    │   ├── App.tsx            # Root — page routing (backtest | stress)
    │   ├── api.ts             # API clients + SSE stream handler
    │   ├── types.ts           # TypeScript types
    │   └── components/
    │       ├── Sidebar.tsx        # Backtest form + Smart Fill
    │       ├── MetricsGrid.tsx    # Performance metrics display
    │       ├── TradeLog.tsx       # Trade table (sortable)
    │       ├── ChartsPanel.tsx    # Equity / drawdown / candlestick charts
    │       ├── MCPathsCanvas.tsx  # Canvas-based Monte Carlo spaghetti chart
    │       ├── StressPage.tsx     # Stress page root + SSE state machine
    │       ├── StressSidebar.tsx  # Stress form + Smart Fill
    │       └── StressResults.tsx  # Verdict, compare cards, MC panels
    ├── package.json
    ├── vite.config.ts
    └── tailwind.config.js
```

---

## API Reference

### Backtest
```
POST /api/backtest/run             Run a backtest
GET  /api/strategies               List strategies + default params
GET  /api/strategies/grid/bounds   Auto-detect GRID price range for a symbol
GET  /api/india/cost_preview       Preview Indian transaction costs
```

### Stress Test
```
POST /api/stress/run               Sync stress test (all MC runs at once)
POST /api/stress/stream            SSE streaming stress test (live path updates)
GET  /api/stress/scenarios         List all 13 scenario presets
```

### Data
```
GET /api/data/{symbol}             Fetch OHLCV data
GET /api/data/{symbol}/quality     Data quality score
```

---

## Strategies

### Grid
Buys when price drops through a level below `lower_bound`; sells when it rises through a level above `upper_bound`. Leave both at `0` to auto-detect from price history with a ±10% pad.

| Param | Description |
|-------|-------------|
| `lower_bound` / `upper_bound` | Price range (0 = auto) |
| `num_levels` | Number of grid levels |
| `spacing` | `linear` or `exponential` |
| `invest_per_level_usd` | Capital per level |

### DCA
Buys a fixed amount at regular time intervals regardless of price direction.

| Param | Description |
|-------|-------------|
| `buy_interval_hours` | Interval between buys |
| `invest_per_buy_usd` | Amount per buy |
| `hold_days` | Max hold period |
| `exit_type` | `time` or `profit` |
| `profit_target_pct` | Exit when profit exceeds this % |

### PLA (EMA crossover + cascading)
Enters on a golden cross (fast EMA > slow EMA). If price dips after entry, fires cascading buy orders at configured levels. Best with Daily candles.

| Param | Description |
|-------|-------------|
| `fast_ema` / `slow_ema` | EMA periods for crossover signal |
| `entry_levels` | Dip levels for cascading entries e.g. `[0, -1, -2.5, -4]` |
| `invest_per_level_usd` | Capital per cascade level |
| `exit_type` | `crossover`, `take_profit`, or `stop_loss` |

---

## Indian Market Notes

| Market type | STT | Lot size |
|-------------|-----|----------|
| `equity_delivery` | 0.1% both legs | 1 |
| `equity_intraday` | 0.025% sell only | 1 |
| `futures` | 0.02% sell only | per symbol |
| `options` | 0.1% on sell premium | per symbol |

F&O: invest amount must cover at least 1 lot (`lot_size × approx_price`). The backend returns HTTP 422 with the minimum required amount if the capital is insufficient.

Key F&O lot sizes: NIFTY50 = 50, BANKNIFTY = 15, FINNIFTY = 40, SENSEX = 10.

---

## Metrics

| Metric | Formula |
|--------|---------|
| Sharpe | `mean_daily_return / std × √252` (rf = 0) |
| Sortino | `mean_daily_return / downside_std × √252` |
| Calmar | `annualised_return / │max_drawdown│` |
| Max Drawdown | Rolling peak-to-trough on equity curve |
| Win Rate | % profitable trades — returned as 0–100 (not 0–1) |
| Profit Factor | Gross profit / gross loss |

---

## Stress Scenarios

17 presets total — 13 global + 4 Indian-market specific.

| Key | Display Name | What it simulates |
|-----|-------------|-------------------|
| `gfc_2008` | 2008 GFC Replay | 37% crash over 252 days with 2 partial bounces |
| `covid_crash` | 2020 COVID Flash Crash | 34% crash in 30 days, 60% recovery over 45 days |
| `flash_crash_2010` | 2010 Flash Crash | 9% single-day drop + outlier wick events |
| `luna_collapse` | LUNA-style Collapse | 95% crash in 7 days, no recovery |
| `liquidity_drought` | Liquidity Drought | Spread/slippage multipliers, no price drift |
| `pump_dump` | Pump & Dump | 50% pump over 5 days then 60% dump |
| `whipsaw_chop` | Whipsaw Chop | ±5% mean-reverting chop for 60 days |
| `slow_bleed` | Slow Bleed Bear | 40% drift down over 180 days |
| `vol_spike` | Vol Spike (VIX-style) | 3× volatility multiplier for 30 days |
| `gap_risk` | Gap Risk | 10 random overnight gap events (3–8%) |
| `range_bound` | Range-bound Consolidation | ±2% mean-reverting chop for 90 days |
| `trend_reversal` | Trend Exhaustion + Reversal | 25% down then 30% recovery |
| `outlier_injection` | 20-30% Outlier Injection | 5 random outlier candles (20–30%) |
| `demonetization_2016` | India Demonetization 2016 | 15% drop over 30d + gap events (Indian markets) |
| `covid_nifty_mar2020` | COVID NIFTY Crash Mar 2020 | 38% crash + 70% recovery + gap events (NSE) |
| `yes_bank_2020` | Yes Bank Collapse 2020 | 85% drop over 120d + heavy gap events (NSE) |
| `expiry_gamma_squeeze` | F&O Expiry Gamma Squeeze | 4× vol + gap + outlier events (F&O specific) |

---

## Running Tests

```bash
# Unit + integration tests (37 tests)
cd backtester
python -m pytest test_all.py -v
```

---

## CLI Runner (no server required)

```bash
python run_backtest.py --symbol BTC/USDT --strategy DCA --start 2022-01-01 --end 2024-01-01
python run_backtest.py --symbol NIFTY50  --strategy GRID --source nse --capital 500000
python run_backtest.py --all
```

---

## Optimizers

Pre-built sweep scripts for finding the best strategy + param combinations:

```bash
# Crypto: Grid/DCA/PLA on BTC/ETH/BNB/SOL (~432 runs, outputs HTML report)
python crypto_optimizer.py

# Indian F&O: Grid/DCA/PLA on NSE futures (~792 runs)
python indian_futures_optimizer.py
```

Results are saved to `optimizer_results/` as CSV and HTML.
