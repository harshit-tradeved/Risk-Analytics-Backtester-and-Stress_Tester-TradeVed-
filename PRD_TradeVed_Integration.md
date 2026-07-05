# TradeVed Platform — Integration PRD
**Prepared for:** Leadership / Cross-team Coordination  
**Date:** 2026-06-27  
**Status:** Draft v1.0  
**Audience:** Design, Frontend, Backend

---

## 1. Executive Summary

TradeVed has built **seven independent capability modules** across ~6 weeks of development. Each module works in isolation. The immediate opportunity is to wire them together into a coherent **three-stage user journey** — from raw social content (reel) → validated backtest → AI-powered forward projection — with a single through-line UX that guides both novice and advanced traders.

This PRD maps what exists, what connects to what, and what design + engineering work each team needs to do to make the integrations real.

---

## 2. Current State — Module Inventory

### 2.1 Backend Modules (all live at `https://backend-production-fdd47.up.railway.app`)

| Module | Key Files | Status | Endpoints |
|--------|-----------|--------|-----------|
| **Core Backtest Engine** | `engine/simulator.py`, `strategies/` (21 files) | ✅ Production | `POST /api/backtest/run` |
| **Indicator Engine** | `engine/indicators.py` | ✅ Production | `GET /api/indicators` |
| **Strategy Registry** | `strategies/__init__.py` | ✅ Production | `GET /api/strategies` |
| **Stress Tester** | `engine/stress.py` | ✅ Production | `POST /api/stress/run`, `/stream`, `/scenarios` |
| **Regime Detection** | `engine/regimes.py` | ✅ Production | (inline, not standalone endpoint) |
| **AI Forward Test (Kronos)** | `engine/forecast.py` | ✅ Production | `POST /api/forecast/stream`, `/crisis/stream` |
| **Walk-Forward Validation** | `engine/validation.py` | ✅ Production | `POST /api/validation/run` |
| **Reel → IR Extractor** | `reel_extractor.py`, `ir_validator.py` | ⚠️ Partial (URL blocked) | `POST /api/reel/analyze` |
| **Ingestion Pipeline** | `ingestion.py` | ⚠️ URL path blocked (cookies), transcript path works | (called internally by `/api/reel/analyze`) |
| **Strategy Outcome Logger** | `models.StrategyOutcome` | ✅ Logs every run | `GET /api/strategy-outcomes/summary` |
| **Analytics + Feedback** | `models.AnalyticsEvent`, `Feedback` | ✅ Production | `POST /api/track`, `/api/feedback`, `/api/admin/*` |
| **Indian Cost Model** | `engine/cost_models.py` | ✅ Production | (inline in simulator) |

### 2.2 Frontend Pages (live at `https://tradeved-backtester.vercel.app`)

| Page / Component | File | Status | Notes |
|------------------|------|--------|-------|
| **Backtest** | `App.tsx` + `Sidebar.tsx` | ✅ Production | Full GRID/DCA/PLA + 20+ indicator presets + Rule Builder |
| **Stress Test** | `StressPage.tsx` | ✅ Production | SSE streaming, live canvas MC paths |
| **Forward Test** | `ForwardTestPage.tsx` | ✅ Production | 3 sub-modes: Forward / Crisis / Paper Trade |
| **Reel Backtest** | `ReelPage.tsx` | ⚠️ Transcript path only | URL path shows blocker note |
| **Admin Dashboard** | `AdminDashboard.tsx` | ✅ Owner-only | KPI cards, event log, feedback cards |
| **Rule Builder** | `RuleBuilder.tsx` | ✅ Production | Drag-and-drop condition builder for CUSTOM strategy |
| **Schema-driven Params** | `StrategyParamsForm.tsx` | ✅ Production | Auto-renders for all indicator preset strategies |
| **Plain Language Verdict** | `PlainLanguageVerdict.tsx` | ✅ Component | Used in Reel page; not surfaced in Backtest/Stress pages yet |
| **IR Editor** | `StrategyIREditor.tsx` | ✅ Component | Human-readable rule display + gap flags |
| **MC Canvas** | `MCPathsCanvas.tsx` | ✅ Component | Shared by Stress + Forward Test |

### 2.3 Infrastructure

| Item | Detail |
|------|--------|
| **Frontend** | Vercel — `harshit-tradeved1/tradeved-backtester` |
| **Backend** | Railway — `tradeved-backtester` project, `/data` volume mounted |
| **DB** | SQLite at `/data/backtester.db` (Railway volume, persists deploys) |
| **LLM** | Azure OpenAI (GPT-5.3-Codex) — reel extraction + vision analysis |
| **Transcription** | Groq Whisper (`whisper-large-v3-turbo`) |
| **Fallback scraping** | Apify (`apify~instagram-reel-scraper`) |
| **AI Paths (GPU)** | Kronos via Modal (env: `KRONOS_URL`) |

