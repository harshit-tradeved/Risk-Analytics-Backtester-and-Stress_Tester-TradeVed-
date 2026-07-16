# TradeVed — Combined Product & Engineering Roadmap

> Merges two strands of work into one sequenced plan:
> 1. **Strategy Breadth** — turn the "70+ indicators" promise into real code: an indicator engine, schema-driven forms, a preset strategy library, and a user-facing rule builder. (from the indicator-extension plan)
> 2. **AI Depth** — the Kronos generative-forecasting moat: probabilistic forward-testing, crisis simulation, and strategy-intelligence on our own outcome data. (from `Kronos.md`)
>
> The two tracks are not independent — they **compound**. Breadth produces a large, diverse universe of strategies; Depth needs exactly that universe (plus a log of how each strategy performs across regimes) to train the strategy-intelligence ranker that is our hardest-to-copy moat. The connective tissue between them is **strategy-outcome logging**, which we start in week 1 because it is free and compounds.

---

## The two tracks at a glance

```
TRACK 1 — STRATEGY BREADTH (cheap, additive, no infra)
  A. Indicator Engine          ← real indicators, the foundation
  B. Schema-Driven Forms       ← new strategies become backend-only
  C. Preset Strategy Library   ← RSI/MACD/Bollinger/Supertrend/Donchian/MA-cross
  D. Generic Rule Builder      ← "strategies we can create"

TRACK 2 — AI DEPTH (Kronos moat, infra-heavy)
  0. Outcome Logging           ← FREE, start now, the real moat seed
  1. Async queue + Postgres    ← prerequisite for any GPU work
  2. AI Forward-Test (Kronos)  ← flagship; reuses the stress pipeline
  3. Crisis Simulator          ← Kronos + stress scaffold hybrid
  4. Strategy-Intelligence     ← GBM ranker on the outcome log (Track 1 feeds it)
  5. AI Paper Trading          ← trade inside generated futures
```

**Why this order:** Track 1 is pure-Python, deploys on the current Railway/Vercel stack, and ships value every week. Track 2 forces real infra decisions (async jobs, Postgres, serverless GPU) and should not start before the outcome log exists. Crucially, **Track 2's most defensible feature (strategy-intelligence) is starved without Track 1's breadth** — a ranker over 3 strategies is uninteresting; a ranker over dozens of indicator strategies + user-built custom rules is a genuine moat.

---

## Honest scope verdict (carried from Kronos.md)

- **Kronos is worth integrating for exactly one capability: probabilistic forward-path generation.** It powers forward-testing, crisis sim, and AI paper trading. It is the **wrong tool** for regime detection and strategy ranking — those are discriminative/tabular problems on *our* data, best served by gradient boosting + the existing heuristic.
- **The moat is the data, not the model.** Kronos is open-source; anyone can run it. Our `{strategy, params, regime → outcome}` dataset is not copyable. Track 1 is what makes that dataset rich.
- **No fine-tuning yet, never a home-grown foundation model.** Zero-shot Kronos-small, gated behind an eval harness.

---

## Deviation from the approved indicator plan (decision log)

The approved plan specified **pandas-ta**. On inspection, `requirements.txt` pins **numpy 2.4.6** and **pandas 3.0.3**. `pandas-ta 0.3.14b0` (a) does `from numpy import NaN` — removed in numpy ≥2.0 — and (b) relies on pandas APIs deleted in pandas 3.0 (`DataFrame.append`, positional `.iloc` quirks). It would break on import and jeopardise the clean Railway build.

**Decision:** implement the indicator engine in **pure pandas/numpy** (no external TA dependency). Benefits: zero compatibility/deploy risk, full control over stable output-column naming (`rsi`, `macd_signal`, `bb_lower`, …), and no version pin to babysit. Cost: we hand-write each indicator, but they are textbook formulas and we gain a tested, self-contained module. The `INDICATOR_CATALOG` metadata contract (for the rule-builder UI) is unchanged from the plan.

---

## Track 1 — Strategy Breadth

