# Reel → Honest Backtest — Research & Architecture

> Companion to `architecture.pdf` / `architecture.svg` (regenerate: `python build_architecture.py`).
> A complete trading novice pastes a reel link; the platform **triages** it, **understands** the
> strategy, **compiles** it onto our existing engine, **backtests** it honestly, and returns a
> plain-language verdict. This document is the research that the diagram is built on.

---

## PART A — Has anyone built this? (research landscape)

**Short answer:** No one ships *"paste a short-form video → automatic backtest."* The pieces all
exist separately; nobody has assembled them around **reels** for **novices** on top of an honest
engine. That gap is the opportunity.

### A.1 The closest things that exist — video/audio → strategy

| What | What it does | What it proves / lacks |
|------|--------------|------------------------|
| **`tonbistudio/model-trader`** (open source) | `yt-dlp` pulls a YouTube transcript → **Claude** distills it into a *strategy document* (prose IR) + a "philosophy" doc → a developer **hand-codes** pass/fail "gates" → custom candle-walking backtester → paper trading. | Direct precedent for *transcript → LLM → spec → backtest*. But: **no formal schema** (prose, not JSON), **a human writes the executable gates**, no OCR, no novice UX. It's "the harness around a strategy," explicitly not turnkey. |
| **RogueQuant "2-prompt" method** | Prompt 1 extracts only actionable logic (entry/exit/stop/context), corrects garbled STT (e.g. "our aside" → "RSI"), flags missing pieces as `REQUIRES_SPECIFICATION`; Prompt 2 converts to platform-agnostic IF/THEN pseudocode. | Validates the **two-stage extraction** and **gap-flagging** design. Key stat from this work: **~70% of trading videos contain no testable strategy** — hence our Triage gate. Output is pseudocode, still needs a human to wire up. |
| **ICAIF-2025 "Democratizing Alpha"** (academic, ACM) | Feeds **YouTube market-commentary transcripts** (Bloomberg, Yahoo Finance) to four LLMs → builds portfolios → backtests vs S&P 500 / NASDAQ. | Proves video-transcript → LLM → backtest is academically live. But it's **portfolio allocation from commentary**, not extracting a *rule-based strategy* from a how-to reel. |

### A.2 The mature, crowded neighbour — natural-language → backtest (typed text, not video)

- **Composer (SoFi)** — strategies are "**Symphonies**": a **structured conditional tree the engine
  interprets**, built via visual editor / NL. *This is the single most important precedent:* a serious
  product compiles NL into a **deterministic spec the engine runs, not LLM-written code.** That is
  exactly the design choice we make in stage 03.
- **TrendSpider** — NL or point-and-click → no-code backtest engine on decades of data; "AI Strategy Lab".
- **TradrLab / LuxAlgo / AlgoBuilder / Capitalise.ai** — "describe entries/exits in plain English →
  AI builds + backtests." AlgoBuilder writes Python over tick data with real spreads/slippage; LuxAlgo's
  "Quant" generates + validates + debugs the code.

