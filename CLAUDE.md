# TradeVed Backtester — CLAUDE.md

Auto-loaded by Claude Code every session. Keep it accurate; update when architecture changes.

---

## Project Overview

**TradeVed Backtester** — a full-stack quantitative backtesting platform for crypto, US stocks, and Indian markets (NSE/BSE). Includes a full **Stress Tester** with 17 scenario presets (13 global + 4 Indian-specific), SSE-streamed Monte Carlo simulation, canvas-based live spaghetti chart, and delta-view toggle.

- **Backend:** FastAPI + SQLite + Python 3.11+
- **Frontend:** React 18 + Vite + TypeScript + Tailwind CSS
- **Working directory:** `backtester/` (all `python` commands run from here)

---

## How to Run

```powershell
# Kill old backend process if port 8000 is in use
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force

# Terminal 1 — Backend (FastAPI on :8000)
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester\backtester"
python main.py

# Terminal 2 — Frontend (Vite on :5173)
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester\backtester\frontend"
npm run dev -- --port 5173
```

API docs: http://localhost:8000/docs  
UI: http://localhost:5173

---
# TradeVed

Frontend:
React + Vite + TS

Backend:
FastAPI

Testing:
- test_all.py
- qa_validation.py

Design:
Figma is source of truth

Research:
Use Exa

Documentation:
Use Context7

UI Validation:
Use Playwright

Production Bugs:
Use Sentry

Browser Testing:
Use Browserbase

Market Regimes:
Bull, Bear, Sideways

Validation:
Walk Forward
Out of Sample
Monte Carlo
Stress Testing

## Repo Layout

**Per-project structure (July 2026 restructure):** each of the six projects has its own folder at the **repo root**, containing `backend/` (Python package) and `frontend/` (React components). The shared app shell — FastAPI routes, DB, schemas, tests, and the Vite app — lives in `backtester/`. The server still runs from `backtester/` (`python main.py`); a `sys.path` shim in each entrypoint makes the root-level project packages importable.

```
<repo root>/
├── backtesting/               # PROJECT 1 — core backtest engine
│   ├── backend/
│   │   ├── engine/            # simulator.py (WACB/lots), cost_models.py, metrics.py,
│   │   │                      #   regimes.py, indicators.py, validation.py
│   │   ├── strategies/        # STRATEGY_REGISTRY: GRID/DCA/PLA + indicator presets + CUSTOM
│   │   ├── data/              # fetcher.py, indian_assets.py, validator.py, eda.py
│   │   └── reporting/         # charts.py (Plotly), report.py (HTML reports)
│   └── frontend/              # Sidebar, MetricsGrid, TradeLog, ChartsPanel, RegimeBreakdown, ValidationPanel
│
├── stress_testing/            # PROJECT 2 — crisis stress tester
│   ├── backend/stress.py      # 17 scenarios, apply_stress(), run_stress_backtest(), MC engine
│   └── frontend/              # StressPage, StressSidebar, StressResults, MCPathsCanvas
│
├── forward_testing/           # PROJECT 3 — AI forward testing (Kronos + bootstrap)
│   ├── backend/forecast.py    # KronosClient, block bootstrap, generate_paths/generate_one_path
│   ├── kronos_service/        # Modal GPU service (deploy: modal deploy forward_testing/kronos_service/modal_app.py)
│   └── frontend/              # ForwardTestPage, ForwardTestSidebar, ForwardTestResults
│
├── paper_trading/             # PROJECT 4 — routes live in shared main.py (see its README)
│   └── frontend/PaperTradeView.tsx
│
├── reel_to_backtest/          # PROJECT 5 — reel → strategy extraction
│   ├── backend/               # ingestion.py, reel_extractor.py, ir_validator.py, improvement_agent.py
│   └── frontend/              # ReelPage, StrategyIREditor, PlainLanguageVerdict, StrategyImprovement
│
├── reel_to_pipeline/          # PROJECT 6 — unified pipeline orchestrator
│   ├── backend/               # pipeline.py (checkpoint/loop/best-IR revert), stages.py, cache.py
│   └── frontend/PipelinePage.tsx
│
├── backtester/                # SHARED APP SHELL (server runs from here)
│   ├── main.py                # FastAPI app — ALL routes for every project
│   ├── config.py              # Paths, constants, logging (anchored to __file__, cwd-independent)
│   ├── database.py            # SQLAlchemy models + session
│   ├── models.py              # Pydantic request/response schemas
│   ├── test_*.py, conftest.py # Entire pytest suite (run from backtester/, collects everything)
│   ├── run_backtest.py, crypto_optimizer.py, indian_futures_optimizer.py   # CLI scripts
│   └── frontend/              # Vite app shell: App.tsx, api.ts, types.ts, analytics.ts,
│       └── src/components/shared/   # IdentityGate, FeedbackWidget, AdminDashboard,
│                                     #   StrategyParamsForm, RuleBuilder
│
├── package.json               # npm workspaces root — `npm install` HERE (hoists node_modules to root)
└── vercel.json                # installCommand: npm install (root); build: cd backtester/frontend && npm run build
```

