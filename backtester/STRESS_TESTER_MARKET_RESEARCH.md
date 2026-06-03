---
dest: ./STRESS_TESTER_MARKET_RESEARCH.pdf
stylesheet: https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1/github-markdown.min.css
body_class: markdown-body
css: |-
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
  .markdown-body { font-size: 13px; max-width: 960px; margin: 0 auto; padding: 30px; }
  .markdown-body pre > code { white-space: pre-wrap; font-size: 11px; }
  .markdown-body table { font-size: 12px; }
  .markdown-body h1 { border-bottom: 2px solid #4f46e5; padding-bottom: 8px; color: #1e1b4b; }
  .markdown-body h2 { color: #1e1b4b; border-bottom: 1px solid #e0e0e0; }
  .markdown-body h3 { color: #374151; }
  .markdown-body blockquote { background: #f0f4ff; border-left: 4px solid #4f46e5; padding: 10px 16px; border-radius: 4px; }
  .page-break { page-break-after: always; }
pdf_options:
  format: A4
  margin: 18mm 16mm
  printBackground: true
  displayHeaderFooter: true
  headerTemplate: |-
    <style>
      section { margin: 0 auto; font-family: -apple-system, sans-serif; font-size: 9px; color: #6b7280; width: 100%; padding: 0 16mm; box-sizing: border-box; }
      .left { float: left; } .right { float: right; }
    </style>
    <section><span class="left">TradeVed — Stress Tester Market Research &amp; Product Strategy</span><span class="right">Confidential · May 2026</span></section>
  footerTemplate: |-
    <style>
      section { margin: 0 auto; font-family: -apple-system, sans-serif; font-size: 9px; color: #6b7280; width: 100%; padding: 0 16mm; box-sizing: border-box; }
    </style>
    <section style="text-align:center">Page <span class="pageNumber"></span> of <span class="totalPages"></span></section>
---

# TradeVed Stress Tester — Market Research & Product Strategy

> **Purpose:** A build-ready product strategy document for evolving the TradeVed Stress Tester into a best-in-market strategy-robustness product.
> **Audience:** Product, quant research, and engineering.
> **Date:** May 2026
> **Method:** Competitive teardown of 20+ platforms, the academic overfitting literature, institutional risk practice, and a line-level read of TradeVed's current `engine/stress.py`.

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Competitor Comparison Table](#2-competitor-comparison-table)
3. [Feature Matrix](#3-feature-matrix)
4. [Most Loved Features Across the Market](#4-most-loved-features-across-the-market)
5. [Most Requested / Missing Features](#5-most-requested--missing-features)
6. [Institutional Practices](#6-institutional-practices)
7. [Where TradeVed Stands Today](#7-where-tradeved-stands-today-honest-self-assessment)
8. [Product Gaps](#8-product-gaps)
9. [Opportunities for TradeVed](#9-opportunities-for-tradeved)
10. [Recommended Features — Ranked by Priority](#10-recommended-features--ranked-by-priority)
11. [TradeVed Opportunity Roadmap](#11-tradeved-opportunity-roadmap)
12. [The Ultimate Stress Tester — Blueprint](#12-the-ultimate-stress-tester--blueprint)
13. [Scoring Frameworks (Spec)](#13-scoring-frameworks-implementation-spec)
14. [Sources](#14-sources)

---

## 1. Executive Summary

The stress-testing / strategy-robustness market splits into **three tiers**, and there is a **wide-open gap in the middle** that TradeVed is unusually well positioned to own.

| Tier | Who | What they do | Price | The catch |
|------|-----|--------------|-------|-----------|
| **Institutional** | BlackRock Aladdin, Bloomberg PORT, MSCI RiskMetrics, FactSet | Portfolio-level factor/macro/climate stress, correlation-breakdown modeling, historical replay with *your exposures* | $100K–$1M+/yr | No retail access, no algo-strategy testing, no self-serve |
| **Quant/Robustness** | Build Alpha, StrategyQuant X, AmiBroker, vectorbt | Deep robustness suites: Monte Carlo (5–9 variants), walk-forward, noise/synthetic data, parameter sensitivity, overfitting rejection | $99–$1,290 one-time or sub | Desktop-bound, steep learning curve, no Indian market, ugly tables not visuals, no streaming/live UX |
| **Retail/Charting** | TradingView, TrendSpider, NinjaTrader, AlgoTest, Streak | Easy backtests, great charts, broker integration | Free–$60/mo | Backtest *stops at the backtest* — little/no real stress testing, no overfitting science, no robustness score |

**The strategic insight:** Nobody combines (a) institutional-grade stress methodology, (b) the robustness/overfitting science quants trust, (c) a beautiful real-time retail UX, and (d) Indian + crypto + US market coverage. Each tier is missing two of the four.

**TradeVed already has rare assets** that the retail and even quant tiers lack:
- **Scenario-based *pre-strategy* OHLCV perturbation** (13 historical presets) — the strategy reacts to the shock *naturally*, which is methodologically closer to Build Alpha's "synthetic data stress" than to the cheap "shuffle the trade list" Monte Carlo most retail tools ship.
- **Live SSE-streamed Monte Carlo** with a **canvas spaghetti chart** (1,000+ paths) and a **delta-view toggle** — a genuinely novel, institutional-feeling UX that *no retail competitor has*.
- **Per-run magnitude jitter** (`severity × uniform(0.75, 1.25)`) so paths fan out in both timing and intensity.
- **Indian cost model** (STT/GST/SEBI/stamp, Budget 2024) + F&O lot sizes — a moat in the fastest-growing retail algo market on earth.

**Important nuance (verified in code):** TradeVed *already ships* a full **walk-forward + out-of-sample validation engine** (`engine/validation.py` → `run_holdout`, `run_walk_forward`), surfaced via `ValidationPanel.tsx`. But it lives in the **backtester** flow only — the **stress tester** does not call it. So the gap is *integration + scoring*, not building walk-forward from scratch.

**What the stress tester is still missing** is the *validation science* that turns a pretty stress chart into a **trustworthy verdict**: the existing walk-forward/OOS engine isn't wired in, and there's no overfitting probability (PBO), no Deflated Sharpe, no Monte Carlo permutation p-value, no parameter-sensitivity heatmap, no single robustness score, no tail-risk metrics (CVaR/probability of ruin), and only single-asset coverage (no portfolio correlation-breakdown).

**The recommendation in one line:** Keep the world-class scenario engine and streaming UX, and bolt on a **Validation & Confidence layer** — a single **Robustness Score (A+→F)** backed by walk-forward, an overfitting probability, tail-risk metrics, and a parameter-sensitivity heatmap — so TradeVed becomes the only product that *stress-tests a strategy AND tells you whether to trust the backtest at all*, in real time, for Indian/crypto/US markets, with a UI a retail trader actually enjoys.

---

## 2. Competitor Comparison Table

| Platform | Core offering | Target user | Pricing (2026) | Killer feature | Biggest weakness for stress/robustness |
|----------|--------------|-------------|----------------|----------------|------------------------------------------|
| **BlackRock Aladdin** | Institutional risk OS | Asset managers, banks | $100K–$1M+/yr | Historical replay using *current exposures* + correlation-breakdown; macro & climate scenarios | No retail, no algo-strategy backtesting, no self-serve |
| **Bloomberg PORT** | Terminal portfolio & risk | Buy-side PMs | ~$24K/yr (terminal) | 4 scenario engines: factor, full-valuation, macro, climate; build custom scenarios (even "Spanish flu") | Portfolio-level only; no strategy robustness; terminal lock-in |
| **MSCI RiskMetrics** | Factor risk & stress | Institutions | $$$ | "Broken-arrow" correlation-breakdown stress test; factor stress | Institutional only; not strategy-centric |
| **HiddenLevers (Orion)** | Advisory scenario analysis | RIAs/advisors | ~$300+/mo/advisor | **"Scenario priced-in" indicator** (key-lever tracking); macro-linked scenarios; client-ready reports | No algo testing; no per-trade MC; managed-portfolio framing |
| **Portfolio Visualizer** | Allocation backtest + MC | Retail/RIA | Free–$360/yr | Multiple MC models (historical bootstrap / parametric / custom dist), withdrawal survival | No strategy-execution testing; portfolio-level; no scenario shocks |
| **Build Alpha** | Strategy generation + robustness | Serious retail quants | ~$999–$1,990 | **The deepest retail robustness suite**: noise tests, MC permutation, variance testing, vs-random, walk-forward, synthetic-data stress with custom rules | Desktop, EasyLanguage-centric, no Indian market, table-heavy UI, no live streaming |
| **StrategyQuant X** | Auto strategy builder | Quants | ~€690–€1,290 | **Robustness as a build gate** — 5+ MC methods auto-*reject* fragile strategies; randomize params / trade order / data | Complex; desktop; FX/futures-centric; no beautiful reporting |
| **AmiBroker** | Fast backtester | Power retail | ~$279–$339 | Fastest engine; **probability of ruin**; automated walk-forward (IS+OOS); random trade/price perturbation | Windows-only; no scenario library; MC output is a table; no Indian costs |
| **QuantConnect** | Cloud algo platform | Coders/quants | Free–$60+/mo | **Parameter-sensitivity heatmaps** on cloud compute; point-in-time data (no lookahead); regime filtering | No stress-scenario presets; no MC spaghetti; code-required |
| **AlgoTest** | No-code Indian options | Indian retail | ₹0 (25/wk) – ₹499+/mo | Tick-level multi-leg options backtest; realistic fills; **AI agent "920"** (natural-language backtest) | No stress scenarios; no robustness/overfitting science; India-only |
| **Streak (Zerodha)** | No-code Indian algo | Indian retail | ~₹500–₹900/mo | Dead-simple no-code; tight Zerodha integration | Shallow backtest; no stress testing at all |
| **TradingView** | Charting + Pine backtest | Everyone | Free–$60/mo | **Best visual feedback** — signals overlaid on chart; huge community | "Deep Backtesting" is paywalled & shallow; no MC, no walk-forward, no robustness |
| **TrendSpider** | AI charting + bots | Retail | ~$30–$120/mo | **AI Strategy Lab** (natural-language strategy build), 50 yrs data, automation | No slippage/commission modeling; no MC/walk-forward; no stress |
| **NinjaTrader** | Futures platform | Futures retail | Free–$1,499 | Walk-forward + MC + genetic optimizer built-in | Futures-centric; MC is basic; dated UX |
| **MultiCharts** | Pro charting/backtest | Pro retail | ~$1,497 | Exhaustive + genetic optimization, transparent | **No built-in walk-forward** (workarounds needed); steep |
| **Wealth-Lab** | .NET backtester | Coders | ~$59/mo | Built-in walk-forward + MC + parameter-stability | .NET/C# required; niche |
| **MetaTrader 5** | Retail FX/CFD | FX retail | Free | Genetic optimization + **forward testing** (OOS); multi-currency | EA/MQL5 required; no scenario stress; no robustness score |
| **TradeZella / Tradewell** | Journal + backtest analytics | Retail | ~$29/mo | **Closes the loop**: backtest → live → analytics dashboard | Not a stress tester; no MC/scenarios |
| **BacktestBase** | MC robustness scoring | Retail | $ | **30-point robustness score (A–F)**; one-click MC with 10% trade-skip; regime-layered randomization | Narrow; not a full backtester |
| **LuxAlgo** | TradingView AI overlay | Retail | ~$40/mo | Crisis templates, AI backtesting assistant, slippage modeling | Overlay, not a standalone engine |
| **vectorbt (PRO)** | Vectorized engine | Python quants | Free / €€ PRO | Insane speed (1M orders ~70ms); **CPCV, purged CV, walk-forward, noise injection** | Library, not a product; code-required; no UI |

---

## 3. Feature Matrix

Legend: ✅ strong · 🟡 partial/basic · ❌ absent · **TV = TradeVed (today)**

| Capability | **TV** | Build Alpha | StratQuant X | AmiBroker | QuantConnect | Portfolio Viz | Aladdin | AlgoTest | TradingView |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **Scenario library (historical crises)** | ✅ 13 | 🟡 | 🟡 | ❌ | ❌ | 🟡 | ✅ | ❌ | 🟡 |
| **Pre-strategy data perturbation** | ✅ | ✅ | ✅ | 🟡 | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Monte Carlo (trade reshuffle/resample)** | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Monte Carlo (data/path)** | ✅ | ✅ | ✅ | 🟡 | ❌ | ✅ | ✅ | ❌ | ❌ |
| **MC permutation p-value** | ❌ | ✅ | ✅ | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Walk-forward optimization** | ✅† | ✅ | ✅ | ✅ | 🟡 | ❌ | ❌ | ❌ | ❌ |
| **Out-of-sample split** | ✅† | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | 🟡 | ❌ |
| **CPCV / purged CV** | ❌ | ❌ | ❌ | ❌ | 🟡 | ❌ | ❌ | ❌ | ❌ |
| **Overfitting probability (PBO)** | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Deflated / selection-bias Sharpe** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 🟡 | ❌ | ❌ |
| **Parameter sensitivity heatmap** | ❌ | ✅ 3D | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Probability of ruin** | ❌ | ✅ | 🟡 | ✅ | ❌ | 🟡 | ❌ | ❌ | ❌ |
| **CVaR / Expected Shortfall** | ❌ | 🟡 | ❌ | ❌ | 🟡 | 🟡 | ✅ | ❌ | ❌ |
| **Slippage / liquidity stress** | 🟡 | ✅ | ✅ | 🟡 | ✅ | ❌ | ✅ | 🟡 | ❌ |
| **Delayed-fill / execution stress** | ❌ | ✅ | ✅ | 🟡 | ✅ | ❌ | ✅ | 🟡 | ❌ |
| **Correlation-breakdown / portfolio** | ❌ | ❌ | ❌ | ❌ | 🟡 | 🟡 | ✅ | ❌ | ❌ |
| **Reverse stress testing** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 🟡 | ❌ | ❌ |
| **Single robustness score (A–F)** | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Live streaming MC visualization** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Canvas spaghetti (1000+ paths)** | ✅ | ❌ | ❌ | ❌ | ❌ | 🟡 | ❌ | ❌ | ❌ |
| **Delta-view (stress − baseline)** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Indian market + costs** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | 🟡 |
| **AI / natural-language scenario** | ❌ | ❌ | ❌ | ❌ | 🟡 | ❌ | ❌ | ✅ | 🟡 |
| **Shareable PDF report** | 🟡 | ✅ | ✅ | ✅ | 🟡 | ✅ | ✅ | 🟡 | ❌ |

**† = exists in the TradeVed *backtester* flow (`engine/validation.py`), but NOT yet wired into the *stress tester*.** This is the single most important correction to make when reading this doc: the walk-forward/OOS *engine is already built and battle-tested* — it just needs to be surfaced into the stress/robustness flow.

**Read of the matrix:** TradeVed *uniquely* owns the bottom-left cluster (streaming MC, canvas spaghetti, delta view, Indian costs), is competitive on the scenario library, and **already has the walk-forward/OOS engine** competitors charge thousands for. Where the *stress tester* is thin is the rest of the middle band — trade-level MC, permutation p-values, overfitting probability (PBO/DSR), parameter heatmaps, tail metrics, and a single robustness score. That band is exactly where trust and differentiation live, and TradeVed is closer to it than the matrix first suggests because the hardest piece (walk-forward) is done.

---

## 4. Most Loved Features Across the Market

What users repeatedly praise (Reddit r/algotrading, product reviews, forums, YouTube):

1. **Instant visual feedback** — signals overlaid on price; equity curve that updates as you tweak. *"The visual component is perfect for understanding why a trade was triggered."* (TradingView's #1 loved trait.) → **TradeVed already nails this with the live canvas.**
2. **Monte Carlo that exposes hidden drawdown** — Build Alpha's most-cited example: a backtest showing $1,663 max DD revealed a **$5,195 potential DD** under MC. Traders *love* being shown the drawdown they'd otherwise discover live.
3. **A single number / letter grade** — BacktestBase's "30-point score" and grade is beloved because it collapses a wall of stats into a decision. People trust and *share* a grade.
4. **Walk-forward "it survived out-of-sample"** — the single most trusted robustness signal among serious quants. AmiBroker/Build Alpha/Wealth-Lab users treat passing WFO as the bar for going live.
5. **Parameter-sensitivity heatmaps / 3D surfaces** — QuantConnect's & Build Alpha's most-loved discovery tool: *"is my profit a robust plateau or a single lucky spike?"*
6. **"Scenario priced-in" tracking** — HiddenLevers' signature: showing a scenario is "50% priced in" as oil moves $50→$75→$100. Advisors say it's the best client-trust tool they have.
7. **Variance / forward simulation** — Build Alpha's "how will this do over the next N trades at varying win rates" — users love a *forward* projection, not just a backward one.
8. **No-code + natural language** — AlgoTest's AI agent "920" and TrendSpider's AI Lab are loved for removing the coding wall entirely.
9. **Closing the loop** — TradeZella's auto-feed of backtest → live → analytics. The #1 complaint about *every other tool* is that it "stops at the backtest."
10. **Speed at scale** — vectorbt (1M orders in ~70ms) and QuantConnect cloud parallelism let users test thousands of variants; speed itself is a loved feature.

---

## 5. Most Requested / Missing Features

The recurring wishlist and frustrations across communities:

- **"Tell me if it's overfit."** The #1 anxiety in algo trading. Users want an explicit overfit verdict, not just good-looking numbers. (Red flags they cite: too-high returns, too-low DD, too many tuned parameters.)
- **"Close the gap between backtest and live."** Universally cited: *"Most tools stop at the backtest and you're on your own."* People want shadow/paper comparison and a realism model (spread, commissions, slippage, partial fills, borrow/funding — and Build Alpha-style **"then double the costs"**).
- **Realistic execution** — delayed fills, queue position, partial fills, slippage that scales with size. Backtests assuming perfect fills are distrusted.
- **Statistical significance (a real p-value)** — *"would this look this good on data with no edge?"* MC permutation p-values are requested but rarely shipped.
- **A robustness/confidence score** — one decision-grade number with a clear pass bar.
- **Probability of ruin / risk of hitting a kill-threshold** — requested constantly by risk-conscious traders.
- **Tail metrics** — CVaR / Expected Shortfall, not just max drawdown.
- **Multi-asset / portfolio stress with correlation breakdown** — the thing institutions have and retail doesn't: *"in a crash, diversification disappears."*
- **Indian-market-specific scenarios** — circuit breakers, SEBI events, expiry-day gamma, demonetization-style shocks. *Nobody* serves these.
- **Shareable, beautiful reports** — PDF/HTML you can hand to a client, a prop desk, or post.

---

## 6. Institutional Practices

How professional quant funds, prop firms, and bank risk desks actually validate robustness — the practices worth importing into a retail product:

### 6.1 Validation methodology
- **Out-of-sample is sacred.** Optimize on in-sample, *never touch* the OOS slice until the end. Hold-out alone is considered weak; serious desks use **walk-forward** (rolling re-optimization, e.g., 9 sequential splits) and increasingly **Combinatorial Purged Cross-Validation (CPCV)** — which purges overlapping samples and embargoes around test windows to kill information leakage, and produces a *distribution* of OOS performance rather than a single path. CPCV demonstrably yields lower **Probability of Backtest Overfitting (PBO)** than K-fold or walk-forward.
- **Multiple-testing correction.** When you try many strategies/parameters, the "best" is partly luck. Desks deflate for this:
  - **PBO** via **CSCV** (Bailey, Borwein, López de Prado, Zhu) — estimates the probability the selected config is overfit.
  - **Deflated Sharpe Ratio (DSR)** — corrects the Sharpe for selection bias under multiple trials *and* non-normal returns.
  - **Monte Carlo Permutation Test (MCPT)** — permute/shuffle the price series, re-run, and ask "would no-edge data have looked this good?" to get a real **p-value**.
- **Synthetic + historical dual validation.** Every model is tested on *both* real history and synthetic/noise-injected data to avoid relying on one-off anomalies.

### 6.2 Risk measurement
- **Expected Shortfall (CVaR) over VaR.** The Basel III **FRTB** replaced 99% VaR with **97.5% Expected Shortfall** as the primary market-risk measure — ES captures *how bad* the tail is, not just its frequency. Retail tools almost never show this.
- **Reverse stress testing.** Instead of "apply a 30% crash, see the loss," ask **"what scenario would break this strategy / blow the risk budget?"** and then characterize how plausible that is. Powerful and almost absent in retail.
- **Factor & macro stress.** Shock factors (rates, credit, vol, oil) and propagate through exposures; model **correlation breakdown** (correlations → 1 in panics, so diversification benefit evaporates — MSCI's "broken-arrow" test).

### 6.3 Pre-deployment discipline
- **Shadow / paper trading with production plumbing** — full logging, daily P&L reconciliation, real order-type logic, queue priority, latency — *before* a dollar is risked.
- **Cost realism then stress the costs** — model spread, commission, slippage, partial fills, borrow, funding — then **double the costs** and check the edge survives.
- **Kill-switches & live controls** — exposure limits, loss-cutting rules, auto-pause on regime shift or underperformance.

**Takeaway for TradeVed:** importing even *simplified, well-explained* versions of PBO, DSR, MCPT, CVaR/ES, walk-forward, and reverse stress testing would put a retail product on institutional footing — and none of TradeVed's retail competitors do this.

---

## 7. Where TradeVed Stands Today (Honest Self-Assessment)

From a line-level read of `engine/stress.py`:

**Genuine strengths (keep & market these):**
- **13 scenario presets** with methodologically sound *pre-strategy* OHLCV perturbation (`apply_stress` is a pure, deep-copying function — input never mutated). Scenarios include persistent crashes (`persist=True` prevents the snap-back/buy-low-sell-high artifact), bounces (GFC), V-recoveries (COVID), pump-dump, whipsaw/AR(1) chop, gap risk, vol spike, outlier injection.
- **Timeframe-aware shock durations** (`_candles_per_day` converts "days" → candles) so 1d and 4h runs are semantically comparable.
- **Monte Carlo with per-run magnitude jitter** (`severity × uniform(0.75, 1.25)`) + random shock start — paths fan out in timing *and* intensity (most retail MC only varies one).
- **Percentile aggregation** (P5/P50/P95/worst/best) for return, DD, Sharpe, Sortino, win-rate; an **equity fan** and up to **100 spaghetti paths** subsampled to 200 pts.
- **Live SSE streaming** endpoint (`/api/stress/stream`) emitting `baseline → run×N → complete`, with `asyncio.to_thread` so events flush — feeding a **canvas spaghetti chart** (1,000+ paths, HSL-colored, hover, click-to-pin) with a **delta-view toggle**. This UX is ahead of the entire retail field.
- **A full out-of-sample validation engine already exists** (`engine/validation.py`): `run_holdout` (train/test split + stable/degraded/failed verdict) and `run_walk_forward` (per-window grid-search by Sharpe → apply best params to OOS step → roll forward → aggregate OOS metrics + stitched validation curve). Exposed in the backtester via `validation_mode`, `wf_window`, `wf_step` and rendered in `ValidationPanel.tsx`. **This is a major asset most retail competitors lack — it's just not connected to the stress tester yet.**

**Structural limitations:**
- **Single-asset only** — no portfolio, no correlation breakdown.
- **Stress = data perturbation only** — no *trade-level* MC (reshuffle/resample), no parameter perturbation, no permutation p-value. *(Walk-forward/OOS exist but in the backtester flow — not yet reused by the stress tester to produce an overfit-aware robustness score.)*
- **Output = distribution of outcomes, not a verdict** — there's no robustness score, no overfit probability, no tail metric (CVaR/ruin), no statistical-significance test. The user still has to interpret.
- **Slippage stress is a single multiplier** (`slip_multiplier`) — no delayed/partial-fill modeling.
- **Scenarios are global price shocks**, not factor/macro-linked, and not Indian-specific.

**Verdict:** TradeVed has built the *hard, beautiful parts* — the scenario engine, the streaming visualization, **and a walk-forward/OOS validation engine** — that competitors either lack or charge thousands for. What's missing is *connecting* that validation science to the stress tester and distilling it into a trusted verdict (a robustness score, overfit probability, tail metrics). That's a very good position to be in: the remaining work is mostly **integration + scoring**, not a rewrite, because the most expensive component (walk-forward) already exists and works.

---

## 8. Product Gaps

Ranked by how much they hurt trust/differentiation:

1. **No single robustness verdict.** Output is a distribution; users want a grade + pass/fail. (Build Alpha, BacktestBase prove demand.)
2. **Overfitting science not connected to stress.** Walk-forward + OOS *exist* (`engine/validation.py`) but only in the backtester — the stress tester doesn't reuse them, and there's still no CPCV, PBO, DSR, or MCPT p-value anywhere. Wiring the existing walk-forward into a stress-side overfit signal is low-hanging fruit; the rest separates "trustworthy" from "toy."
3. **No tail-risk layer.** No CVaR/Expected Shortfall, no probability of ruin — both heavily requested.
4. **No trade-level Monte Carlo.** Only data-path MC. Reshuffle/resample MC (and trade-skip) is the most familiar MC to traders and cheap to add.
5. **No parameter-sensitivity heatmap.** The single most-loved robustness *discovery* tool (QuantConnect/Build Alpha) — and TradeVed has the optimizer data to build it.
6. **No execution-realism stress.** Delayed/partial fills, size-scaled slippage, "double the costs" toggle.
7. **No portfolio / correlation-breakdown stress.** The institutional crown jewel; nobody serves retail here.
8. **No reverse stress testing.** "What breaks me?" — high wow-factor, low competition.
9. **No Indian-specific scenarios.** A defensible moat given the existing Indian cost model.
10. **No AI/natural-language scenario builder.** AlgoTest/TrendSpider show this is now table-stakes-trending.
11. **No shareable stress report (PDF).** Blocks virality and pro/advisor use.
12. **Doesn't close the loop to paper/live.** The universal complaint.

---

## 9. Opportunities for TradeVed

### Underserved segments
- **Indian retail algo traders** (exploding, served only by shallow tools like Streak/AlgoTest with *zero* stress testing). TradeVed's Indian cost model + F&O lots is a ready-made wedge.
- **Serious retail quants priced out of Build Alpha/desktop tools** who want robustness science in a *web* product with great UX.
- **Prop-firm-funded traders** who must *prove* robustness to keep an account — a robustness score + PDF report is exactly their need.

### Cheap differentiators (you already own the building blocks)
- **Regime-aware Monte Carlo — the biggest easy win.** Your MC currently fans out with flat `severity × uniform(0.75, 1.25)` jitter (`stress.py:456`). You *already ship* `engine/regimes.py` (timeframe-aware bull/bear/sideways detection, run after every backtest). Feed it into the MC loop so each run samples **regime-specific volatility** — bear-regime runs draw fatter-tailed, higher-vol shocks; sideways runs draw tighter ones. BacktestBase only does this "partially"; with `regimes.py` already built, TradeVed can do it *better*, and it makes the spaghetti fan **physically realistic** instead of uniform noise. Low effort, high uniqueness.
- **No-lookahead "point-in-time" guarantee + badge.** QuantConnect's single most-trusted feature, and retail tools are widely distrusted here. Audit the signal path so indicators never peek at future candles, then display a **"✓ No lookahead bias" badge** on results. Cheap to verify, outsized trust payoff.
- **Selectable MC models.** Portfolio Visualizer's loved option — let the user choose the MC engine: **historical bootstrap**, **block bootstrap** (preserves autocorrelation), **parametric (μ/σ)**, or your existing **scenario-perturbation** method. One dropdown, several methods, broad appeal.

### UX / visualization innovations (extend existing strengths)
- The canvas spaghetti chart is a unique asset — extend it to **walk-forward windows** (each OOS slice as a segment), **parameter heatmaps**, and **reverse-stress "break point" markers**.
- A **"Robustness Gauge"** hero component (A+→F dial) at the top of `StressResults` — the single most shareable element you could add.
- **"Priced-in" scenario meter** (HiddenLevers-style) tied to live price vs scenario target.
- **"What-If" stressed-path overlay** — draw the perturbed price path *on top of* the real candlestick chart (LuxAlgo-style), distinct from the equity delta-view, so users *see* the shock applied to price.
- **Multi-strategy "book" stress** — stress all of a user's deployed strategies at once (HiddenLevers' household-level idea, applied to a book of algos) and aggregate the blast radius.

### AI-assisted workflows
- **Natural-language scenario builder**: "crash NIFTY 30% over 2 months with two relief rallies, then stay down" → parameters for a `StressScenario`. (You already have the dataclass; this is a thin LLM-to-params layer.)
- **AI verdict narrator**: turn the score + metrics into a plain-English paragraph ("Your strategy survived 10/13 scenarios but is fragile to slow bleeds and shows HIGH overfit risk because OOS Sharpe is 38% of in-sample…").
- **Auto-recommendations**: "reduce parameter count," "widen the EMA plateau," "your edge vanishes after costs ×2."

### Automation opportunities
- **Robustness gate** (StrategyQuant-style): in the optimizer (`crypto_optimizer.py`, `indian_futures_optimizer.py`), auto-reject configs that fail MC/walk-forward — surface only robust strategies.
- **Scheduled re-stress**: re-run the suite weekly on new data; alert if a deployed strategy's robustness score degrades.

---

## 10. Recommended Features — Ranked by Priority

Scored on **Impact** (trust + differentiation), **Effort**, **Demand**, **Moat**. P0 = do first.

| # | Feature | Impact | Effort | Demand | Moat | Priority |
|---|---------|:------:|:------:|:------:|:----:|:--------:|
| 1 | **Robustness Score (A+→F) + Gauge** | 🔥🔥🔥 | Low | 🔥🔥🔥 | Med | **P0** |
| 2 | **Probability of Ruin + CVaR/ES in MC output** | 🔥🔥🔥 | Low | 🔥🔥 | Med | **P0** |
| 3 | **Trade-level MC (reshuffle/resample) + trade-skip %** | 🔥🔥 | Low | 🔥🔥🔥 | Low | **P0** |
| 4 | **Indian-specific scenario presets** | 🔥🔥 | Low | 🔥🔥 | 🔥🔥🔥 | **P0** |
| 5 | **Wire EXISTING walk-forward/OOS into stress robustness score** (reuse `validation.py`) | 🔥🔥🔥 | **Low** | 🔥🔥🔥 | Med | **P0** |
| 6 | **Parameter-sensitivity heatmap** | 🔥🔥🔥 | Med | 🔥🔥 | Med | **P1** |
| 7 | **MC permutation p-value (MCPT)** | 🔥🔥 | Med | 🔥🔥 | 🔥🔥 | **P1** |
| 8 | **Execution-realism stress (delay/partial/×2 costs)** | 🔥🔥 | Med | 🔥🔥 | Med | **P1** |
| 9 | **AI verdict narrator + NL scenario builder** | 🔥🔥 | Med | 🔥🔥 | 🔥🔥 | **P1** |
| 10 | **Deflated Sharpe + PBO (overfit engine)** | 🔥🔥🔥 | High | 🔥🔥 | 🔥🔥🔥 | **P2** |
| 11 | **Reverse stress testing ("what breaks me?")** | 🔥🔥 | High | 🔥 | 🔥🔥🔥 | **P2** |
| 12 | **Portfolio + correlation-breakdown stress** | 🔥🔥🔥 | High | 🔥🔥 | 🔥🔥🔥 | **P2** |
| 13 | **Shareable PDF stress report** | 🔥🔥 | Low | 🔥🔥 | Low | **P1** |
| 14 | **CPCV engine** | 🔥🔥 | High | 🔥 | 🔥🔥🔥 | **P3** |
| 15 | **Paper/live loop-closure comparison** | 🔥🔥🔥 | High | 🔥🔥🔥 | Med | **P3** |
| 16 | **Regime-aware MC** (reuse `regimes.py` for per-run vol) | 🔥🔥 | Low–Med | 🔥🔥 | 🔥🔥🔥 | **P1** |
| 17 | **No-lookahead audit + trust badge** | 🔥🔥 | Low | 🔥🔥 | Med | **P1** |
| 18 | **Selectable MC models** (bootstrap / parametric) | 🔥 | Med | 🔥🔥 | Low | **P2** |
| 19 | **"What-If" stressed-path overlay on chart** | 🔥 | Low | 🔥 | Med | **P2** |

---

## 11. TradeVed Opportunity Roadmap

### Phase 1 — "Trust Layer" (2–4 weeks) — *ship a verdict, not just a chart*
Turn the existing distribution into a decision.
- **Robustness Score + A–F Gauge** (§13.1). Computed from data you *already* produce (`monte_carlo` percentiles + `baseline`/`stressed`). Hero dial in `StressResults.tsx`.
- **Tail metrics in MC aggregation**: add **CVaR/Expected Shortfall (5%)**, **Probability of Ruin**, **return P1**, **MC max-DD P95** to `_pcts()` / `aggregate_stress_results()` in `stress.py`.
- **Trade-level MC + trade-skip slider**: add `mc_mode: "data" | "trades" | "both"` and a `trade_skip_pct` (default 10%) — reshuffle/resample the realized trade list; cheap and familiar.
- **4 Indian scenario presets**: `demonetization_2016`, `covid_nifty_mar2020`, `yes_bank_2020`, `expiry_gamma_squeeze` — add to `SCENARIO_PRESETS`, `SCENARIO_DISPLAY/GROUPS/DEFAULTS` (StressSidebar) and `StressScenarioKey` (types.ts).
- **Wire the EXISTING walk-forward/OOS engine into the stress score** *(reuse, not build)*: call `run_walk_forward` / `run_holdout` (already in `engine/validation.py`) from the stress flow and compute **Walk-Forward Efficiency (WFE)** = aggregated OOS Sharpe ÷ mean in-sample `train_sharpe`. This makes the Robustness Score **overfit-aware on day one** with no new engine — `run_walk_forward` already returns per-window `train_sharpe` and OOS `sharpe`.
- **Regime-aware MC** *(reuse `regimes.py`)*: replace the flat `uniform(0.75, 1.25)` per-run jitter with **regime-conditioned volatility** drawn from the regime mix `classify_regimes` already detects — physically realistic fan-out, and a differentiator no retail tool does well.
- **No-lookahead badge**: audit the signal path, then show a **"✓ No lookahead bias"** trust badge on results.
- **AI verdict narrator**: one paragraph generated from score + metrics.

*Outcome:* TradeVed goes from "shows you stress paths" to "**grades your strategy and explains why**" — instantly differentiated from every retail competitor, and overfit-aware immediately by reusing code that already exists.

### Phase 2 — "Validation Science" (4–8 weeks) — *earn quant trust*
- **Deepen the walk-forward already wired in Phase 1**: render per-window OOS segments on the canvas spaghetti; layer **CPCV-style multiple train/test splits** on top of the existing `run_walk_forward` to produce a *distribution* of OOS outcomes (not a single stitched path); use it as an auto-reject **gate** in `crypto_optimizer.py` / `indian_futures_optimizer.py`.
- **Parameter-sensitivity heatmap**: 2-param grid → 2D/3D surface; flag "robust plateau vs lucky spike." (Reuse optimizer output.)
- **MC permutation p-value (MCPT)**: permute price series, re-run, report p-value ("1.2% chance this is luck").
- **Execution-realism stress**: delayed-fill (1–2 candles), partial fills, size-scaled slippage, **"double the costs"** toggle.
- **Shareable PDF report** (extend `frontend/report.py`): score, scenario table, MC fan, heatmap, verdict.

### Phase 3 — "Institutional Moat" (8–16 weeks) — *features no retail tool has*
- **Overfit engine**: **Deflated Sharpe Ratio** + **PBO via CSCV** → "Overfit Risk: LOW/MED/HIGH."
- **Reverse stress testing**: search for the minimal shock (depth/duration/vol) that pushes the strategy below a user threshold; mark the "break point."
- **Portfolio + correlation-breakdown stress**: multi-symbol; in crash scenarios force pairwise correlations toward 1.0 and show diversification collapse.
- **CPCV** for the most rigorous OOS distribution.
- **(Stretch) Paper/live loop-closure**: compare deployed P&L to the stressed envelope; alert on robustness decay.

---

## 12. The Ultimate Stress Tester — Blueprint

A layered design. TradeVed already owns Layers 1 and the Visualization layer; the blueprint adds 2–6.

```
┌─────────────────────────────────────────────────────────────────────┐
│ 0. INPUT: strategy + params + asset(s) + capital + cost model         │
└─────────────────────────────────────────────────────────────────────┘
        │
┌───────▼───────────────┐  ┌────────────────────────┐  ┌───────────────────────┐
│ 1. SCENARIO ENGINE     │  │ 2. MONTE CARLO ENGINE   │  │ 3. VALIDATION ENGINE   │
│  (HAVE ✅)             │  │                         │  │  (overfitting science) │
│ • 13 + Indian presets  │  │ • Data-path MC (HAVE)   │  │ • Walk-forward / OOS    │
│ • Custom + NL builder  │  │ • Trade reshuffle/resamp│  │ • CPCV (purged+embargo) │
│ • persist crashes      │  │ • Trade-skip %          │  │ • PBO (CSCV)            │
│ • factor/macro shocks  │  │ • Noise / permutation   │  │ • Deflated Sharpe       │
│ • reverse stress search│  │ • per-run jitter (HAVE) │  │ • MCPT p-value          │
└───────┬───────────────┘  └───────────┬─────────────┘  └───────────┬───────────┘
        └──────────────┬───────────────┴─────────────────────────────┘
                       │
        ┌──────────────▼───────────────┐   ┌──────────────────────────────┐
        │ 4. RISK ANALYSIS LAYER        │   │ 5. SCORING ENGINE             │
        │ • CVaR / Expected Shortfall   │──▶│ • Robustness Score (A+→F)     │
        │ • Probability of Ruin         │   │ • Overfit Risk (LOW/MED/HIGH) │
        │ • Tail / drawdown percentiles │   │ • Confidence band (sample-aware)│
        │ • Correlation-breakdown (port)│   │ • Per-axis sub-scores         │
        └──────────────┬───────────────┘   └──────────────┬───────────────┘
                       │                                   │
        ┌──────────────▼───────────────────────────────────▼─────────────┐
        │ 6. VISUALIZATION + REPORTING (HAVE strong base ✅)              │
        │ • Live canvas spaghetti + delta view (HAVE)                     │
        │ • Robustness gauge · heatmap · WFO segments · break-point marker │
        │ • AI verdict narrator · shareable PDF/HTML report               │
        └────────────────────────────────────────────────────────────────┘
```

### Core feature set (must-have)
- Scenario library (historical + Indian + custom) — **HAVE, extend**
- Dual Monte Carlo: data-path (HAVE) **+ trade-level** with skip %
- Walk-forward / OOS validation — **HAVE in backtester (`validation.py`); wire into stress**
- Tail risk: CVaR/ES + Probability of Ruin
- **Robustness Score (A+→F)** with per-axis breakdown
- Live spaghetti + delta view — **HAVE**

### Advanced feature set
- Parameter-sensitivity heatmap (robust-plateau detection)
- MC permutation p-value; Deflated Sharpe; PBO
- Reverse stress testing (break-point search)
- Execution realism (delay/partial fills, size-scaled slippage, ×2 costs)
- Portfolio + correlation-breakdown stress (+ multi-strategy "book" aggregation)
- **Regime-aware MC** (per-run vol from `regimes.py`) + **selectable MC models** (historical/block bootstrap, parametric, scenario-perturbation)
- **No-lookahead / point-in-time guarantee** with a visible trust badge

### AI-powered capabilities
- **NL scenario builder** (text → `StressScenario`)
- **AI verdict narrator** (metrics → plain-English risk story + fixes)
- **Auto-robustness-gate** in optimizers (reject fragile configs)
- **Anomaly explainer** ("why did run #318 lose 60%? — the COVID crash hit during a cascade entry")

### Validation engine (how it works)
> **Steps 1–3 already exist** in `engine/validation.py` (`run_walk_forward`, `run_holdout`) and run in the backtester today. The net-new work is (a) calling them from the stress flow and (b) adding steps 4–6.
1. Split history → walk-forward windows (`run_walk_forward`, default window=252 / step=63) **or** CPCV groups (purge + embargo). *(walk-forward: HAVE)*
2. Re-optimize in-sample (grid-search best params by Sharpe), record OOS performance per window → **distribution**, not a point. *(HAVE)*
3. **WFE** = mean OOS Sharpe / mean IS Sharpe (≥0.5 healthy). *(computable now from `run_walk_forward` output)*
4. **PBO** via CSCV: fraction of combinatorial splits where the IS-best config underperforms median OOS. *(new)*
5. **MCPT**: permute prices, re-run N times → p-value = rank of real performance in the null. *(new)*
6. **DSR**: deflate Sharpe for #trials and non-normality. *(new)*

### Reporting engine
- One-click **PDF/HTML** (extend `frontend/report.py`): score gauge, scenario Δ-table, MC fan, heatmap, WFO segments, tail metrics, AI verdict. Shareable link for prop desks/advisors/social.

### Risk analysis layer
- CVaR/ES (5%), Probability of Ruin (P(equity < kill-threshold)), DD percentiles, recovery-time distribution, and (portfolio) correlation-breakdown impact.

---

## 13. Scoring Frameworks (Implementation Spec)

### 13.1 TradeVed Robustness Score (TRS) — 0–100 → A+…F

A weighted composite, **computable mostly from data `stress.py` already returns**. Each sub-score normalized 0–100.

| Axis | Weight | Inputs (already available unless noted) | Intuition |
|------|:------:|------------------------------------------|-----------|
| **Scenario Survival** | 30% | % of 13 scenarios with Δ% ≥ −X; median Δ%; worst scenario Δ% | Does it survive known crises? |
| **MC Stability** | 25% | MC `return_pct.p5 > 0?`; P5/P50 ratio; dispersion (P95−P5) | Is the edge consistent across paths? |
| **Tail Safety** | 20% | CVaR(5%); Probability of Ruin; MC `max_drawdown_pct.p95` *(add)* | How ugly is the worst case? |
| **Overfit Resistance** | 25% | Walk-Forward Efficiency *(available NOW via `validation.py`)*; MCPT p-value & param-plateau width *(Phase 2 refinements)* | Will it survive *unseen* data? |

```
TRS = 0.30·Survival + 0.25·MC_Stability + 0.20·Tail_Safety + 0.25·Overfit_Resistance

Grade:  A+ ≥ 90 · A 80–89 · B 70–79 · C 60–69 · D 50–59 · F < 50
```
Because walk-forward **already exists**, the Overfit Resistance axis can use **WFE from day one** — so the full 4-axis TRS is achievable in Phase 1 (MCPT p-value and parameter-plateau width refine this axis later). Only fall back to a **Provisional TRS** (first three axes, re-weighted to 100%) when the user's date range is too short for walk-forward (`n < wf_window + wf_step`), and label it "Provisional — widen date range for the overfit-resistance score."

### 13.2 Overfit Risk (separate verdict)
```
Signals → verdict:
  WFE  = OOS_Sharpe / IS_Sharpe       (<0.3 bad, 0.3–0.5 caution, >0.5 good)
  PBO  = P(backtest overfit) via CSCV (>0.5 bad)
  MCPT = permutation p-value          (>0.10 bad → result indistinguishable from luck)
  DSR  = deflated Sharpe              (≤0 bad → not significant after multiple-testing)

Overfit Risk = LOW  (≥3 green) · MEDIUM (mixed) · HIGH (≥2 red)
```

### 13.3 Confidence Band (sample-aware)
Don't show a crisp score on thin evidence. Scale a confidence interval by **#trades**, **#MC runs**, and **OOS-window count**:
```
low trades (<30) OR low MC (<200)  → "Low confidence — widen date range / raise MC runs"
else                                → show TRS ± half-width from MC P5/P95 dispersion
```

### 13.4 Probability of Ruin & CVaR (drop-in for `stress.py`)
- Add to the `_pcts()` consumers in `run_stress_backtest` / `aggregate_stress_results`:
  - `cvar_5 = mean(returns[returns <= percentile(returns, 5)])`
  - `prob_ruin = mean(final_equity < kill_threshold)` where `kill_threshold = capital × (1 − max_loss_tolerance)` (default 50%)
  - `ret_p1 = percentile(returns, 1)` and `maxdd_p95` (already have the array).
- Surface in `monte_carlo` payload → render in `StressResults.tsx` MC panels.

---

## 14. Sources

**Institutional / portfolio stress**
- [BlackRock Aladdin — Power of Stress Testing](https://www.blackrock.com/aladdin/products/aladdin-wealth/insights/power-of-stress-testing)
- [Bloomberg PORT — Build custom stress scenarios](https://www.bloomberg.com/professional/insights/trading/how-to-build-custom-scenarios-to-stress-test-your-portfolio/)
- [MSCI — A Stress Test to Incorporate Correlation Breakdown](https://www.msci.com/www/research-report/a-stress-test-to-incorporate/018449914)
- [HiddenLevers — Interactive Stress Testing](https://help.hiddenlevers.com/help/stress-testing-training-video) · [Capterra reviews](https://www.capterra.ca/software/179454/hiddenlevers)
- [Top 10 Financial Stress Testing Platforms — Cotocus](https://www.cotocus.com/blog/top-10-financial-stress-testing-platforms-features-pros-cons-comparison/)

**Robustness / quant tools**
- [Build Alpha — Robustness Testing Guide](https://www.buildalpha.com/robustness-testing-guide/) · [Monte Carlo Permutation](https://www.buildalpha.com/monte-carlo-permutation/) · [Monte Carlo Simulation](https://www.buildalpha.com/monte-carlo-simulation/)
- [StrategyQuant X — Types of robustness tests](https://strategyquant.com/doc/strategyquant/types-of-robustness-tests-in-sqx/) · [5 Monte Carlo methods](https://strategyquant.com/blog/new-robustness-tests-on-the-strategyquant-codebase-5-monte-carlo-methods-to-bulletproof-your-trading-strategies/)
- [AmiBroker — Walk-forward](https://www.amibroker.com/guide/h_walkforward.html) · [Features](https://mail.amibroker.com/features.html) · [Review](https://enlightenedstocktrading.com/amibroker-software-review/)
- [QuantConnect Review — LuxAlgo](https://www.luxalgo.com/blog/quantconnect-review-best-platform-for-algo-trading-2/) · [Backtesting docs](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting)
- [Portfolio Visualizer — Monte Carlo](https://www.portfoliovisualizer.com/monte-carlo-simulation)
- [Wealth-Lab vs MultiCharts](https://enlightenedstocktrading.com/multicharts-vs-wealth-lab/) · [NinjaTrader vs MultiCharts](https://enlightenedstocktrading.com/ninjatrader-vs-multicharts/) · [MultiCharts WFO](https://www.multicharts.com/trading-software/index.php?title=Walk_Forward_Optimization)
- [vectorbt (GitHub)](https://github.com/polakowo/vectorbt) · [VectorBT PRO features](https://vectorbt.pro/)
- [BacktestBase — MC Stress Testing](https://www.backtestbase.com/education/monte-carlo-stress-testing)
- [LuxAlgo — Stress Testing Your Algo](https://www.luxalgo.com/blog/stress-testing-your-algo-preparing-for-the-worst/) · [Backtesting ranked for retail quants](https://www.luxalgo.com/blog/backtesting-software-ranked-for-retail-quants/)

**Retail / Indian / charting**
- [AlgoTest — Best options backtesting India](https://algotest.in/blog/best-backtesting-software-for-options-trading-in-india/) · [AlgoTest](https://algotest.in/)
- [TrendSpider review](https://www.liberatedstocktrader.com/trendspider-review-automated-stock-trend-analysis/)
- [MetaTrader 5 Strategy Tester](https://www.metatrader5.com/en/automated-trading/strategy-tester)
- [TradeZella — best backtesting software](https://www.tradezella.com/blog/best-backtesting-software) · [Tradewell](https://www.tradewell.app/)

**Overfitting / statistical science**
- [The Probability of Backtest Overfitting (Bailey, Borwein, López de Prado, Zhu)](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) · [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- [The Deflated Sharpe Ratio (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- [Combinatorial Purged Cross-Validation — Papers With Backtest](https://paperswithbacktest.com/course/combinatorial-purged-cross-validation-cpcv) · [Purged cross-validation (Wikipedia)](https://en.wikipedia.org/wiki/Purged_cross-validation) · [Traditional Backtesting is Outdated — Use CPCV](https://www.insightbig.com/post/traditional-backtesting-is-outdated-use-cpcv-instead)
- [Expected Shortfall / CVaR explained](https://ryanoconnellfinance.com/expected-shortfall-cvar/) · [Reverse stress testing & dynamic loss models (arXiv)](https://arxiv.org/pdf/2211.03221)
- [Human-in-the-Loop Quant: anti-overfitting workflow](https://medium.com/@aymane.bt/human-in-the-loop-quant-an-anti-overfitting-workflow-for-ai-generated-trading-ideas-211f3eb6bc4a)

---

*Prepared as a living strategy document — update as features ship and the competitive field moves.*
