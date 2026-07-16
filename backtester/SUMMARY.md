# TradeVed Backtester — Engineering & Quantitative Summary

> **Focus:** Quantitative finance design decisions, mathematical models, market microstructure
> details, and execution realism. Web/UI specifics are intentionally brief.

---

## 1. System Architecture at a Glance

```
Data Layer           Strategy Layer         Execution Layer        Analytics Layer
─────────────        ──────────────         ───────────────        ───────────────
YFinanceFetcher  →   GridStrategy       →   TradeSimulator     →   calculate_metrics()
BinanceFetcher       DCAStrategy            ├─ SimpleCostModel      ├─ Sharpe / Sortino
IndianMarketFetcher  PLAStrategy            └─ IndianCostModel      ├─ Drawdown
DataValidator                                   (STT/GST/stamp)     ├─ Calmar
                                                                     └─ Profit Factor
```

**Signal flow:** Each strategy produces a DataFrame with columns `[timestamp, close, signal, quantity]`
where `signal ∈ {BUY, SELL, HOLD}`. The simulator consumes this row-by-row, maintaining
a single long position with WACB (weighted-average cost basis).

**Supported universes:**
| Universe | Data Source | Cost Model | Notes |
|---|---|---|---|
| Crypto (BTC, ETH, …) | Binance REST / yfinance | SimpleCostModel (0.1%) | Tick-level possible |
| US / FX | yfinance | SimpleCostModel | auto_adjust=True |
| Indian Equity (NSE/BSE) | yfinance `.NS` / `.BO` | IndianCostModel | Weekends stripped |
| Indian F&O | yfinance (index/equity) | IndianCostModel | Lot-size enforced |
| Indian ETFs | yfinance `.NS` | IndianCostModel | Same as equity delivery |

---

## 2. Data Acquisition & Quality Pipeline

### 2.1 yfinance Conventions for Indian Markets

NSE-listed stocks use the `.NS` suffix; BSE uses `.BO`. Index symbols use `^`:

| Plain symbol | yfinance ticker | Notes |
|---|---|---|
| `RELIANCE` | `RELIANCE.NS` | NSE equity |
| `NIFTY50` | `^NSEI` | Nifty 50 index |
| `BANKNIFTY` | `^NSEBANK` | Bank Nifty index |
| `SENSEX` | `^BSESN` | BSE Sensex |
| `FINNIFTY` | `NIFTY_FIN_SERVICE.NS` | Fin Services index |
| `VIX` | `^INDIAVIX` | India VIX |

`auto_adjust=True` is always passed to yfinance — this adjusts historical prices for
corporate actions (splits, bonuses, rights issues) so strategy returns are not distorted
by price discontinuities.

### 2.2 Weekend & Holiday Filtering

NSE/BSE trading calendar = Monday–Friday, no weekends. `IndianMarketFetcher` strips any
rows where `timestamp.dt.dayofweek >= 5` after download:

```python
if interval == "1d":
    df = df[df["timestamp"].dt.dayofweek < 5]
```

Market holidays (Diwali Muhurat, Republic Day, etc.) appear as natural gaps and are
handled by the continuity checker with a 3× median-gap tolerance.

### 2.3 Data Validator (7 checks, quality score 0–100)

Every dataset passes through `DataValidator.validate()` before backtesting begins.
The backtest is **refused** if `quality_score < 50`.

| Check | Deduction | What it catches |
|---|---|---|
| Schema (missing cols) | −30 | CSV with wrong column names |
| Non-numeric types | −10 | String prices after bad parse |
| Range violations (price ≤ 0) | −10 | Delisted / suspended stocks |
| `high < low` violations | −10 | Data feed errors, bad splits |
| Duplicate timestamps | −5 | Duplicate candles from fetcher |
| Continuity gaps > 3× median | −2 to −20 | Missing sessions, partial data |
| Outlier returns (Z > 5σ) | −2 to −10 | Fat-finger / data errors |
| NaN / Inf in OHLCV | −5 per col | Forward-fill failures |