---

## 3. Integration Map — What Connects to What

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CURRENT STATE (SILOED)                          │
│                                                                         │
│  [Reel Page]   [Backtest Page]   [Stress Page]   [Forward Test Page]   │
│       │               │                │                   │            │
│      (✗ no link)    (✗ no link)    (✗ no link)         (✗ no link)     │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                         TARGET STATE (INTEGRATED)                       │
│                                                                         │
│  [Reel URL / Transcript]                                                │
│         │                                                               │
│         ▼                                                               │
│  [LLM Extraction → IR]  ←── user edits gaps ──► [StrategyIREditor]    │
│         │                                                               │
│         ▼                                                               │
│  [Backtest] ────────────────► [Stress Test] ───────────────────────►  │
│         │                            │             [Forward Test]       │
│         ▼                            ▼                   ▼              │
│  [PlainVerdict]            [Scenario Report]    [Paper Trade mode]      │
│         │                            │                   │              │
│         └──────────────┬─────────────┘                   │              │
│                        ▼                                 │              │
│               [Share / Export card]                      │              │
│                        │                                 │              │
│                        ▼                                 ▼              │
│              [Strategy Outcome DB] ◄───────── [Outcome Logger]         │
│                        │                                                │
│                        ▼                                                │
│             [Adaptability Agent RAG]  ──► recommendations               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Concrete Integration Points

#### A. Reel → Backtest → Continue Journey
**What works today:** Reel page (transcript path) extracts IR → user confirms → `/api/strategy/from-ir` → backtest result.  
**Gap:** After the backtest result, the user hits a dead end. There's no "Now stress test this" or "Now forward test this" CTA.  
**Work needed:**
- Frontend: Add "Continue →" action buttons on the Reel results view (stress test / forward test)
- Backend: `/api/strategy/from-ir` already returns same shape as `/api/backtest/run` — no backend change needed
- Design: Post-result CTA card design with 3 continuation options

#### B. Backtest → Stress Test → Forward Test (shared strategy context)
**What works today:** All three pages are independent. User must re-enter strategy + symbol on each page.  
**Gap:** No shared strategy state between pages; user repeats themselves 3 times.  
**Work needed:**
- Frontend: Global `strategyContext` state in `App.tsx`; "Use this strategy →" button on each results page pre-fills next page's form
- Backend: Zero changes (endpoints already accept same strategy shape)
- Design: "You're testing [NIFTY50 / PLA / EMA 9-21]" context pill that persists across pages

#### C. Plain Language Verdict — Surface Everywhere
**What works today:** `PlainLanguageVerdict.tsx` component exists but is only shown in the Reel page flow.  
**Gap:** Standard Backtest and Stress Test pages show raw numbers only — no novice-friendly summary.  
**Work needed:**
- Frontend: Add `PlainLanguageVerdict` below `MetricsGrid` in the backtest results view; add condensed version to `StressResults.tsx`
- Backend: Zero changes (verdict is computed client-side from response metrics)
- Design: Two variants — full card (Reel/Backtest) and compact chip (Stress)

#### D. Strategy Outcome Logger → Adaptability Agent RAG
**What works today:** Every backtest appends a row to `StrategyOutcome` table. `GET /api/strategy-outcomes/summary` returns aggregate stats.  
**Gap:** The outcome data is sitting unused. The Adaptability Agent (`adaptability_agent.py`) has a RAG retriever but it reads static docs, not live outcome DB.  
**Work needed:**
- Backend: Add `get_top_strategies(symbol, source, regime)` query on `StrategyOutcome`; expose as `GET /api/strategy-outcomes/recommend?symbol=&source=&regime=`
- Backend: Wire Adaptability Agent to call this endpoint as a retrieval tool
- Frontend: Add "Recommended for [NIFTY50] based on past runs" panel in Sidebar (optional Phase 2)

#### E. Regime Detection → Forward Test / Stress Scenario Auto-Select
**What works today:** Regime detection runs after every backtest (`classify_regimes`); regime mix is in the response. Forward Test live view shows regime counts. Stress has 17 scenario presets.  
**Gap:** No connection between detected regime and stress scenario selection.  
**Work needed:**
- Frontend: After backtest, if regime is mostly Bear → suggest `slow_bleed` / `gfc_2008` scenarios. Add "Suggested scenarios based on regime" section in StressSidebar
- Backend: `GET /api/stress/scenarios/suggest?regime=bear` — filter `SCENARIO_PRESETS` by risk type (1-hour task)