**Import convention:** `from backtesting.backend.engine.simulator import TradeSimulator`, `from stress_testing.backend.stress import run_stress_backtest`, `from forward_testing.backend import forecast`, `from reel_to_backtest.backend.ir_validator import validate_ir`, `from reel_to_pipeline.backend import pipeline`. Shared modules keep bare imports (`from database import ...`) — resolvable because the server/tests run from `backtester/`.

**Frontend aliases** (vite.config.ts + tsconfig paths): `@app` → `backtester/frontend/src`, `@backtesting` / `@stress` / `@forward` / `@paper` / `@reelbt` / `@reelpipe` → each project's `frontend/` folder. Tailwind `content` globs include all six project frontend folders — a new project folder MUST be added there or its classes get purged from the build.

**npm install must run at the repo root** (workspaces hoist deps to root `node_modules` so project frontend files outside the Vite root can resolve react etc.). Do not run `npm install` inside `backtester/frontend/` — it would recreate a nested `node_modules`/lockfile and break hoisting.

---

## Key Architecture Decisions

### Cost Models
- **SimpleCostModel:** flat % fee per leg (crypto / US stocks)
- **IndianCostModel:** itemised STT + NSE exchange charges + SEBI + GST (18% on brokerage+ETC+SEBI) + stamp duty — Budget 2024 rates
- `_calculate_cost(turnover, side, track=True/False)` — `track=False` for provisional estimates, `track=True` for final recorded calls. This prevents double-counting in `cost_breakdown`.

### Simulator
- **WACB** (Weighted-Average Cost Basis): `new_avg = (old_qty*old_avg + new_qty*price) / total_qty`
- **Lot-size enforcement:** `math.floor(qty / lot_size) * lot_size` — only when `lot_size > 1`
- **`lot_size_skips`:** counter for BUY signals skipped because qty < 1 lot after floor rounding
- **Partial fills:** if cash < required, back-solve for affordable qty

### Indian Market
- Auto-detection: `req.source in ("nse","bse") or is_indian(req.symbol)` → `use_indian_costs=True`
- Lot sizes from `backtesting/backend/data/indian_assets.py:FO_LOT_SIZES` — applied only for `market_type in ("futures","options")`
- `get_lot_size(symbol)` returns 1 for non-F&O instruments
- 422 raised when lot_sz > 1, 0 trades, and BUY signals existed (with guidance message)

### F&O Lot Sizes (key ones)
| Symbol | Lot Size | Symbol | Lot Size |
|--------|----------|--------|----------|
| NIFTY50 | 50 | BANKNIFTY | 15 |
| FINNIFTY | 40 | SENSEX | 10 |
| RELIANCE | 250 | HDFCBANK | 550 |
| TCS | 150 | SBIN | 1500 |