**Why Z = 5σ for outliers?** Indian markets can move 10–15% on results day. At Z=5,
a daily 3σ event (≈ ±3% for Nifty) never triggers a false positive. Only genuine
data artifacts (e.g., a post-split unadjusted price) get flagged.

**OHLCV forward-fill rule:** When `close` is NaN on a non-trading day that still appears
in the feed, we `ffill()` once — this preserves equity-curve continuity without
introducing phantom P&L. Volume is set to 0 on forward-filled candles.

---

## 3. Transaction Cost Model — Indian Markets

This is the most rigorous component of the system. All rates are as per **Budget 2024**,
effective **1 October 2024** (Finance Act 2024, SEBI circular NSCCL/CMPT/56264/2024).

### 3.1 Cost Components

For every trade leg (buy or sell), six components are computed:

```
Total Cost = Brokerage + STT + Exchange Charges + SEBI + GST + Stamp Duty
```

#### Securities Transaction Tax (STT)
Levied by the Government of India on every NSE/BSE transaction. It is the largest cost
component for equity delivery.

| Instrument | Buy | Sell |
|---|---|---|
| Equity Delivery | 0.1% of turnover | 0.1% of turnover |
| Equity Intraday | 0% | 0.025% of turnover |
| Futures | 0% | **0.02%** of turnover *(raised from 0.01% in Budget 2024)* |
| Options | 0% | **0.1%** of premium *(raised from 0.0625% in Budget 2024)* |

> **Budget 2024 impact:** Futures STT doubled (0.01% → 0.02%), Options STT increased
> 1.6× (0.0625% → 0.1%). This significantly raised the cost of high-frequency F&O
> strategies. The backtester uses the **new rates** to give realistic post-Oct-2024
> simulation.

#### Exchange Transaction Charges (NSE ETC)
Charged by NSE on total turnover. Revised rates from NSE circular:

| Segment | Rate |
|---|---|
| Equity (delivery + intraday) | 0.00297% (₹2.97 per lakh) |
| Futures | 0.00173% (₹1.73 per lakh) |
| Options | 0.03503% on premium (₹35.03 per lakh) |

#### SEBI Regulatory Fee
0.0001% (₹10 per crore) on all segments — minimal but included for completeness.

#### GST
18% charged on the taxable base of `(Brokerage + Exchange Charges + SEBI Charges)`.
GST is **not** levied on STT or Stamp Duty.

#### Stamp Duty
Levied by the State (Maharashtra for NSE) on the **buy side only**:

| Instrument | Buy |
|---|---|
| Equity Delivery | 0.015% |
| Equity Intraday | 0.003% |
| Futures | 0.003% |
| Options | 0.003% |

#### Brokerage
Three presets, matching real Indian retail brokers:

| Model | Formula | Brokers |
|---|---|---|
| `flat` ₹20/order | `min(₹20, 0.1% of turnover)` for delivery; `min(₹20, 2.5%)` for F&O | Zerodha, Groww, Upstox |
| `zero` | ₹0 | Angel One (free delivery) |
| `percentage` 0.5% | `turnover × 0.005` | Traditional full-service brokers |

### 3.2 Round-Trip Effective Cost Benchmarks

Verified against publicly available Zerodha brokerage calculator and NSEIndia:

| Segment | Round-trip cost (₹1L notional, ₹20 flat) | Real-world reference |
|---|---|---|
| Equity Delivery | ≈ 0.241% | Consistent with industry estimates |
| Equity Intraday | ≈ 0.054% | Per-side ≈ ₹27 on ₹1L |
| Futures | ≈ 0.046% | Per-side ≈ ₹23 on ₹1L |

### 3.3 Double-Counting Bug (Found & Fixed)

**The bug:** When a `BUY` order hit a partial-fill path (capital insufficient for full
quantity), `_calculate_cost()` was called twice — once provisionally and once for the
revised quantity — and both calls appended to `_cost_breakdowns`. This caused
`cost_breakdown.total` to be approximately **2× `total_fees_paid`**.

**Example observed:**
```
total_fees_paid      = ₹1,812.52   ← correct (deducted from cash)
cost_breakdown.total = ₹3,541.59   ← wrong  (double-counted)
```

