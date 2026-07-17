# TradeVed Backtester — CONTEXT.md

Living progress document. Update after each session with what changed and what's next.  
Last updated: 2026-05-30 (session 4 — bug fixes, full audit, cleanup)

---

## Current Status

**Two pages shipped and working:**
1. **Backtest page** — original full-featured backtesting UI (stable)
2. **Stress Test page** — fully functional; SSE live loading; canvas MC chart

Backend running on `:8000` with `reload=False`. After any Python change:
```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester\backtester"
python main.py
```

---

## Feature Status

### Feature A — Timeframe-Aware Regime Detection ✅ DONE
**File:** `backtesting/backend/engine/regimes.py`

- Regime labels (bull/bear/sideways) now use real trading-day MA windows regardless of candle interval.
- A 1d and 4h backtest of the same period produce semantically equivalent labels.
- `method = "ma_trend_tf_aware"` in regime output signals new logic.
- **Test:** `test_regime_tf_aware` in `test_all.py` verifies 1d vs 4h labels agree within ±15pp.

---

### Feature B — Stress Tester ✅ DONE (full stack)

#### B1 — Backend (`stress_testing/backend/stress.py` + `main.py`)

**13 Scenario Presets:**

| Key | Display Name | Shock | Duration | Vol× | Persist |
|-----|-------------|-------|----------|------|---------|
| `gfc_2008` | 2008 GFC Replay | 37% down | 252d | 1.5 | Yes |
| `covid_crash` | 2020 COVID Flash Crash | 34% down + 60% V-recovery | 30d+45d | 2.5 | Yes |
| `flash_crash_2010` | 2010 Flash Crash | 9% single-candle | 1d | 3.0 | No |
| `luna_collapse` | LUNA-style Collapse | 95% down | 7d | 4.0 | Yes |
| `liquidity_drought` | Liquidity Drought | 5× slippage, 3× spread | 10d | 1.2 | No |
| `pump_dump` | Pump & Dump | +50% then -60% | 5d+3d | 2.0 | Yes (dump) |
| `gap_risk` | Gap Risk | 10 random ±3–8% gaps | — | 1.0 | No |
| `slow_bleed` | Slow Bleed Bear | 40% down | 180d | 1.0 | Yes |
| `vol_spike` | Vol Spike (VIX-style) | 3× candle ranges | 30d | 3.0 | No |
| `whipsaw_chop` | Whipsaw Chop | Mean-reverting ±5% | 60d | 2.5 | No |
| `range_bound` | Range-bound Consolidation | Mean-reverting ±2% | 90d | 1.0 | No |
| `trend_reversal` | Trend Exhaustion + Reversal | +30% then -25% | 60d+20d | 1.5 | Yes (reversal) |
| `outlier_injection` | 20–30% Outlier Injection | 5 random ±20–30% candles | — | 1.0 | No |

**Critical design: `persist=True`**  
Permanent crash scenarios use `_apply_drift(..., persist=True)` so prices after the shock window stay at the crashed level — no snap-back.

**Per-run magnitude jitter (session 3):**  
Each MC run uses `run_severity = severity × uniform(0.75, 1.25)`. Both timing AND intensity vary across runs, producing a proper fan of outcomes. Without this, all runs were near-identical (same shock depth, only start position varied).

**`run_stress_backtest()` response:**
- `stressed` — includes: `return_pct`, `sharpe`, `sortino`, `calmar`, `max_dd_pct`, `win_rate`, `num_trades`, `final_equity`, `annualized_return`
- `monte_carlo` — percentile stats for all above metrics + `per_run` list
- `series.spaghetti` — up to 100 equity curves × 200 points

**New helpers in `stress.py` (session 3):**
- `aggregate_stress_results(baseline, per_run, equity_curves, price_curves, df, capital, scenario, severity)` — standalone aggregation; called by the SSE endpoint after streaming all runs
- `run_single_backtest` — public alias for `_single_backtest`; imported by `main.py` SSE endpoint

**API endpoints:**
- `POST /api/stress/run` — sync, full result in one shot
- `POST /api/stress/stream` — **async SSE**, yields: `baseline` → `run × N` → `complete`
- `GET /api/stress/scenarios` — preset metadata

#### B2 — Frontend Components

**`StressSidebar.tsx`:** (updated session 4)
- Source-aware symbol dropdown, date presets (1M–5Y), Smart Fill, severity pills
- Monte Carlo presets: **50 / 100 / 250 / 500** + custom + time estimate warning (was 1/100/500/1000)
- Default `mcRuns` = **100** (was 1)
- `handleSourceChange` now auto-triggers Smart Fill for the new source's first symbol (capital + invest amounts reset correctly)
- Smart Fill bumps mcRuns to at least 100 if currently lower

**`StressPage.tsx`:** (rewritten in session 3)
- Streaming state machine: `idle → live → complete | error`
- In `live` state: **LiveLoadingView** with:
  - Animated canvas showing equity paths building up in real time
  - Progress bar (indigo→orange gradient) + `X / N` counter
  - 4-stat strip: latest return, latest Sharpe, best so far, worst so far
  - Baseline chip (appears when baseline event arrives)