### Market Types
| Type | STT | Lot Size | Use case |
|------|-----|----------|----------|
| `equity_delivery` | 0.1% buy+sell | 1 | CNC, long-term stocks/ETFs |
| `equity_intraday` | 0.025% sell | 1 | MIS intraday trades |
| `futures` | 0.02% sell | per symbol | NRML futures contracts |
| `options` | 0.1% on sell premium | per symbol | CE/PE contracts (cost model only; P&L uses underlying price) |

### Strategies
**GRID** — buys at price levels below a threshold, sells above. Params: `lower_bound`, `upper_bound`, `num_levels`, `spacing` (linear/exponential), `invest_per_level_usd`.

**DCA** — buys at fixed time intervals. Params: `buy_interval_hours`, `invest_per_buy_usd`, `hold_days`, `exit_type` (time/profit), `profit_target_pct`.

**PLA** — EMA crossover entry + cascading average-down. Params: `fast_ema`, `slow_ema`, `entry_levels` [0, -1, -2.5, -4], `invest_per_level_usd` [L1, L1, 2×L1, 3×L1], `exit_type` (crossover/take_profit/stop_loss). **Cascades only fire if price dips below entry after golden cross — use Daily candles, not Weekly.**

These three are the **classic** strategies (category `classic`). See **Indicator Engine & Strategy Extension** below for the indicator presets and rule builder.

### Indicator Engine & Strategy Extension (ROADMAP.md Track 1)
- **`backtesting/backend/engine/indicators.py`** — pure pandas/numpy indicator engine (NO pandas-ta: it breaks on the pinned numpy 2.4 / pandas 3.0). `INDICATOR_CATALOG` (25 indicators, 40 output series, grouped overlap/momentum/trend/volatility/volume) + `compute(df, key, **params) -> DataFrame` with stable output column names (`rsi`, `macd_signal`, `bb_lower`, …). Wilder smoothing in `rma()` is SMA-seeded (RSI/ATR/ADX match textbook values). Exposed via `GET /api/indicators`.
- **Schema-driven params:** `BaseStrategy.parameter_schema()` returns structured UI metadata per param (`type/label/min/max/step/options/group/depends_on`), built by `param_schema()` (rich declarations via the `Param(...)` helper) overlaid on values auto-derived from `default_params()`. `BaseStrategy.category()` returns `classic|indicator|custom`. `GET /api/strategies` now returns `category` + `schema` alongside flat `parameters`.
- **`signals_from_masks(df, entry_mask, exit_mask, invest_usd, qty_fallback)`** (in `backtesting/backend/strategies/base.py`) — shared long-only state machine converting boolean masks → signal/quantity/meta. Used by every indicator preset AND the rule builder, so signal-walking lives in one place.
- **Indicator presets** (category `indicator`, registered in `STRATEGY_REGISTRY`): `RSI`, `MACD`, `BOLLINGER`, `SUPERTREND`, `DONCHIAN`, `MACROSS`. Each uses `compute()` + `signals_from_masks`, dollar-or-units sizing via `invest_per_trade_usd`/`quantity`.
- **Rule builder** (`backtesting/backend/strategies/custom.py: CustomStrategy`, category `custom`, name `CUSTOM`): `entry_rules`/`exit_rules` are condition lists (`{left, operator (>/</>=/<=/cross_above/cross_below), right}` where operands are `{indicator,params,output}` | `{price}` | `{value}`), combined via `logic` AND/OR. Evaluator computes indicators via the engine → boolean masks → `signals_from_masks`.
- **Frontend (hybrid):** classic GRID/DCA/PLA keep their dedicated flat form fields; all other strategies use the schema-driven `StrategyParamsForm.tsx` (renders from `/api/strategies` schema, honors `group`/`depends_on`), and `CUSTOM` uses `RuleBuilder.tsx` (fetches `/api/indicators`). `FormState`/`StressFormState` gained `strategyParams: Record<string, unknown>`; `Strategy` type is now `string`; `buildStrategyParams` returns `strategyParams` for non-classic strategies. The strategy dropdown (Sidebar + StressSidebar) is populated from `/api/strategies`, grouped by category.