**Fix (3-path tracking):**

```python
# Provisional estimate — NOT tracked
fee = self._calculate_cost(cost, "BUY", track=False)
total_cost = cost + fee

if total_cost > self._cash:
    # Partial fill — recalculate with affordable qty, track HERE
    quantity = affordable_qty
    fee      = self._calculate_cost(quantity * actual_price, "BUY", track=True)
else:
    # Normal fill — provisional IS the actual; track it now
    self._calculate_cost(cost, "BUY", track=True)
```

**Verified fix:**
```
total_fees_paid      = 320.0770
cost_breakdown.total = 320.0770  ✓  Match: True
```

---

## 4. Trade Simulator — Execution Realism

### 4.1 Slippage Model

Market-impact slippage is applied as a fixed percentage adjustment to the execution price:

```python
buy_price  = close_price × (1 + slippage_pct)   # pays more on entry
sell_price = close_price × (1 − slippage_pct)   # receives less on exit
```

Default: 0.1% (10 bps). This is conservative for liquid NSE large-caps (actual
market impact for retail size is typically 1–3 bps) but appropriate for crypto
and mid-cap stocks. Users can reduce it for index futures simulation.

**Why not model order-book slippage?** Without intraday order book data, a fixed
slippage is the honest choice — it avoids overfitting to a stylised L2 model that
doesn't reflect actual fills.

### 4.2 Weighted-Average Cost Basis (WACB)

When additional units are added to an existing position (pyramid/DCA), the average
entry price is recomputed as:

```
new_avg_price = (old_qty × old_avg + new_qty × new_price) / (old_qty + new_qty)
```

This is the same methodology used by Zerodha Console, Groww, and NSE/BSE P&L reports.
It matters for cascading strategies like PLA where multiple buy levels accumulate.

### 4.3 P&L Attribution

P&L for each closed trade is computed as:

```
gross_pnl = (exit_price - avg_entry_price) × quantity
net_pnl   = gross_pnl - sell_side_fee
pnl_pct   = net_pnl / (avg_entry_price × quantity)
```

Note: Buy-side fees are already deducted from `_cash` at entry time, so the sell-side
fee only needs to be deducted from proceeds. This gives correct net P&L without
double-deducting costs — consistent with how brokers report P&L.

### 4.4 Partial Fill Logic

If `total_cost > available_cash`, the simulator does not reject the trade. Instead it
back-solves for the maximum affordable quantity:

- **Indian costs (non-linear):** Uses a 97% cash utilisation heuristic
  (`affordable = cash × 0.97 / actual_price`) to leave headroom for non-linear
  STT/GST charges. No iterative solver needed.
- **Simple cost model (linear):** Exact back-solve:
  `quantity = cash / (actual_price × (1 + fee_pct))`

### 4.5 Open Position Closure

At the end of the dataset, any open position is automatically closed at the final
candle's close price. This prevents the equity curve from ending with a position
that has never realised its paper P&L — a common source of overstated returns in
naive backtesting systems.

### 4.6 F&O Lot-Size Enforcement

For futures and options, quantities are always **rounded down** to the nearest lot:

```python
if lot_size > 1 and qty > 0:
    qty = math.floor(qty / lot_size) * lot_size
    if qty == 0:
        skip_candle()   # not enough capital for even 1 lot
```

Lot sizes as of NSE FY2024-25 circular (selected):

| Symbol | Lot Size | Min Notional @ ~₹2500 index |
|---|---|---|
| NIFTY50 | 50 | ₹1,25,000 |
| BANKNIFTY | 15 | ₹7,20,000 (≈₹48K × 15) |
| FINNIFTY | 40 | — |
| RELIANCE | 250 | — |
| HDFCBANK | 550 | — |
| SBIN | 1500 | — |
| ITC | 3200 | — |

> This enforcement means a strategy that wants to buy 73 NIFTY contracts actually
> buys 50. If capital is below the minimum notional for even 1 lot, the candle is
> skipped — which is the correct real-world behaviour.

---

## 5. Trading Strategies

### 5.1 Grid Strategy