**Takeaway:** the *NL → strategy → backtest* half is a solved, competitive space. **Our wedge is the
input modality (a reel) and the audience (a novice who can't write the rules themselves)** — plus an
engine that's honest about costs and overfitting.

### A.3 Research cautions we must design around

- **"Profit Mirage: Revisiting Information Leakage in LLM-based Financial Agents" (2025).** LLMs have a
  training cutoff; when an LLM *reasons over a historical period it has already seen*, it leaks the
  future → backtests look great **within** the cutoff and **collapse after** it. Mitigations: temporal
  segregation, **always validate on post-cutoff / out-of-sample data**, state the simulation date, and
  paper-trade before trusting. *Our exposure is smaller than agent systems* because **our LLM only
  extracts a static rule once — it does not make per-bar decisions** — but the trap still applies to any
  parameter the LLM might "tune" from memory, so the OOS/walk-forward gates (already built) are
  load-bearing, not optional.
- **LLM trading agents overfit and most underperform.** Papers like *"Can LLM-based Strategies
  Outperform the Market in the Long Run?"*, *QuantAgent*, and *TradingAgents* all converge on: rigorous
  backtest evaluation is the hard part, and naive results are usually a mirage. → This is why **honesty
  is the product**, not a disclaimer bolted on.
- **QuantEvolve** (multi-agent *evolutionary* strategy discovery) — precedent for our **orchestrator
  refine-loop**, but we keep it *bounded and cheap* (refine the IR, re-run), not open-ended search.

---

## PART B — The architecture (built from scratch, grounded in A)

### B.0 The one structural insight

The original sketch was six greenfield stages. Mapped against what the **TradeVed Backtester already
ships**, the truth is: **the backtest + evaluation half is built; the new work is a thin
reel-understanding front-end that compiles into our existing strategy contract.** Two consequences:

1. **The "Strategy IR" is not a new format — it is our `CustomStrategy` schema** (`entry_rules` /
   `exit_rules` / `logic` over a 25-indicator engine). The extractor targets *that*, not a new IR.
2. **Stage 03 "Compilation" is a deterministic mapper, not LLM codegen** — exactly Composer's Symphony
   model. This removes the biggest engineering + security risk in the original design.

### B.1 Build status by stage

| Stage | Status | Exists today | New work |
|-------|--------|--------------|----------|
| 00 Triage | **TO BUILD** | — | cheap LLM classifier: strategy vs commentary/hype/ad |
| 01 Ingestion | **TO BUILD** | — | reel download, Whisper STT, frame OCR, caching |
| 02 Extraction | **TO BUILD** | — | 2-prompt LLM → strict IR, gap-flag, confidence, HITL edit |
| 03 Compilation | **PARTIAL** | `CustomStrategy`, registry, `/api/indicators`, `/api/strategies` | IR→params mapper, Pine export |
| 04 Backtest | **BUILT** | simulator, cost models, 54 strategies, regimes, market data | reuse verbatim |
| 05 Evaluation | **BUILT** | metrics, stress (17), MC, walk-forward/OOS, Kronos, crisis sim | **leakage guard + faithfulness gate** |
| 06 Insights | **PARTIAL** | equity/drawdown/candle/MC charts, HTML report | novice plain-language verdict + disclaimers |
| Orchestrator | **TO BUILD** | (reuse stress/forecast SSE patterns) | the bounded 02→05 refine loop |
| Infra | **TO BUILD** | SQLite, blocking endpoints | Redis/RQ queue + Postgres (Roadmap K2) |

**Net new engineering ≈ stages 00–02 + two eval gates + a verdict layer.** Everything else is wiring.

### B.2 Stage-by-stage (only the non-obvious parts)

**00 · Triage gate (new, research-driven).** A cheap LLM call on caption + transcript classifies the
reel: *testable strategy / market commentary / motivational hype / ad*. ~70% of content has no entry
rule, no instrument, or no exit — reject those **before** paying for full extraction + backtest. This
protects cost, latency, and credibility (never backtest a hype clip and dignify it as a "strategy").

**01 · Ingestion.** A reel hides the strategy in **three** places, and you need all three:
- **Audio** — often Hinglish (the founder's own voice note). STT must be multilingual (faster-whisper).
- **On-screen text** — the actual indicator *values* are usually **burned into the video**, not spoken
  → sample frames + OCR.
- **Caption** — frequently "full rules in comments / link in bio."
**Gotchas:** scraping breaks platform ToS → use official APIs or treat download as the user's action;
**cache by reel-ID** so a reel is processed once.

**02 · Extraction (two-prompt, from the RogueQuant precedent).**
- **Prompt 1 — Clean & isolate:** repair garbled STT, strip narrative, extract **only explicitly stated**
  rules (entry / exit / stop / target / instrument / timeframe). Anti-hallucination is a hard rule:
  *never invent an indicator or a precise threshold.*
- **Prompt 2 — Normalize:** emit the **strict Strategy-IR JSON** (= `CustomStrategy` shape),
  schema-validated against the indicator catalog.
- **Gap detection:** any missing parameter → `REQUIRES_SPECIFICATION`, surfaced to the user, never
  guessed. **Human-in-the-loop:** the novice reviews/edits the draft IR before it runs — load-bearing,
  not polish, because the LLM *will* produce plausible-but-wrong rules.

**The bridge — IR ≡ CustomStrategy.** Extraction outputs one of:
```jsonc
// (a) a known preset
{ "strategy": "RSI", "params": { "length": 14, "oversold": 30, "overbought": 70 } }

// (b) a CustomStrategy IR for anything else — already a valid /api/backtest/run input
{ "strategy": "CUSTOM",
  "params": {
    "entry_rules": [
      {"left": {"indicator":"rsi","params":{"length":14},"output":"rsi"}, "operator":"<", "right":{"value":30}},
      {"left": {"indicator":"ema","params":{"length":50},"output":"ema"}, "operator":"cross_above", "right":{"price":"close"}}
    ],
    "exit_rules":  [{"left": {"indicator":"rsi","params":{"length":14},"output":"rsi"}, "operator":">", "right":{"value":70}}],
    "logic": "AND", "invest_per_trade_usd": 1000
  } }
```
Operators today: `> >= < <= cross_above cross_below`; operands: `{indicator,params,output}` | `{price}` |
`{value}`. The LLM's entire job is to produce this faithfully — a constrained, validated target.

**03 · Compilation — map, don't codegen.** Deterministic mapper: IR → registry-preset params or →
`CustomStrategy`. Validate against `/api/indicators` + `param_schema()`. Python is canonical; **Pine
Script is an optional export only** (it's locked inside TradingView and can't feed our metrics/charts —
this resolves the founder's "Pine vs Python" question). A real sandbox is needed only for a rare
free-form fallback; presets + rule-IR need none.

**04 · Backtest — already shipped (reuse).** Simulator (WACB, partial fills, lot-size enforcement),
`IndianCostModel`/`SimpleCostModel`, point-in-time OHLCV (crypto/NSE/BSE/US), look-ahead guard,
timeframe-aware regimes. A compiled reel is just another `STRATEGY_REGISTRY` call. Honest costs
(slippage/commission/spread) are baked in — a no-cost backtest flatters junk.

**05 · Evaluation — the founder's open question, answered.** Four checks:
- **Did it run?** enough trades to be statistically meaningful (4 trades prove nothing).
- **Is it good?** CAGR · Sharpe · Sortino · Calmar · MaxDD · win% · profit factor, **always vs
  buy-&-hold** (NIFTY/SPY). Underperforming buy-and-hold = worse than doing nothing.
- **Is it real?** in-sample vs out-of-sample · walk-forward · Monte-Carlo · 17-scenario stress test ·
  Kronos forward-test (P5/P50/P95) · crisis sim — **all already built.**
- **(new) Leakage guard + faithfulness:** validate OOS/post-cutoff (Profit Mirage), never let the LLM
  tune parameters from memory, and check the compiled IR **actually matches** the reel's claim
  (re-derive the IR, diff the two). Faithfulness failure → orchestrator loops back to stage 02.

**06 · Insights — for a user who knows nothing.** Charts already exist. New = the **plain-language
verdict**: *"₹1 lakh would have become ₹2.3 lakh over 3 years — but you'd have sat through a scary −30%
drop most people panic-sell."* Plus a hard **"not financial advice / past performance ≠ future"**
disclaimer. **Honest base rate as a feature:** most reel strategies *lose to buy-and-hold* — saying so
clearly is the defensible moat (everyone else sells dreams; we sell a reality check). Save strategy + IR
to the user's library, which feeds the `StrategyOutcome` log (the data moat).

### B.3 The orchestrator (the part most designs under-build)
Stages 02→05 are a **loop**: extract → compile → backtest → evaluate; if faithfulness or significance
fails, send the IR back to 02 *with the failure as feedback* and re-run, with **bounded retries** (the
founder's "nothing loops infinitely"). Echoes QuantEvolve's evolutionary loop but kept constrained and
cheap. Reuse the existing SSE patterns (`/api/stress/stream`, `/api/forecast/stream`) for live progress.

### B.4 Cross-cutting
Async job queue (Redis/RQ — STT/backtest/Kronos are slow, Roadmap K2) · storage (IR store, results DB,
library, outcome log) · caching (reel DL, STT, market data, forecast paths) · security (validate IR;
sandbox only free-form code; no arbitrary `exec`) · compliance (ToS, data licensing, disclaimer) ·
observability (Sentry, LLM + GPU cost tracking) · infra split (FastAPI/Postgres/Redis on Railway;
**never GPU on Railway** — Kronos on Modal scale-to-zero).

---

## PART C — How to actually build it (sequenced)

1. **Stage 03 IR→params mapper + validator** (days). Lets you paste an IR JSON by hand → full backtest
   *today*. Lowest risk, instantly demoable, proves the bridge. New endpoint `POST /api/strategy/from-ir`.
2. **Stage 02 extraction on TEXT only** (caption + a pasted transcript), two-prompt + `REQUIRES_SPECIFICATION`
   + HITL editor. Defer audio/OCR. This is the research-grade part — build the human-review step first and
   treat extraction accuracy as a metric to improve, not a solved problem.
3. **Stage 00 triage** (one cheap classifier call) — wrap it around stage 02 the moment 02 works.
4. **Eval gates:** wire the **leakage guard** (force OOS split + post-cutoff check) and **faithfulness**
   diff into the existing eval, then the **bounded orchestrator loop** on top of the SSE patterns.
5. **Stage 06 novice verdict** — pure presentation over metrics already computed.
6. **Stage 01 full ingestion** — yt-dlp + Whisper + frame OCR + caching; lands with the async queue (K2).

**Order rationale:** ship the certain parts first (3 → eval gates → verdict), de-risk the fuzzy part (2)
behind a human review step, and only then automate the expensive front door (1, triage, full ingestion).

### Two honest cautions (carried forward)
- The backtesting half is mature; the **reel-understanding half is genuinely research-grade and will be
  wrong sometimes.** Design for that with the HITL review and faithfulness gate — don't pretend
  extraction is solved.
- **Be careful what you promise a beginner.** "This strategy works" is dangerous. "Here's how this would
  have performed historically, with these caveats" is honest and defensible — and, per the research, the
  only positioning that survives contact with reality.

---

## Sources
- model-trader (OSS): https://github.com/tonbistudio/model-trader
- "Turn Any YouTube Trading Video Into a Backtestable System (2 AI Prompts)": https://roguequant.substack.com/p/turn-any-youtube-trading-video-into
- "Democratizing Alpha: LLM-Driven Portfolio Construction… Public Financial Media" (ICAIF 2025): https://dl.acm.org/doi/10.1145/3768292.3770376
- "Profit Mirage: Revisiting Information Leakage in LLM-based Financial Agents": https://arxiv.org/pdf/2510.07920
- TradingAgents (multi-agent LLM trading): https://arxiv.org/html/2412.20138v1
- QuantAgent: https://arxiv.org/html/2509.09995v3 · QuantEvolve: https://arxiv.org/html/2510.18569v1
- Composer / Symphony (NL → structured strategy tree): https://www.composer.trade/ · https://help.composer.trade/article/65-how-does-composer-trade
- TrendSpider: https://trendspider.com/product/strategy-development-and-backtesting-tools/ · AlgoBuilder: https://algobuilder.com/ · TradrLab: https://tradrlab.com/ · LuxAlgo: https://www.luxalgo.com/backtesting/ · Capitalise.ai: https://capitalise.ai/