#### F. Paper Trade Mode → Outcome Feedback Loop
**What works today:** `PaperTradeView.tsx` exists as a sub-mode of Forward Test (simulated live trading on forward-projected paths).  
**Gap:** Paper trade outcomes are not logged to `StrategyOutcome` — the feedback loop is broken.  
**Work needed:**
- Backend: `POST /api/paper-trade/log` endpoint that accepts paper trade outcomes and appends to `StrategyOutcome` with `source_type: "paper"`
- Frontend: On paper trade completion, call this endpoint

---

## 4. Current Blockers

### Blocker 1 — Instagram URL Ingestion (P0)
**Problem:** `yt-dlp` fails on Instagram reels without authenticated session cookies. The `INGESTION_API_URL` env var is set but points to a service that currently encounters the same auth issue. Apify fallback works but is slow (~30s) and costs API credits per run.  
**Impact:** The primary UX ("paste a URL") doesn't work. Users must manually type out the transcript — high friction, drops conversion.  
**Fix:**
- Short-term: Implement stable yt-dlp cookie injection (export `cookies.txt` from browser, mount on Railway volume at `/data/instagram_cookies.txt`, pass `--cookies` flag to yt-dlp)  
- Medium-term: Make Apify the **primary** path (not fallback) since it handles auth; demote yt-dlp to secondary  
- Work needed: Backend 2h. DevOps: add cookie file to Railway volume mount.

### Blocker 2 — LLM Calls Block FastAPI Thread (P1)
**Problem:** Triage + extraction calls (2–3 LLM calls, 3–8s each) run synchronously inside the FastAPI request. Under concurrent load, this blocks the entire event loop, delaying all other users' requests.  
**Impact:** Not visible with one user; becomes a hard blocker at 3+ concurrent users.  
**Fix:**
- Add Redis + RQ task queue. `POST /api/reel/analyze` returns immediately with a `task_id`. Frontend polls `GET /api/reel/task/{task_id}` (or use SSE). Same pattern as the existing Stress streaming endpoint.  
- Work needed: Backend 1 day. Frontend: 2h polling/SSE change.

### Blocker 3 — CustomStrategy IR Edge Cases (P2)
**Problem:** `cross_above` / `cross_below` operators between two indicator series (e.g., EMA(9) cross_above EMA(21)) can produce NaN-misaligned boolean Series if both sides compute indicators with different warm-up lengths, causing the signal mask to silently produce 0 trades.  
**Impact:** Strategies extracted from reels that use MA crossovers (the most common pattern) may silently return 0 trades with no error message to the user.  
**Fix:** Normalize index alignment in `CustomStrategy._evaluate_side()` and add a unit test covering EMA-vs-EMA cross_above. Backend 3h + test.

---

## 5. Feature Specifications by Team

### 5.1 Design Team

| Feature | Priority | Description |
|---------|----------|-------------|
| **Journey flow screens** | P0 | Design the "Reel → Backtest → Stress → Forward" funnel as a connected flow. Show a progress strip (4 stages) at the top when user is in a guided journey vs. free exploration mode |
| **Context persistence pill** | P0 | When strategy context carries across pages (e.g., "NIFTY50 / PLA / EMA 9-21"), show a persistent chip in the top nav. Clicking it shows the full params. |
| **Post-result CTA card** | P0 | After any backtest result, show a card with 3 next-step actions: (1) Stress Test this, (2) Forward Test this, (3) Share result. Dark-mode, consistent with current palette. |
| **PlainLanguageVerdict — variants** | P1 | Full card variant (Reel + Backtest) and compact inline chip variant (below the scenario verdict in Stress). Current Reel design is reference. |
| **Regime-aware scenario suggest** | P1 | In StressSidebar, a "Recommended scenarios" section that highlights 2–3 scenarios based on regime detected in backtest. Needs highlighted card UI within existing sidebar. |
| **Shareable result card** | P1 | Single-image summary card (equity curve thumbnail + 4 key metrics + verdict badge + strategy name) that users can download and share. This is the social growth flywheel. |
| **Reel page — URL path UX** | P2 | Once Blocker 1 is fixed, the URL tab needs a loading state (yt-dlp download → transcription → extraction → validation — each phase should show progress). |
| **Adaptability Agent UI** | P2 | Entry point for the AI assistant. A chat/query input that accepts natural language ("what's the best strategy for NIFTY in a bear market?") and returns recommendations from the outcome DB. Could be a floating panel or a dedicated page. |