**Concept:** Divide a price range `[lower_bound, upper_bound]` into N levels. Buy every
time price drops through a level (accumulate on dips). Sell every time price rises
through a level (take profit on recovery). Captures range-bound / mean-reverting markets.

**Level construction:**
- `linear`: `levels = np.linspace(lower, upper, N)` — equal ₹ spacing
- `exponential`: `levels = np.exp(np.linspace(log(lower), log(upper), N))` — equal %
  spacing, mathematically correct for price series which are log-normally distributed

**Signal logic:**
```python
buy_levels  = [l for l in levels if prev_price > l >= curr_price]  # price dropped through
sell_levels = [l for l in levels if prev_price < l <= curr_price]  # price rose through
```

Multi-level crosses (price jumps through 2+ levels in one candle) are aggregated into a
single order with `quantity = qty_per_level × num_levels_crossed`.

**Position sizing:** Dollar-based preferred (`invest_per_level_usd`). Given a ₹500 per
level investment, `qty = ₹500 / price`. This ensures each grid level risks the same
rupee amount regardless of the price scale — unlike fixed-unit sizing, which risks more
₹ at higher price levels.

**Best fit for:** Range-bound index (Nifty within a channel), stable blue-chips like
HDFC Bank, crypto with mean-reverting daily ranges.

### 5.2 DCA Strategy (Dollar-Cost Averaging)

**Concept:** Buy a fixed-rupee amount at regular intervals regardless of price.
Averaging down over time reduces the sensitivity to entry timing. After a holding
period, exit all at once.

**Candle-agnostic scheduling:**
```python
median_hours = df["timestamp"].diff().median().total_seconds() / 3600
buy_every_n  = round(buy_interval_hours / median_hours)
```
Works identically on daily, hourly, or 5-minute candles.

**Exit options:**
- `time`: Sell all after `hold_days` regardless of P&L
- `profit`: Scan forward within the hold period; exit the first candle where
  `(price − avg_entry) / avg_entry × 100 ≥ profit_target_pct`

**WACB tracking inside strategy:** The strategy pre-computes its own running `avg_entry`
for profit-target scanning. This is separate from the simulator's WACB (which handles
slippage), so there is a small difference — but it only affects the exit trigger, not
the reported P&L (which comes entirely from the simulator).

**Best fit for:** Long-term accumulation of quality stocks (HDFC Bank, Infosys, TCS),
weekly SIP simulation, stress-testing holding-period sensitivity.

### 5.3 PLA Strategy (Price-Level Averaging with EMA Crossover)

**Concept:** Use EMA crossover to time the initial entry, then average down into the
position using cascading buy levels if price pulls back. Exit on death-cross, take-profit,
or stop-loss.

**Entry trigger:** Golden cross — fast EMA crosses above slow EMA.
```python
if prev_diff <= 0 and curr_diff > 0:
    entry_price = current_price
    # Level 0 buy
```

**Cascading entries (averaging down):**
```
Level 0: entry at crossover price
Level 1: buy if price drops -1% from entry
Level 2: buy if price drops -2.5% from entry
Level 3: buy if price drops -4% from entry
```
Each level adds quantity and lowers the WACB. If the price never drops that far, higher
levels are never triggered — unlike naive DCA, which buys regardless of drawdown.

**Dollar-based cascading weights:**
```
invest_per_level_usd = [₹300, ₹300, ₹600, ₹900]
```
Deeper dips get larger allocations (bottom-loading), which reduces break-even faster.

**EMA parameterisation:**
- Default: fast=12, slow=26 (standard MACD parameters — well-established in technical analysis)
- The EMA is computed as: `series.ewm(span=period, adjust=False).mean()`
- `adjust=False` uses the recursive formula `EMA_t = α × P_t + (1−α) × EMA_{t−1}`,
  which matches how trading platforms (TradingView, Kite) compute EMAs.
  Using `adjust=True` would give different values during the warmup period.

**Exit logic:**
- `crossover`: Death cross (fast EMA crosses below slow) — exits entire position
- `take_profit`: Monitored on every candle relative to WACB
- `stop_loss`: Monitored on every candle relative to WACB