### Phase A — Indicator Engine Foundation
`backtester/backtesting/engine/indicators.py` (pure pandas/numpy):
- `INDICATOR_CATALOG` — registry of indicators with UI/rule-builder metadata: `{key, label, group (momentum/trend/volatility/volume/overlap), params:[{name,default,min,max}], outputs:[col names]}`.
- `compute(df, key, **params)` → named output column(s) with stable keys.
- Groups: overlap (SMA/EMA/WMA/VWAP/HMA…), momentum (RSI/MACD/Stoch/CCI/ROC/Williams %R…), trend (ADX/Aroon/Supertrend/PSAR…), volatility (ATR/Bollinger/Keltner/Donchian…), volume (OBV/MFI/CMF…).
- `GET /api/indicators` returns the catalog.
- Tests: reference values for RSI/MACD/Bollinger/ATR on a fixed series; catalog shape.

### Phase B — Schema-Driven Dynamic Forms (the scalability unlock)
- Backend: `Param(...)` helper + enrich `BaseStrategy.parameter_schema()` to return structured UI metadata (`type/label/min/max/step/options/group/depends_on`). Enrich `GET /api/strategies` with schema + `category` (`classic`/`indicator`/`custom`).
- Frontend: `StrategyParamsForm.tsx` renders any strategy's inputs generically; migrate `FormState` → `strategy: string` + `strategyParams: Record<string, unknown>`; collapse `buildStrategyParams`; delete hardcoded GRID/DCA/PLA blocks in `Sidebar.tsx`/`StressSidebar.tsx`; migrate `computeSmartDefaults`.
- After this phase, Phases C & D are **backend-only** for the form to pick them up.

### Phase C — Preset Indicator Strategy Library
`RSIStrategy`, `MACDStrategy`, `BollingerStrategy`, `SupertrendStrategy`, `DonchianBreakoutStrategy`, `MACrossStrategy` — each a `BaseStrategy` using the engine, declaring a schema, emitting the `signal`/`quantity`/`meta` contract, registered in `STRATEGY_REGISTRY`. Per-strategy signal tests.

### Phase D — Generic Rule Builder ("strategies we can create")
- `backtesting/strategies/custom.py: CustomStrategy` — `entry_rules`/`exit_rules` as condition lists (`left_indicator, operator (>/</cross_above/cross_below), right: value|indicator`), combined via AND/OR; evaluator computes indicators via the engine and emits BUY/SELL/HOLD. Category `custom`.
- `RuleBuilder.tsx` — fetches `/api/indicators`, lets users compose conditions, serialises into `strategyParams`. Rendered when strategy is `CUSTOM`.

---

## Track 2 — AI Depth (Kronos)

### Phase 0 — Strategy-Outcome Logging (START NOW — free)
`StrategyOutcome` table + write a row on every backtest: `{strategy, params, symbol, source, interval, regime mix, metrics}`. This is the seed of the moat and the training set for Phase 4. Track 1's breadth makes these rows diverse.

### Phase 1 — Async queue + Postgres
Redis + RQ job queue (move forecast/heavy backtests off the request thread); SQLite → Postgres via `DATABASE_URL` + Alembic. Prerequisite for GPU work and for scaling the current blocking endpoints.

### Phase 2 — AI Forward-Test (Kronos zero-shot) — FLAGSHIP
`forward_testing/forecast.py` `KronosClient` (HTTP, `KRONOS_URL`) + `kronos_service/` (Modal/FastAPI loading Kronos-small + tokenizer). `POST /api/forecast/run` + `/stream` mirror the stress endpoints, **reusing** `run_single_backtest` + `aggregate_stress_results` + the SSE contract + `MCPathsCanvas`. Frontend "Forward Test" page pill. GPU on Modal scale-to-zero (or CPU at MVP); cache paths by context-hash.

### Phase 3 — Crisis Simulator
Map `SCENARIO_PRESETS` (17) to a Kronos+scaffold hybrid: the stress scaffold imposes the macro shock shape, Kronos fills realistic micro-structure. "Show me a flash crash" → preset + generated variants.

### Phase 4 — Strategy-Intelligence v1 (the deepest moat)
Gradient-boosting ranker trained on the Phase-0 outcome log → "this strategy historically degrades in bear/high-vol." **No Kronos.** Gated on Phase 0 having accumulated data — which is why Phase 0 starts in week 1 and why Track 1 breadth matters (more strategy types → richer ranker). Also upgrade `classify_regimes` heuristic with an HMM/GBM.