### Strategy-Outcome Logging (ROADMAP.md Track 2 / Phase 0 — moat seed)
- `models.StrategyOutcome` table: append-only `{strategy, category, params, symbol, source, interval, dates, regime_mix, outcome metrics}` written on every backtest (best-effort; a logging failure never fails the run). Auto-created via `create_all` — no migration. Seeds the future strategy-intelligence ranker. Observable via `GET /api/strategy-outcomes/summary`.

### Metrics (all via `backtesting/backend/engine/metrics.py`)
- Annualisation: `TRADING_DAYS_PER_YEAR = 252`
- Sharpe: `(mean_daily_return - rf) / std_daily_return * sqrt(252)` — `rf = 0`
- Sortino: uses only negative daily returns for denominator
- Calmar: `annualised_return / abs(max_drawdown)`
- MDD: rolling peak-to-trough on equity curve
- `win_rate` is returned as **0–100 range** (e.g. 57.5 means 57.5%), NOT 0–1. Do not multiply by 100.

### Regime Detection (`backtesting/backend/engine/regimes.py`)
- **Timeframe-aware MA windows:** windows are sized in real trading days using `_candles_per_day(timestamps)`, then converted back to candles. A 1d and 4h backtest of the same period get semantically equivalent labels.
- `method` field returns `"ma_trend_tf_aware"` — consumers can detect the new logic.
- `classify_regimes(df)` is called from `main.py` after every backtest.

### Stress Tester (`stress_testing/backend/stress.py`)
- **`apply_stress(df, scenario, severity, seed)`** — pure function, deep-copies input, returns perturbed OHLCV DataFrame. Never mutates input.
- **`_apply_drift(..., persist=True/False)`** — `persist=True` means prices from `end` onwards are also scaled by the final multiplier (no snap-back). Used for all "permanent" crash scenarios.
- **17 presets** in `SCENARIO_PRESETS` dict (13 global + 4 Indian: `demonetization_2016`, `covid_nifty_mar2020`, `yes_bank_2020`, `expiry_gamma_squeeze`). Key presets with `persist=True`:
  - `luna_collapse` (95% crash, no recovery), `slow_bleed` (40% over 180d), `gfc_2008` (37% over 252d with bounces), `pump_dump` (dump persists), `trend_reversal` (reversal persists), `covid_crash` (crash + recovery both persist)
- **`run_stress_backtest()`** returns: `scenario`, `baseline`, `stressed`, `monte_carlo`, `series`
  - `stressed` includes: `return_pct`, `sharpe`, `sortino`, `calmar`, `max_dd_pct`, `win_rate`, `num_trades`, `final_equity`, `annualized_return`
  - `monte_carlo` includes: `return_pct`, `max_drawdown_pct`, `sharpe`, `sortino`, `win_rate` percentiles + `per_run` list
  - `series.spaghetti` — up to 100 equity curves subsampled to 200 points each
- **Per-run magnitude variation:** each MC run uses `severity × uniform(0.75, 1.25)` so paths fan out realistically (timing AND intensity vary). Without this all runs are nearly identical.
- **`aggregate_stress_results(baseline, per_run, equity_curves, price_curves, df, capital, scenario, severity)`** — standalone aggregation helper used by the SSE streaming endpoint after collecting runs one-by-one.
- **`run_single_backtest`** — public alias for `_single_backtest`, imported by the SSE endpoint in `main.py`.
- **Three endpoints:**
  - `POST /api/stress/run` — sync, returns full result in one shot
  - `POST /api/stress/stream` — **async SSE**, yields events per run (`baseline` → `run` × N → `complete`)
  - `GET /api/stress/scenarios` — returns all 17 preset metadata

### SSE Streaming (`POST /api/stress/stream`)
- Implemented as an `async def` FastAPI route returning `StreamingResponse(media_type="text/event-stream")`
- Each blocking computation (`apply_stress`, `_single_backtest`) runs via `asyncio.to_thread` so events flush between iterations
- Event types:
  - `{type: "baseline", metrics: {...}}` — sent first after computing the no-stress run
  - `{type: "run", run_num: N, total: N, metrics: {...}, equity: [...]}` — one per MC iteration; equity is ≤200-point subsampled curve
  - `{type: "complete", result: {...}}` — same shape as `/api/stress/run`, sent when all runs finish
  - `{type: "error", message: "..."}` — on any failure
- Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no` (disables nginx buffering)

### Canvas MC Paths Chart (`MCPathsCanvas.tsx`)
- HTML Canvas (not Recharts SVG) — handles 1000+ paths without performance degradation
- **Color:** HSL spectrum based on run return — red (−50%+) → yellow (0%) → teal (+50%+), opacity 28%
- **Incremental drawing:** `drawnCountRef` tracks last drawn run; new runs append without full redraw
- **High-DPI:** canvas dimensions scaled by `window.devicePixelRatio`; `ResizeObserver` for container width changes
- **Hover:** finds nearest equity path within 28px; shows tooltip with return/DD/Sharpe/Win%
- **Click to pin:** selected path turns orange, held on top; chip shows selected run
- **Delta mode toggle (top-right button):** switches Y-axis from absolute equity to `(stressed − baseline) / baseline × 100%`. Y-axis labels show `+X%` / `−X%`. Zero line drawn in delta mode. More useful than absolute equity for seeing stress *impact*.
- Works in both `isLive=true` (live streaming, incremental) and `isLive=false` (static, full redraw) modes.

### Stress Frontend (`StressSidebar` + `StressPage` + `StressResults`)
- **`StressSidebar`:** source-aware symbol dropdown, date presets (1M–5Y), Smart Fill, severity pills, advanced overrides accordion, MC runs picker. Unchanged.
- **`StressPage`:** now a streaming state machine with states: `idle → live → complete | error`
  - In `live` state: shows `LiveLoadingView` — animated canvas with paths building up, progress bar (indigo→orange gradient), run counter `X / N`, 4-stat strip (latest return, latest Sharpe, best/worst so far), baseline chip
  - Uses `streamStressTest()` from `api.ts`; stores cleanup ref to abort on re-run
- **`StressResults`:** `SpaghettiFanChart` (Recharts) replaced with `MCPathsCard` (wraps `MCPathsCanvas`). All other panels unchanged.
- **`MCPathsCard`:** wraps the canvas, has filter pills (All/Profitable/Loss), run log table (sortable by Return/MaxDD/Sharpe).

---

## Frontend State

`DEFAULT_FORM` in `App.tsx` — all backtest form defaults.  
`DEFAULT_STRESS_FORM` in `StressSidebar.tsx` — all stress form defaults.

`buildStrategyParams(form)` in `api.ts` — converts FormState → backend `params` dict. Used by `runBacktest()`, `runStressTest()`, and `streamStressTest()`.

### Page Navigation
`App.tsx` has `page: 'backtest' | 'stress'` state. Top nav has two pills — clicking switches pages. Stress page is full-width with its own sidebar; backtest page uses the original aside+main layout.

### Pre-flight Validation (Sidebar.tsx Run button)
Before allowing Run, checks:
1. `startDate < endDate`
2. For F&O (`futures`/`options`): `investAmt >= lotSize * approxPrice * 1.05`
3. For non-F&O: warns if `investAmt < capital * 0.005`

`FO_LOT_SIZES` and `APPROX_PRICES` lookup tables are duplicated in `Sidebar.tsx` (frontend copy for pre-flight checks — keep in sync with `backtesting/backend/data/indian_assets.py`).

---

## Common Bugs / Gotchas

| Issue | Root cause | Fix applied |
|-------|-----------|-------------|
| `cost_breakdown.total` ≈ 2× `total_fees_paid` | `_calculate_cost` called twice on partial fills | `track=False` for provisional call, `track=True` for confirmed |
| Futures 0 trades, no error | Sub-lot quantities silently rounded to 0 | `lot_size_skips` counter + 422 HTTPException with guidance |
| PLA dip levels change nothing | (1) Invest amount too small; (2) Weekly candles rarely dip enough | Pre-flight invest warning + cascade dip hint in UI |
| `$` everywhere on Indian backtests | Hardcoded `$` in Summary JSON panel + `en-US` locale | All replaced with `currency` variable + `en-IN` locale |
| Indian source resets to Futures | `marketType` not reset on source switch | Source switch now sets `marketType: 'equity_delivery'` |
| GRID HTTP 500 / 0 trades (bounds 0,0) | `lower_bound == upper_bound == 0` → `ValueError` | `main.py` auto-detects from price history with ±10% pad (applies to `/api/backtest/run`, `/api/stress/run`, `/api/stress/stream`) |
| Stress GRID always 0 trades | Auto-bounds fix only existed in `/api/backtest/run`, not in `/api/stress/run` or `/api/stress/stream` | Added same auto-bounds block to both stress endpoints in `main.py` |
| Stress tester "not working" for Indian/new symbols | `mcRuns` defaulted to 1 (no distribution visible); switching source didn't reset capital/invest amounts | `mcRuns` default changed to 100; source switch now auto-Smart-Fills capital + strategy amounts for the new source |
| Backend freezes / watchfiles restarts | `reload=True` + log written every request → repeated restarts | `reload=False`; restart manually after code changes |
| `$` in ChartsPanel sub-components | 7 hardcoded `$` in EquityChart, PriceTradesChart, MonthlyHeatmap | `currency` + `locale` props passed from App.tsx |
| Stress crashes profitable (snap-back bug) | `_apply_drift` only modified [start,end]; prices snapped back after `end` | Added `persist=True` parameter |
| Stress `win_rate * 100` in UI | Frontend multiplied already-0-100 win_rate by 100 → "5769%" | Removed the `* 100` multiplication in `StressResults.tsx` |
| Stress symbol stuck on BTC/USDT when switching to NSE | StressSidebar used free-text input | Replaced with dropdown + `handleSourceChange` resets symbol |
| All MC paths identical / 0 loss paths | Severity was fixed per run; only shock *timing* varied → paths converge | Per-run `severity × uniform(0.75, 1.25)` — both timing AND magnitude vary |
| Port 8000 already in use on restart | Old process still running | `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force` |

---

## Optimization Results (Jan 2022 – Jan 2024)

### Crypto ($10,000/symbol, 4 symbols, 432 total runs)
| Symbol | Best Strategy | Return | Notes |
|--------|--------------|--------|-------|
| SOL/USDT | DCA (500/day, 14d, profit-exit 10%) | **+441%** | Crashed 95% (FTX), DCA accumulated, recovered |
| BTC/USDT | DCA | +159% | — |
| BNB/USDT | DCA | +73% | — |
| ETH/USDT | DCA | +65% | — |

**Why DCA wins crypto:** Crash-then-recover markets reward accumulation during lows.

### Indian Futures (₹ capital per symbol, 6 symbols, 792 total runs)
| Symbol | Best Strategy | Return | Sharpe | MDD |
|--------|--------------|--------|--------|-----|
| INFY | PLA EMA 9/21, tp=5%, inv=₹8.6L/lvl | **+20.4%** | **1.621** | -4.6% |
| BANKNIFTY | PLA EMA 9/21, tp=10% | +30.8% | 1.326 | -14.4% |
| HDFCBANK | PLA EMA 12/26, tp=5% | +31.1% | 1.142 | -12.2% |
| RELIANCE | GRID 5-lvl exponential, ₹3L/lvl | +6.1% | 1.563 | -1.5% |

**Composite score:** Sharpe 35% + Return 25% + Sortino 20% + Calmar 10% + MDD 10% (all min-max normalised).

### Stress Test Validation (207 tests — 13 scenarios × 3 strategies × 3 assets, 3 severities)
| Scenario | Median Δ% | Verdict | Notes |
|----------|-----------|---------|-------|
| luna_collapse | -11.8% | DEGRADED | Most dangerous; NIFTY50 PLA worst-hit (-37.4%) |
| slow_bleed | -7.6% | DEGRADED | DCA can't accumulate fast enough vs 40% drift |
| pump_dump | -6.7% | DEGRADED | Strategy buys into the pump, caught in dump |
| gfc_2008 | -4.5% | DEGRADED | DCA/GRID actually improve (accumulate during crash) |
| vol_spike / gap_risk | 0.0% | SURVIVED | Only affects candle shape, not close prices |

---

## Running Tests

```powershell
# Unit/integration tests (37 tests)
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester\backtester"
python -m pytest test_all.py -v