### 5.2 Frontend Team

| Feature | Priority | Files Affected | Description |
|---------|----------|----------------|-------------|
| **Shared strategy context** | P0 | `App.tsx`, `Sidebar.tsx`, `StressSidebar.tsx`, `ForwardTestSidebar.tsx` | Add `strategyContext` state to `App.tsx`. Add "Use last strategy" button on Backtest/Stress/Forward sidebars. Pre-fill form from context. |
| **Post-result CTA buttons** | P0 | `App.tsx`, `MetricsGrid.tsx`, `StressResults.tsx` | "Stress Test This" button on backtest results page → switch to stress page with pre-filled form. "Forward Test This" similarly. |
| **PlainLanguageVerdict in Backtest** | P1 | `App.tsx` (results section) | Import `PlainLanguageVerdict` component. Already written — just needs a mount point below `MetricsGrid`. |
| **PlainLanguageVerdict compact in Stress** | P1 | `StressResults.tsx` | Compact verdict chip (green/yellow/red + 1-line summary) under the scenario comparison cards. |
| **Reel task polling** | P1 | `ReelPage.tsx`, `api.ts` | When Blocker 2 is fixed: change `/api/reel/analyze` call to receive `task_id` + poll `GET /api/reel/task/{task_id}`. SSE preferred over polling. |
| **Regime → scenario suggestion** | P1 | `StressSidebar.tsx` | After a backtest (if regime is in strategy context), call `GET /api/stress/scenarios/suggest?regime=X`, highlight those scenarios in the checkbox list. |
| **Share result card** | P1 | New `ShareCard.tsx` | Canvas or html2canvas render of: equity curve thumbnail + 4 metrics + verdict + "Tested on TradeVed" watermark. Download as PNG. |
| **Paper trade outcome log** | P2 | `PaperTradeView.tsx`, `api.ts` | On paper trade end, call `POST /api/paper-trade/log` with strategy + outcomes. |
| **Strategy recommendations panel** | P2 | `Sidebar.tsx` (or new `RecommendPanel.tsx`) | Call `GET /api/strategy-outcomes/recommend?symbol=&regime=` and show top 3 strategies with return + Sharpe. |

### 5.3 Backend Team

| Feature | Priority | Files Affected | Description |
|---------|----------|----------------|-------------|
| **Fix Blocker 1 (Instagram cookies)** | P0 | `ingestion.py` | Mount cookie file on Railway; pass `--cookies /data/instagram_cookies.txt` to yt-dlp subprocess. Add env var `INSTAGRAM_COOKIES_PATH`. |
| **Fix Blocker 3 (Custom IR edge cases)** | P0 | `strategies/custom.py` | In `_evaluate_side()`, call `.dropna()` + `.reindex(df.index)` after computing both left and right indicator series before building the boolean mask. Add test to `test_all.py`. |
| **Async task queue** | P1 | `main.py`, new `tasks.py` | Wrap `POST /api/reel/analyze` in RQ task. Return `{task_id}`. Add `GET /api/reel/task/{task_id}`. Use Redis Cloud (free tier) or Railway Redis addon. |
| **`GET /api/stress/scenarios/suggest`** | P1 | `main.py`, `engine/stress.py` | Accept `?regime=bull\|bear\|sideways`. Return 3 scenario keys most relevant to that regime (bear → `slow_bleed`, `luna_collapse`, `gfc_2008`; bull → `pump_dump`, `vol_spike`; etc.). 1h task. |
| **`GET /api/strategy-outcomes/recommend`** | P1 | `main.py`, `database.py` | Query `StrategyOutcome` table by `symbol` + `source` + (optional) `regime_mix` filter. Return top 5 by composite score (Sharpe 35% + Return 25% + Sortino 20%). |
| **Paper trade outcome logging** | P2 | `main.py`, `models.py` | `POST /api/paper-trade/log` — accepts paper trade results, writes to `StrategyOutcome` with `source_type="paper"`. |
| **Adaptability Agent endpoint** | P2 | `adaptability_agent.py`, `main.py` | Expose `POST /api/agent/query` that calls the RAG agent with the question + injects top outcomes from `StrategyOutcome` as retrieval context. |
| **`/api/reel/analyze` SSE mode** | P2 | `main.py`, `reel_extractor.py` | Stream events for each pipeline stage: `downloading → transcribing → triaging → extracting → validating`. Mirrors the existing Stress streaming pattern. Each stage is an SSE event so the frontend can show granular progress. |

---

## 6. Priority Matrix