- Uses `streamStressTest()` from `api.ts`; cleanup ref aborts stream on re-run
- No more loading spinner; the canvas IS the loading UI

**`MCPathsCanvas.tsx`:** (new in session 3)
- HTML Canvas — handles 1000+ paths without lag
- Rainbow color spectrum by return: red (large loss) → yellow (break-even) → teal (large gain)
- **Incremental drawing:** `drawnCountRef` — appends new paths without redrawing all
- **High-DPI:** `devicePixelRatio` scaling + `ResizeObserver` for width changes
- **Hover:** nearest path within 28px → tooltip (return, DD, Sharpe, Win%)
- **Click to pin:** selected path highlighted orange; chip top-right; click again to clear
- **Delta mode toggle (top-right button):** Y-axis becomes `% impact vs baseline`. Zero reference line drawn. Most useful view for seeing actual stress impact independent of market trend.

**`StressResults.tsx`:** (updated in session 3)
- `SpaghettiFanChart` (Recharts) replaced with `MCPathsCard` wrapping `MCPathsCanvas`
- `MCPathsCard` has filter pills (All/Profitable/Loss) + sortable run log table
- All other panels (verdict, compare cards, equity overlay, histograms, fan chart) unchanged

**`api.ts`:** (updated in session 3)
- `streamStressTest(form, callbacks)` — uses `fetch` + streaming reader to parse SSE events
  - Callbacks: `onBaseline`, `onRun`, `onComplete`, `onError`
  - Returns cleanup function (aborts stream)
- `StreamRun` interface — per-run event shape from the SSE stream

#### B3 — All Bugs Fixed (sessions 1–4)
| Bug | Fix |
|-----|-----|
| Crash scenarios profitable (snap-back) | `persist=True` in `_apply_drift` |
| `win_rate * 100` → 5769% | Removed multiplication; win_rate already 0–100 |
| Symbol stuck on BTC/USDT when switching to NSE | Source-aware dropdown + `handleSourceChange` |
| No Smart Fill button | Added `computeSmartDefaults` + ⚡ Smart Fill |
| All MC paths identical / 0 loss paths | Per-run `severity × uniform(0.75, 1.25)` — magnitude varies per run |
| Port 8000 already in use | Kill with `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force` |
| **Stress GRID always 0 trades** | Auto-bounds fix (lower=upper=0 → price range ±10%) was missing from `/api/stress/run` and `/api/stress/stream`; added to both |
| **"Failed to fetch" on stress run** | Vite proxy default ~60s timeout killed SSE connection; fixed with `timeout: 0, proxyTimeout: 0` in `vite.config.ts` |
| **`UnboundLocalError: n_runs`** | `n_runs = max(1, req.monte_carlo_runs)` was assigned after `yield ... n_runs` in `_generate()`; moved to top of function |
| **Stress tester "not working" for non-BTC symbols** | `mcRuns` default was `1` (no visible paths); changed to `100`. Source switch didn't reset capital/invest amounts; `handleSourceChange` now auto-Smart-Fills for the new source |
| **MC counter shows "0/0" during baseline** | Pre-populate `total: form.mcRuns` immediately on run start; backend also sends `"total": n_runs` in baseline event |

#### B4 — Test Coverage
- `test_stress_non_mutating` — all 13 scenarios: input not mutated, OHLCV valid
- `test_stress_monte_carlo_percentiles` — p5 ≤ p50 ≤ p95 ordering
- `stress_validation.py` — 207 tests, 100% pass rate

---

## Test Suite Summary

| Suite | Tests | Status | Notes |
|-------|-------|--------|-------|
| `pytest test_all.py` | 37 | ✅ All pass | Unit + integration |
| `stress_validation.py` | 207 | ✅ All pass | 13 scenarios × 3 strategies × 3 assets + severity variants |
| **Total** | **244** | ✅ | |

---

## File Inventory

### New files (session 3)
| File | Purpose |
|------|---------|
| `frontend/src/stress_testing/frontend/MCPathsCanvas.tsx` | Canvas-based MC paths chart: rainbow colors, hover, click-to-pin, delta view, incremental draw |

### New files (session 1–2)
| File | Purpose |
|------|---------|
| `stress_testing/backend/stress.py` | Stress engine: 13 scenarios, `apply_stress()`, `run_stress_backtest()`, `aggregate_stress_results()` |
| `frontend/src/stress_testing/frontend/StressPage.tsx` | Stress page root — SSE streaming state machine + live loading view |
| `frontend/src/stress_testing/frontend/StressSidebar.tsx` | Stress form controls |
| `frontend/src/stress_testing/frontend/StressResults.tsx` | Results panel: verdict, compare cards, MCPathsCard, MC panels |
| `stress_validation.py` | 207-test validation script |
| `CONTEXT.md` | This file |