### Phase 5 — AI Paper Trading + eval/fine-tune gate
Trade inside generated/crisis environments. Eval harness measuring Kronos forecast accuracy on held-out crypto + NSE/BSE → the gate for any LoRA fine-tune (NSE/BSE is the only case that might justify it).

---

## Unified sequencing (one line)

**indicator engine → outcome logging → dynamic forms → preset strategies → rule builder → async+Postgres → Kronos forward-test → crisis sim → strategy-intelligence → AI paper trading**

The first five are Track-1 (ship now, no infra). Outcome logging is slotted second because it is free and every subsequent strategy run feeds it. Kronos work begins only once the strategy universe is broad and the outcome log is filling.

## Infra & cost guardrails (from Kronos.md)

- Never run GPU on Railway. Keep FastAPI/Postgres/Redis on Railway; offload Kronos to **Modal** serverless GPU (scale-to-zero, per-second). CPU Kronos-small at MVP to defer GPU spend.
- Cache forecast paths by `(symbol, interval, context-hash, horizon, T, top_p)`.
- Frame forward-tests as *a distribution of plausible futures*, never "prediction"; show P5/P50/P95.

## Reuse (don't reinvent)

- Strategy contract & dispatch: `BaseStrategy`, `STRATEGY_REGISTRY`, `main.py` dispatch — new strategies plug in unchanged.
- Signal→trade execution: `backtesting/engine/simulator.py` (BUY/SELL/HOLD + `quantity`) — simulator, cost models, metrics, regimes, stress all work unchanged.
- The stress pipeline (`run_single_backtest`, `aggregate_stress_results`, SSE, `MCPathsCanvas`) is reused verbatim by Kronos forward-test — this is why Track 2's flagship is cheap.

---

## Current implementation status

- [x] Track 1 / Phase A — indicator engine (`backtesting/engine/indicators.py`, 25 indicators / 40 series) + `GET /api/indicators`
- [x] Track 2 / Phase 0 — outcome logging (`StrategyOutcome` table + `/api/strategy-outcomes/summary`)
- [x] Track 1 / Phase B — schema-driven forms (`parameter_schema` + `StrategyParamsForm.tsx`; hybrid: classic strategies keep flat fields)
- [x] Track 1 / Phase C — preset strategies (RSI, MACD, Bollinger, Supertrend, Donchian, MACross)
- [x] Track 1 / Phase D — rule builder (`backtesting/strategies/custom.py` + `RuleBuilder.tsx`)
- [x] Track 2 / Phase K1 — AI Forward-Test (`forward_testing/forecast.py` block-bootstrap + `POST /api/forecast/run|stream` + `ForwardTestPage` + `ForwardTestSidebar` + `ForwardTestResults`; Kronos GPU slots in via `KRONOS_URL` env var with zero code change)
- [ ] Track 2 / Phase K2 — Async queue + Postgres (Redis/RQ; prerequisite for GPU work and scaling)
- [x] Track 2 / Phase K3 — Crisis Simulator hybrid (`/api/forecast/crisis/stream`: Kronos block-bootstrap path + `apply_stress` scaffold overlay per run; frontend mode toggle in `ForwardTestPage`)
- [ ] Track 2 / Phase K4 — Strategy-Intelligence ranker (GBM on StrategyOutcome log)
- [x] Track 2 / Phase K5 — AI Paper Trading (`POST /api/forecast/paper/stream` SSE bar-by-bar; `PaperTradeView.tsx` with price/equity charts + trade log; "Paper Trade" tab in `ForwardTestPage`)
- [x] Track 1 expansion — 54 total strategies (3 classic + 44 new indicator/combo presets + CUSTOM rule builder); grouped in 9 thematic files: `oscillators.py`, `trend_indicators.py`, `ma_variants.py`, `volume_strats.py`, `breakout_strats.py`, `combos_rsi.py`, `combos_macd.py`, `combos_supertrend.py`, `combos_multi.py`

**Verification:** 43/43 unit tests pass (`python test_all.py`, +5 new for indicators/presets/custom/schema); frontend `npm run build` clean (tsc + vite). Live API end-to-end (backtest on BTC/USDT through an indicator/CUSTOM strategy) is blocked only by the datacenter Binance 451 in this environment — dispatch + outcome-logging paths are covered by unit tests and TestClient metadata checks.