**Edge case — simultaneous entry + exit on same candle:** If a candle triggers both a
cascading buy (price dip) and a death-cross, the death-cross (exit) takes priority and
overwrites the signal. This is correct behaviour — you don't want to average down into
a position you're about to exit.

**Best fit for:** Trending markets with intermittent pullbacks — midcap growth stocks,
Nifty IT during bull phases. The EMA timing helps avoid entering into pure downtrends.

---

## 6. Performance Metrics Engine

All metrics use `TRADING_DAYS_PER_YEAR = 252` (NSE / NYSE convention).

### 6.1 Annualised Return (CAGR)

```python
ann_return = (eq[-1] / eq[0]) ** (252 / n_days) - 1
```

`n_days` is derived from the equity curve length divided by candles-per-day (CPD).
CPD is inferred from the median timestamp difference — so a 1-hour backtest over
100 candles correctly annualises as 100/8 ≈ 12.5 trading days, not 100 days.

### 6.2 Sharpe Ratio

```python
candle_returns = np.diff(equity_curve) / equity_curve[:-1]
sharpe = mean(returns) / std(returns) × sqrt(252 × cpd)
```

- Risk-free rate = 0 (excess return Sharpe). For Indian markets, the RBI repo rate
  could be subtracted, but for strategy comparison, rf=0 is consistent.
- Annualisation factor `√(252 × cpd)` correctly scales hourly sharpe to annual.
  Daily Sharpe uses `√252`, 1-hour uses `√(252 × 6.5)` for US hours or `√(252 × 6.25)`
  for NSE (9:15–15:30 = 6.25 hours). The CPD inference handles this automatically.

### 6.3 Sortino Ratio

```python
downside_returns = returns[returns < 0]
sortino = mean(returns) / std(downside_returns) × sqrt(252 × cpd)
```

Uses only negative returns in the denominator — penalises downside volatility only,
not upside. More appropriate than Sharpe for strategies with positive skew (like DCA
which accumulates and sells at profit targets).

### 6.4 Maximum Drawdown

```python
running_max = np.maximum.accumulate(equity_curve)
drawdowns   = (equity_curve - running_max) / running_max
max_dd      = min(drawdowns)
```

Computed on the **equity curve** (mark-to-market), not just at trade close prices.
This means an open position that drops 20% intraday is reflected in the max drawdown
even if the trade is eventually closed at breakeven — critical for accurate risk reporting.

**Max drawdown duration:** Counts consecutive candles below the previous peak, not calendar
days. For daily data these are the same; for intraday data this gives a more granular
picture of how long capital is underwater.

### 6.5 Calmar Ratio

```
Calmar = Annualised Return / |Max Drawdown|
```

Useful for comparing strategies with different drawdown profiles. A Grid strategy on
Nifty might have lower absolute returns than an aggressive PLA, but if its drawdown is
also proportionally smaller, the Calmar normalises the comparison.

### 6.6 Profit Factor

```
Profit Factor = Gross Profit / Gross Loss
```

Infinity when there are no losing trades (handled: `if gross_loss < 1e-10: return inf`).
Displayed as `∞` in the UI. PF > 1.5 is considered healthy; PF < 1.0 means the strategy
is losing money in aggregate.

### 6.7 Volatility (Annualised)

```python
volatility = std(candle_returns) × sqrt(252 × cpd)
```

Annualised standard deviation of returns. For Indian equity, typical Nifty 50 annualised
volatility is 14–18%. Intraday strategies on individual stocks can reach 40–60%.

---

## 7. Indian Market Asset Registry

### 7.1 Coverage

| Category | Count | Notes |
|---|---|---|
| NSE Indices | 14 | NIFTY50, BANKNIFTY, SENSEX, FINNIFTY, VIX, etc. |
| Nifty 50 Stocks | 50 | Full current constituent list |
| Popular NSE Mid/Small | 60+ | Zomato, IRCTC, HAL, DMart, etc. |
| NSE ETFs | 17 | NIFTYBEES, GOLDBEES, BANKBEES, LIQUIDBEES, etc. |
| F&O Lot Sizes | 60+ | Index + all equity F&O names |

### 7.2 F&O Lot Size Source

