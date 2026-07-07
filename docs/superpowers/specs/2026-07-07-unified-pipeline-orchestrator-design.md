# Unified End-to-End Pipeline Orchestrator — Design

**Date:** 2026-07-07
**Status:** Approved for implementation planning

## Problem

TradeVed Backtester has, as of this design, several independently-working pieces: reel/transcript strategy extraction (`reel_extractor.py`), IR validation (`ir_validator.py`), classic/indicator/custom backtesting, walk-forward + holdout validation (`engine/validation.py`), stress testing (`engine/stress.py`), an LLM critique/improve/judge loop (`improvement_agent.py`), and paper/forward trading (`/api/forecast/paper/stream`). None of them are wired together. The goal is a single pipeline: user pastes a reel/transcript (or types a strategy directly) → the platform extracts a strategy, validates it with the user, iteratively optimizes it against in-sample data only, checks it once against a held-out window, kicks off paper trading in the background, and hands back a short, honest report with drill-down chips for the heavy stuff.

This spec covers the **orchestrator** — the piece that sequences all of the above, persists progress, enforces the "holdout touched exactly once" rule, and survives a backend restart mid-run. It assumes the individual stage logic (extraction, validation, backtest, stress, critique/improve, paper trading) already exists and only needs to be called, not rebuilt.

## Non-goals

- Not building a distributed job queue (Celery/Redis/etc.) — this is a single-process FastAPI app; asyncio tasks are sufficient at current scale.
- Not changing the individual stage logic itself (extraction prompts, validation rules, metric formulas) — only how they're sequenced and persisted.
- Not solving multi-instance/horizontal-scaling coordination — out of scope until the app actually runs more than one backend instance.

## Data Model

New SQLAlchemy table, `PipelineRun` (in `models.py`, auto-created via existing `create_all`, no migration):

| Column | Type | Notes |
|---|---|---|
| `id` | str (uuid) PK | |
| `user_id` | str | keyed off existing analytics identity (localStorage name/email), not a real auth system |
| `status` | str | `running \| awaiting_checkpoint \| looping \| holdout \| paper_trading \| complete \| failed \| interrupted` |
| `stage` | str | fine-grained stage name for UI/logging (`extracting`, `validating_ir`, `checkpoint`, `patching_ir`, `loop_round_N`, `holdout`, `paper_trading`, `done`) |
| `ir_json` | text | current strategy IR (extracted, then possibly patched/improved) |
| `symbol`, `timeframe`, `source_url`, `source_platform`, `source_creator` | str, nullable | source metadata; also feeds the creator-recommendation query |
| `cache_key` | str, indexed | normalized-IR + symbol + timeframe dedup key |
| `loop_round` | int | current round number in the optimization loop |
| `composite_scores_json` | text | list of `{round, score, metrics}` — one per loop iteration |
| `checkpoint_opened_at` | datetime, nullable | set when entering `awaiting_checkpoint`; cleared on user response or timeout-driven resume |
| `holdout_result_json` | text, nullable | null until holdout stage runs; presence of this value is what enforces "touched once" |
| `report_json` | text, nullable | final concise report payload (verdict + chip data) |
| `paper_trading_task_id` | str, nullable | handle for the background paper-trading task tied to this run |
| `created_at`, `updated_at` | datetime | |

This reuses the existing `StrategyOutcome` table's role for the cache/dedup and creator-analytics purposes (as already agreed in the flowchart) — `PipelineRun` is the *execution* record; `StrategyOutcome` remains the *outcome log* that the cache lookup queries.

## Execution Model

Each run is driven by `async def run_pipeline(run_id: str)`, launched via `asyncio.create_task`. The function is a straight-line sequence of stage functions, each of which:

1. Reads the current `PipelineRun` row.
2. Does its work (may be a no-op if the row shows this stage already completed — this is what makes resume idempotent).
3. Writes results + advances `stage`/`status`.
4. Calls the next stage function, or returns if the next stage requires waiting on something external (user checkpoint response, paper-trading real time).

**Restart recovery:** on app startup, a sweep query finds rows with non-terminal `status` and no corresponding live asyncio task, and marks them `interrupted`. The frontend shows "this run was interrupted — resume?"; clicking it just calls `run_pipeline(run_id)` again, which picks up from whatever the row already has populated.

**One active run per user:** enforced at `POST /api/pipeline/start` — reject with a clear error if the user already has a row with `status in (running, awaiting_checkpoint, looping, holdout)`. Rows in `paper_trading` or `complete` don't block a new run — paper trading is explicitly decoupled from "the user is blocked."