### Modified files (session 3)
| File | What changed |
|------|-------------|
| `stress_testing/backend/stress.py` | Added `aggregate_stress_results()`, `run_single_backtest` alias, per-run `uniform(0.75,1.25)` severity jitter |
| `main.py` | Added `asyncio` import, `StreamingResponse`, `POST /api/stress/stream` SSE endpoint |
| `frontend/src/api.ts` | Added `streamStressTest()`, `StreamRun` interface |
| `frontend/src/stress_testing/frontend/StressPage.tsx` | Full rewrite: streaming state machine, `LiveLoadingView` with live canvas |
| `frontend/src/stress_testing/frontend/StressResults.tsx` | Replaced `SpaghettiFanChart` with `MCPathsCard` + `MCPathsCanvas` |

### Modified files (session 1–2)
| File | What changed |
|------|-------------|
| `backtesting/backend/engine/regimes.py` | Timeframe-aware MA windows |
| `main.py` | `StressRequest` model; `/api/stress/run`; `/api/stress/scenarios` |
| `frontend/src/App.tsx` | Page state + top nav page pills + stress page routing |
| `frontend/src/api.ts` | `runStressTest()`, `fetchStressScenarios()` |
| `frontend/src/types.ts` | All stress types: `SpaghettiRun`, `StressRunMetrics`, `StressMonteCarloResult`, `StressSeries`, `StressFormState`, `StreamRun` |
| `test_all.py` | 3 new tests: regime TF, stress non-mutation, MC percentiles (34 → 37 tests) |
| `CLAUDE.md` | Full architecture updates |

---

## Session 4 Changes (2026-05-30)

### Bugs Fixed
- **Stress GRID 0 trades** — Auto-bounds block added to `/api/stress/run` and `/api/stress/stream` in `main.py`
- **SSE "Failed to fetch"** — `timeout: 0, proxyTimeout: 0` in `vite.config.ts`
- **`UnboundLocalError: n_runs`** — moved `n_runs` assignment to top of `_generate()` in `main.py`
- **MC counter "0/0"** — `total: form.mcRuns` pre-populated on run start; backend sends `"total"` in baseline event
- **`mcRuns: 1` default** — changed to 100; MC pill buttons updated to [50, 100, 250, 500]
- **Source switch capital mismatch** — `handleSourceChange` now auto-Smart-Fills for new source

### Cleanup
- Deleted `backtester/reports/` (145 HTML files — auto-generated artifacts)
- Deleted `backtester/ppt_assets/` (27 files — intern PPT builder scripts)
- Deleted `backtester/app.py` (old Streamlit dashboard — replaced by React)
- Deleted `backtester/PROOF_SCREENSHOTS.md`, `TASK_TRACKER.md`, `REVIEW_REPORT.md`, `New Plan.md` (personal intern docs)
- Rewrote `backtester/README.md` (was crypto-only; now covers full platform)

### Audit Results (45/48 pass, 3 are correct behavior)
- 45 API tests PASS across DCA/GRID/PLA × BTC/NIFTY50/BANKNIFTY/SPY/RELIANCE/ETH/SOL × all 13 stress scenarios
- NIFTY50 Futures 422 = correct lot-size enforcement (invest too small — expected)
- Walk-forward `validation` key (not `walk_forward`) — correct, test script bug
- Cost preview `round_trip_pct` field (not `total_cost_pct`) — correct, test script bug

---

## Known Limitations / Backlog

| Priority | Item | Notes |
|----------|------|-------|
| Medium | Pin shock to specific date | Currently random within first 60% of data |
| Low | Stress + walk-forward | No stress variant for WF out-of-sample windows |
| Low | Volume-based regime detection | Current MA-trend only; no volume signal |
| Low | Indian cost model stress-test | `slip_multiplier` interaction with IndianCostModel untested |

---

## Architecture Notes for Next Session

**Adding a new stress scenario:**
1. Add `StressScenario(...)` to `SCENARIO_PRESETS` in `stress_testing/backend/stress.py`
2. Add the scenario handler block in `apply_stress()` (the big `if sname ==` chain)
3. Add key to `StressScenarioKey` union in `types.ts`
4. Add to `SCENARIO_DISPLAY`, `SCENARIO_GROUPS`, `SCENARIO_DEFAULTS` in `StressSidebar.tsx`

**Adding a new per-run metric:**
1. Add to `per_run.append(...)` in `run_stress_backtest()` and the SSE loop in `main.py`
2. Add field to `StressRunMetrics` in `types.ts`; add to `StreamRun` in `api.ts`
3. If MC percentile needed: add `_pcts(...)` call in `mc_result` dict (both `run_stress_backtest` and `aggregate_stress_results`) + add field to `StressMonteCarloResult`
4. Add `CompareCard` in `StressResults.tsx` extra row and/or MC percentile table row

**SSE streaming architecture:**
- `POST /api/stress/stream` in `main.py` is the live endpoint
- Each `apply_stress` + `_single_backtest` call runs via `asyncio.to_thread`
- After all runs, calls `aggregate_stress_results()` from `stress_testing/backend/stress.py`
- Frontend: `streamStressTest()` in `api.ts` uses `fetch` + `ReadableStream` reader
- `StressPage.tsx` accumulates `liveRuns[]` as `onRun` fires → `MCPathsCanvas` draws incrementally

**Backend restart reminder:**
`reload=False` always. Kill port 8000 then `python main.py` after any `.py` change.