```
                HIGH IMPACT
                    │
         ┌──────────┴──────────────┐
   LOW   │  [Regime→Scenario]      │  [Reel URL Fix]
  EFFORT │  [PlainVerdict Backtest] │  [Shared Strategy Context]
         │  [CTA buttons]          │  [Post-result CTA card]
         │                         │  [Custom IR fix]
         ├──────────┬──────────────┤
         │  [Share card]           │  [Async task queue]
   HIGH  │  [Paper trade log]      │  [Strategy Recommendations]
  EFFORT │                         │  [Adaptability Agent UI]
         └──────────┴──────────────┘
                LOW IMPACT
```

### Phase 1 — "Connect the dots" (Target: 1 week)
1. Fix Blocker 1 (Instagram cookies) — Backend
2. Fix Blocker 3 (Custom IR edge cases) — Backend
3. Shared strategy context + "Use this →" buttons — Frontend
4. PlainLanguageVerdict in Backtest results — Frontend
5. Post-result CTA card design + implementation — Design + Frontend

### Phase 2 — "Intelligence layer" (Target: 2 weeks)
1. Async task queue for Reel endpoint — Backend
2. Strategy Outcome Recommendations endpoint + sidebar panel — Backend + Frontend
3. Regime → scenario suggestions — Backend + Frontend
4. Shareable result card — Frontend + Design

### Phase 3 — "Growth & retention" (Target: 3–4 weeks)
1. Adaptability Agent endpoint + UI — Backend + Design + Frontend
2. Reel SSE streaming (per-stage progress) — Backend + Frontend
3. Paper trade outcome logging + feedback loop — Backend + Frontend

---

## 7. Open Questions for Each Team

### For Design
- What does the "4-stage journey strip" look like when a user enters at Backtest directly (not via Reel)? Do we show incomplete stages?
- Is the shareable result card Instagram-story aspect ratio (9:16) or landscape (1.91:1)?
- Is the Adaptability Agent a chat panel, a dedicated page, or a right-drawer?

### For Frontend
- Should `strategyContext` persist in `localStorage` so page refresh doesn't lose it?
- For the "Share card" — html2canvas or a server-side render? (html2canvas has font/icon issues; server render is more reliable but slower)
- Who owns the `isIndianSource` helper in `api.ts` — should this move to a shared util?

### For Backend
- Redis: Railway addon (paid) or Redis Cloud free tier (external)? Affects setup time vs. cost.
- Should `/api/strategy-outcomes/recommend` filter by `regime_mix` as a string match (e.g., >50% bull) or use a separate `dominant_regime` column? Column is cleaner but requires a migration.
- Adaptability Agent reads from `adaptability_agent.py` at project root — does this move into `backtester/` for Railway deploy, or stay as a separate service?

---

## 8. Data Flow Reference

### End-to-end Reel → Forward Test (target state)

```
User pastes Instagram URL
       │
       ▼
POST /api/reel/analyze
  ├─ yt-dlp download (with cookies)
  ├─ ffmpeg audio extract
  ├─ Groq Whisper transcription
  ├─ Azure Vision (on-screen text)
  ├─ LLM triage (200 tokens)
  ├─ LLM clean+isolate (800 tokens)
  └─ LLM normalize to IR (1200 tokens)
       │
       ▼
{strategy_ir, gaps, confidence, suggested_symbol/source/interval}
       │
       ▼
User reviews StrategyIREditor (fills gaps, confirms)
       │
       ▼
POST /api/strategy/from-ir  →  BacktestResponse
       │                           │
       │                           ├─ MetricsGrid
       │                           ├─ PlainLanguageVerdict  ← NEW
       │                           ├─ ChartsPanel
       │                           └─ "Continue →" CTA  ← NEW
       │
   [Save to strategyContext]  ← NEW
       │
       ├──────────────► POST /api/stress/stream  (pre-filled)
       │
       └──────────────► POST /api/forecast/stream  (pre-filled)
                              │
                              └─ PaperTradeView
```

---

## 9. Appendix — Deployed URLs

| Resource | URL |
|----------|-----|
| Frontend | https://tradeved-backtester.vercel.app |
| Backend API | https://backend-production-fdd47.up.railway.app |
| API Docs | https://backend-production-fdd47.up.railway.app/docs |
| Admin Dashboard | `?admin=<ADMIN_TOKEN>` appended to frontend URL |
| Strategy Outcomes | `GET /api/strategy-outcomes/summary` |
| Strategy Registry | `GET /api/strategies` |
| Indicator Catalog | `GET /api/indicators` |
| Stress Scenarios | `GET /api/stress/scenarios` |