NSE revises lot sizes quarterly to keep minimum contract value near ₹5–10 lakh
(SEBI mandate for retail protection). Lot sizes in this project are from:
`NSE circular NSCCL/CMPT/56264/2024` (FY2024-25 revision).

> ⚠️ **Production note:** Lot sizes must be re-verified quarterly from
> `nseindia.com/market-data/futures-and-options-lot-sizes` before live use,
> as they change every quarter.

---

## 8. Known Limitations & Future Work

### What this backtester does correctly
- ✅ Realistic Indian statutory transaction costs (Budget 2024 rates)
- ✅ WACB position tracking, consistent with NSE/broker P&L reports
- ✅ Lot-size enforcement (cannot trade fractional lots in F&O)
- ✅ Slippage on both entry and exit
- ✅ Open position closed at end of data (no phantom profits)
- ✅ Data quality gating (rejects bad feeds before simulation)
- ✅ Correct annualisation for both daily and intraday data
- ✅ Mark-to-market equity curve (drawdown reflects open positions)
- ✅ Walk-forward validation (rolling out-of-sample windows with best-param selection)
- ✅ Stress testing with 13 scenario presets and Monte Carlo (SSE streaming)

### What is simplified / not modelled
- ❌ **Options greeks / non-linear payoff:** Treats options as linear instruments.
  Real options backtesting requires modelling delta, theta decay, IV surface.
- ❌ **Rolling expiry:** F&O contracts expire monthly/weekly. This system does not
  model roll costs or basis convergence. It should be treated as a proxy simulation,
  not a precise F&O backtest.
- ❌ **Impact of own orders on price:** Assumed to be negligible (retail size).
  For large positions in mid-caps, actual market impact will be higher.
- ❌ **Intraday margin & MTM settlement:** NSE intraday and F&O involve margin calls
  and daily MTM settlement. This is not modelled — the simulator is equity-curve based.
- ❌ **Circuit breakers & price bands:** NSE applies 5%/10%/20% daily price bands on
  most stocks. A violent gap-down signal that would be circuit-limited is not caught.
- ❌ **Short selling:** Only LONG positions are supported. Shorting NSE equity requires
  intraday closing or F&O, which adds complexity beyond current scope.
- ❌ **Brokerage caps for large trades:** For very large trades, brokerage is capped at
  2.5% of turnover (SEBI rule), not just ₹20. The current model applies this cap only
  for intraday/F&O; delivery brokerage is already bounded at `min(₹20, 0.1%)`.

### Prioritised next improvements (quant)
1. **Options payoff engine** — model call/put at expiry, IV surface via Black-Scholes
2. **Multi-leg positions** — allow simultaneous long + hedge (e.g., covered call)
3. **Benchmark comparison** — plot strategy equity vs Nifty 50 buy-and-hold
4. **Stress + walk-forward** — apply shock scenarios to each out-of-sample window

---

## 9. Verified Test Results

### RELIANCE.NS Delivery (2023, DCA strategy)
```
Data:         246 trading days (no weekends, correct NSE calendar)
Return:       +17.34%
Sharpe:       1.254
Max Drawdown: -14.82%
Cost model:   Equity Delivery, Zerodha ₹20 flat
```

### Cost Model Verification (₹2.5L turnover, Equity Delivery, ₹20 flat)
```
Brokerage:        ₹20.00   (min of ₹20 and 0.1% of ₹2.5L)
STT (buy+sell):   ₹500.00  (0.1% × ₹2.5L × 2 sides)
Exchange charges: ₹14.85   (0.00297% × 2)
SEBI:             ₹0.50
GST:              ₹6.21    (18% on brok+ETC+SEBI)
Stamp Duty:       ₹37.50   (0.015% on buy side)
─────────────────────────────
Total:            ₹579.06  ≈ 0.241% round-trip ✓
```

### Double-Count Fix Verification
```
total_fees_paid      = ₹320.0770
cost_breakdown.total = ₹320.0770  ← exact match after fix
```

---

## 10. Stress Tester — Design & Monte Carlo

### 10.1 Architecture