# Stress validation (207 tests, requires running backend on :8000)
python stress_validation.py
```

37 unit tests covering: data fetching (Binance/NSE/ETF), strategy signals (GRID/DCA/PLA), simulator (equity/futures), cost models (STT rates, GST), metrics (Sharpe/Sortino/Calmar), WACB, lot-size enforcement, data validator, timeframe-aware regimes, stress non-mutation, MC percentile ordering.

---

## Do NOT

- Do not add `pandas-ta` (or any TA lib that does `from numpy import NaN`) — it breaks on the pinned numpy 2.4 / pandas 3.0 and the Railway build. Add indicators to `backtesting/backend/engine/indicators.py` in pure pandas/numpy instead, and register them in `INDICATOR_CATALOG` (with `outputs` column names).
- Do not add a new strategy without registering it in `STRATEGY_REGISTRY` (`backtesting/backend/strategies/__init__.py`) and giving it a `CATEGORY` + `param_schema()`. The frontend dropdown and forms are driven by `/api/strategies`, so a registered strategy with a schema needs **zero** frontend changes (non-classic strategies render via `StrategyParamsForm`/`RuleBuilder` automatically).
- Do not add dedicated flat FormState fields for new strategies — only the three classic ones (GRID/DCA/PLA) use flat fields; everything else flows through `form.strategyParams`. `buildStrategyParams` returns `strategyParams` for non-classic strategies.
- Do not modify `FO_LOT_SIZES` in `Sidebar.tsx` without also updating `backtesting/backend/data/indian_assets.py` (they must stay in sync). Same applies to `StressSidebar.tsx`.
- Do not use `%%` in Python f-strings (prints two `%` signs — just use `%`)
- Do not call `_calculate_cost(..., track=True)` twice for the same trade leg
- Do not use `en-US` locale for Indian ₹ amounts — use `en-IN`
- Do not add `lot_size > 1` check without checking `market_type in ("futures", "options")`
- **Do not set `reload=True` in `uvicorn.run()`** — `logs/backtester.log` is written every request; watchfiles detects it every ~400ms, triggers repeated server restarts, and eventually deadlocks the event loop. Always use `reload=False` and restart manually after code changes.
- Do not hardcode `$` anywhere in the frontend — always use the `currency` variable (or prop). Applies to all chart sub-components and `MCPathsCanvas.tsx`.
- Do not leave GRID `lower_bound`/`upper_bound` at 0,0 without the auto-bounds guard in `main.py`.
- Do not call `_apply_drift` with `persist=False` for crash scenarios (luna_collapse, slow_bleed, gfc_2008, pump_dump, trend_reversal, covid_crash) — they require `persist=True` or the crash snaps back and creates buy-low-sell-high profits.
- Do not multiply `win_rate` by 100 in the frontend — `calculate_metrics` already returns it as 0–100.
- Do not add new stress scenario presets in `SCENARIO_PRESETS` without also adding them to `SCENARIO_DISPLAY`, `SCENARIO_GROUPS`, `SCENARIO_DEFAULTS` in `StressSidebar.tsx`, and `StressScenarioKey` union in `types.ts`.
- **Do not fix per-run severity back to a constant in the MC loop** — the `uniform(0.75, 1.25)` jitter is intentional. Without it, all MC runs share the same shock intensity and only differ in timing, producing near-identical paths with 0 loss runs even on severe scenarios.
- Do not use `SpaghettiFanChart` — it was removed and replaced with `MCPathsCanvas` / `MCPathsCard`. The old Recharts approach can't handle 1000+ lines.