## Stage Flow

1. **Cache lookup** — compute `cache_key` from input; query `StrategyOutcome` for a match. Hit → skip straight to a `complete` row with the cached report. Miss → continue.
2. **Extract** — `reel_extractor.py` triage + `extract_strategy_ir()`. If the user supplied a tweak alongside the original input, this is passed through as an extra instruction to the extraction prompt (not a separate patch step — the tweak is available before an IR even exists yet).
3. **Validate IR** — `ir_validator.py`. Invalid → repair loop (existing behavior) before continuing.
4. **Checkpoint** (`awaiting_checkpoint`, sets `checkpoint_opened_at`) — returns without advancing. Resumed by one of:
   - User confirms → continue to loop.
   - User submits a tweak → **Patch IR** stage (reuses `improvement_agent.critique_and_improve()`'s mechanic, LLM edits the existing IR against the user's text only, no re-extraction) → back through Validate IR → loop.
   - 60–100s elapse with no response (checked via periodic sweep, same mechanism as restart recovery) → auto-proceed with the IR as-is → loop.
5. **Loop** (`looping`, `loop_round` increments each pass) — backtest (IS) → walk-forward → stress test → composite score (existing Sharpe 35/Return 25/Sortino 20/Calmar 10/MDD 10 formula) → append to `composite_scores_json`. Stop condition: `loop_round >= 5` OR score improvement `< 2%` vs previous round. If not stopping, call `critique_and_improve()` to produce the next IR, then repeat. If stopping, continue to holdout.
6. **Holdout** (`holdout`) — runs only if `holdout_result_json is null`. Calls `run_holdout()` once. Result (pass or honest fail) is written and stage always advances to report — no auto-retry on failure, per the agreed design.
7. **Paper trading** (`paper_trading`) — kicked off as a separate background task the moment the loop exits (does not wait for holdout, per earlier agreement that it needs real wall-clock time regardless). Its task id is stored; it updates the same row's paper-trading portion of `report_json` as data accumulates, independent of the row's own `status` reaching `complete`.
8. **Report** — `report_json` is written as soon as holdout resolves: a short verdict line plus chip metadata (`instant` chips point at already-computed `composite_scores_json`/holdout data; the `paper_trading` chip is `live` until its background task has enough data, `instant` after). Row `status` becomes `complete`. `judge_pipeline()` runs here too, as the independent audit already built for the improve flow.
9. **Retry-symbol re-entry** — `POST /api/pipeline/{run_id}/retry-symbol` creates a **new** `PipelineRun` row, copies `ir_json` from the finished run, sets the new symbol, and starts at the Loop stage (skipping extract/validate/checkpoint since the IR is already confirmed). Gets its own fresh holdout and its own paper-trading task.

## API Surface

- `POST /api/pipeline/start` — body: input (reel URL/transcript/text) + optional tweak text → `{run_id}`
- `GET /api/pipeline/{run_id}/stream` — SSE, one event per stage transition (mirrors the existing `/api/stress/stream` pattern: `asyncio.to_thread` for blocking calls, flush events between stages)
- `POST /api/pipeline/{run_id}/checkpoint` — body: `{action: "confirm"} | {action: "tweak", text: "..."}`
- `GET /api/pipeline/{run_id}` — current row state, for polling/resume
- `POST /api/pipeline/{run_id}/retry-symbol` — body: `{symbol: "..."}`

## Error Handling

- Any stage function raising an exception sets `status = failed` with the error captured in `stage`/a new `error_message` column, and does not retry automatically — surfaced to the user as a real failure, not silently swallowed (matches the existing "logging failure never fails the run" pattern used for `StrategyOutcome`, but this is the run *itself* failing, which must be visible).
- Checkpoint timer sweep and restart-recovery sweep are the same mechanism: a lightweight `asyncio` task started at app boot, polling every ~10s for rows needing action (`checkpoint_opened_at` older than 100s, or non-terminal rows with no live task after a fresh boot).
- Paper-trading task failures update only the paper-trading portion of `report_json` (chip shows an error state) and never flip the parent row's `status` away from `complete`.

## Known Risks / Open Items

- Checkpoint sweep cadence (~10s) and the loop's round cap (5) / plateau threshold (2%) are initial guesses, not measured — expect tuning after first live runs.
- `user_id` is keyed off the existing localStorage identity gate, not real auth — sufficient for the current internal-tester deployment, not for a public multi-tenant launch.
- Single-process asyncio task model does not survive horizontal scaling (multiple backend instances) — acceptable at current scale (single Railway service), flagged as a non-goal above.