The stress tester runs the **same simulator pipeline** (strategy → signals → TradeSimulator → metrics)
on a synthetically perturbed copy of the historical OHLCV data, then repeats N times with
randomised shock timing and intensity.

```
Real OHLCV  →  apply_stress(scenario, severity, seed)  →  Perturbed OHLCV
                                                               ↓
                                             _single_backtest(strategy, capital)
                                                               ↓
                                           Stressed metrics (return, Sharpe, DD, …)
```

`apply_stress()` is a **pure function** — it deep-copies the input DataFrame and never mutates it.
Each Monte Carlo run gets its own `seed` so results are reproducible.

### 10.2 Scenario Presets (13 total)

| Key | Shock | Duration | persist | Description |
|-----|-------|----------|---------|-------------|
| `gfc_2008` | −37% | 252d | Yes | 2008-style crash with price bounces |
| `covid_crash` | −34% + +60% recovery | 30d+45d | Yes | Sharp V-shape crash |
| `flash_crash_2010` | −9% | 1 candle | No | Single-candle intraday crash |
| `luna_collapse` | −95% | 7d | Yes | Permanent near-zero collapse |
| `slow_bleed` | −40% | 180d | Yes | 6-month bear drift |
| `pump_dump` | +50% then −60% | 5d+3d | Yes (dump) | Manipulation cycle |
| `vol_spike` | 3× candle ranges | 30d | No | Volatility spike only, trend unchanged |
| `whipsaw_chop` | ±5% mean-reverting | 60d | No | High-frequency direction changes |
| `gap_risk` | 10 random ±3–8% gaps | — | No | Overnight gap shocks |
| `range_bound` | ±2% mean-reverting | 90d | No | Price stuck in tight range |
| `trend_reversal` | +30% then −25% | 60d+20d | Yes (reversal) | Exhaustion + reversal |
| `liquidity_drought` | 5× slippage, 3× spread | 10d | No | Market illiquidity |
| `outlier_injection` | 5 random ±20–30% candles | — | No | Fat-tail outlier events |

**`persist=True`:** The post-shock price level is carried forward (no snap-back). Critical for
scenarios where the crash is permanent (luna_collapse, slow_bleed, gfc_2008).
Without it, the strategy would trivially profit from buying the crash and selling the recovery.

### 10.3 Monte Carlo Design

Each of N runs uses a **different shock start position** (uniform within first 60% of data)
AND a **different severity multiplier** `run_severity = severity × uniform(0.75, 1.25)`.

Two sources of variation:
- **Timing variation** (when the shock starts relative to the strategy's entry points)
- **Magnitude variation** (how deep the shock actually goes)

Without magnitude variation, all N runs share the same shock intensity → paths nearly
identical → no spread in the distribution → misleading "best case ≈ worst case" output.

### 10.4 SSE Streaming Endpoint

`POST /api/stress/stream` is an async FastAPI generator that yields server-sent events:

```
{type: "baseline", metrics: {...}, total: N}     ← computed first, no perturbation
{type: "run", run_num: k, total: N, metrics: {...}, equity: [...]}  ← one per MC run
{type: "complete", result: {...}}                 ← same shape as /api/stress/run
{type: "error", message: "..."}                  ← on any failure
```

Each blocking call (`apply_stress`, `_single_backtest`) runs via `asyncio.to_thread` so
the async generator can flush events between iterations — critical for real-time UI updates.

The frontend uses `fetch` + `ReadableStream` (not `EventSource`) to consume the SSE stream.
`EventSource` doesn't support POST bodies; `fetch` streaming does.

### 10.5 Walk-Forward Validation

`backtesting/engine/validation.py` provides `WalkForwardValidator` which:
1. Splits the date range into rolling windows of `wf_window` months
2. On each train window: grid-searches over strategy param variations, picks best Sharpe
3. Tests the winning params on the subsequent `wf_step`-month out-of-sample window
4. Returns per-window: train Sharpe, test return, test Sharpe, test drawdown

The API returns the `validation` key with `{mode, window, step, num_windows, windows: [...]}`.
363 windows were computed for a 3-year BTC dataset with 6-month train / 3-month step.
