"""
Comprehensive test suite — run with: python test_all.py
Tests: data fetching, strategies, simulator, cost model, lot sizes, metrics
"""
import sys, traceback, math
from datetime import datetime, timedelta
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from data.fetcher import DataFetcher
from data.validator import DataValidator
from data.indian_assets import get_lot_size, is_indian
from engine.simulator import TradeSimulator
from engine.metrics import calculate_metrics
from engine.cost_models import IndianCostModel
from strategies.grid import GridStrategy
from strategies.dca  import DCAStrategy
from strategies.pla  import PLAStrategy

fetcher   = DataFetcher()
validator = DataValidator()

results = []

def run_test(name, fn):
    try:
        fn()
        results.append(("PASS", name))
        print(f"[PASS] {name}")
    except Exception as e:
        results.append(("FAIL", name, str(e)))
        print(f"[FAIL] {name}")
        traceback.print_exc()
        print()

# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCH
# ─────────────────────────────────────────────────────────────────────────────

def test_fetch_crypto():
    df = fetcher.fetch("BTC/USDT", datetime(2024,1,1), datetime(2024,3,31), "binance", "1d")
    assert len(df) > 50
    assert list(df.columns[:6]) == ["timestamp","open","high","low","close","volume"]
    print(f"  BTC/USDT binance: {len(df)} candles, close [{df.close.min():.0f},{df.close.max():.0f}]")
run_test("Crypto BTC/USDT from Binance", test_fetch_crypto)

def test_fetch_nse_equity():
    df = fetcher.fetch("RELIANCE", datetime(2024,1,1), datetime(2024,3,31), "nse", "1d")
    assert len(df) > 40
    assert (df["timestamp"].dt.dayofweek < 5).all(), "Weekend rows found!"
    assert (df["close"] > 0).all()
    print(f"  RELIANCE NSE: {len(df)} days, close [{df.close.min():.0f},{df.close.max():.0f}]")
run_test("NSE Equity RELIANCE", test_fetch_nse_equity)

def test_fetch_nifty50():
    df = fetcher.fetch("NIFTY50", datetime(2024,1,1), datetime(2024,3,31), "nse", "1d")
    assert len(df) > 40
    print(f"  NIFTY50: {len(df)} days, range [{df.close.min():.0f},{df.close.max():.0f}]")
run_test("NSE Index NIFTY50", test_fetch_nifty50)

def test_fetch_banknifty():
    df = fetcher.fetch("BANKNIFTY", datetime(2024,1,1), datetime(2024,3,31), "nse", "1d")
    assert len(df) > 40
    print(f"  BANKNIFTY: {len(df)} days, range [{df.close.min():.0f},{df.close.max():.0f}]")
run_test("NSE Index BANKNIFTY", test_fetch_banknifty)

def test_fetch_etf():
    df = fetcher.fetch("NIFTYBEES", datetime(2024,1,1), datetime(2024,3,31), "nse", "1d")
    assert len(df) > 40
    print(f"  NIFTYBEES ETF: {len(df)} days, price ~{df.close.mean():.2f}")
run_test("NSE ETF NIFTYBEES", test_fetch_etf)

def test_fetch_bse():
    df = fetcher.fetch("TCS", datetime(2024,1,1), datetime(2024,3,31), "bse", "1d")
    assert len(df) > 40
    print(f"  TCS BSE: {len(df)} days, price ~{df.close.mean():.0f}")
run_test("BSE Equity TCS", test_fetch_bse)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== STRATEGY SIGNAL TESTS ===")

def test_grid_nifty():
    df = fetcher.fetch("NIFTY50", datetime(2024,1,1), datetime(2024,6,30), "nse", "1d")
    strat = GridStrategy(lower_bound=20000, upper_bound=25000, num_levels=5, invest_per_level_usd=10000)
    sig = strat.generate_signals(df)
    buys  = (sig["signal"]=="BUY").sum()
    sells = (sig["signal"]=="SELL").sum()
    print(f"  NIFTY50 Grid: {buys} BUYs, {sells} SELLs over {len(df)} candles")
    assert buys + sells > 0, "No signals generated!"
run_test("Grid signals NIFTY50", test_grid_nifty)

def test_dca_reliance():
    df = fetcher.fetch("RELIANCE", datetime(2024,1,1), datetime(2024,6,30), "nse", "1d")
    strat = DCAStrategy(buy_interval_hours=24, invest_per_buy_usd=5000, hold_days=30)
    sig = strat.generate_signals(df)
    buys  = (sig["signal"]=="BUY").sum()
    sells = (sig["signal"]=="SELL").sum()
    print(f"  RELIANCE DCA: {buys} BUYs, {sells} SELLs over {len(df)} candles")
    assert buys > 0 and sells > 0
run_test("DCA signals RELIANCE", test_dca_reliance)

def test_pla_tcs():
    df = fetcher.fetch("TCS", datetime(2023,1,1), datetime(2023,12,31), "nse", "1d")
    strat = PLAStrategy(fast_ema=12, slow_ema=26,
                        invest_per_level_usd=[5000,5000,10000,15000])
    sig = strat.generate_signals(df)
    buys  = (sig["signal"]=="BUY").sum()
    sells = (sig["signal"]=="SELL").sum()
    print(f"  TCS PLA: {buys} BUYs, {sells} SELLs")
run_test("PLA signals TCS", test_pla_tcs)

# ─────────────────────────────────────────────────────────────────────────────
# SIMULATOR — EQUITY
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== SIMULATOR: EQUITY ===")

def test_equity_delivery():
    df = fetcher.fetch("HDFCBANK", datetime(2023,6,1), datetime(2023,12,31), "nse", "1d")
    strat = DCAStrategy(buy_interval_hours=24, invest_per_buy_usd=10000, hold_days=60)
    sig = strat.generate_signals(df)
    sim = TradeSimulator("HDFCBANK", capital=200000,
                         use_indian_costs=True, market_type="equity_delivery",
                         brokerage_model="flat", brokerage_flat=20)
    res = sim.run(sig)
    fees = res["total_fees_paid"]
    cb   = res["cost_breakdown"].get("total", 0)
    print(f"  HDFCBANK delivery: {len(res['trades'])} trades, fees={fees:.2f}, breakdown={cb:.2f}")
    assert abs(fees - cb) < 0.02, f"Fee mismatch! total_fees={fees} vs breakdown={cb}"
run_test("Equity Delivery HDFCBANK DCA", test_equity_delivery)

def test_equity_intraday():
    df = fetcher.fetch("INFY", datetime(2024,1,1), datetime(2024,3,31), "nse", "1d")
    lo = float(df["close"].min()) * 0.9
    hi = float(df["close"].max()) * 1.1
    strat = GridStrategy(lower_bound=lo, upper_bound=hi, num_levels=6, invest_per_level_usd=5000)
    sig = strat.generate_signals(df)
    sim = TradeSimulator("INFY", capital=100000,
                         use_indian_costs=True, market_type="equity_intraday",
                         brokerage_model="flat", brokerage_flat=20)
    res = sim.run(sig)
    fees = res["total_fees_paid"]
    cb   = res["cost_breakdown"].get("total", 0)
    print(f"  INFY intraday Grid: {len(res['trades'])} trades, fees={fees:.2f}, breakdown={cb:.2f}")
    assert abs(fees - cb) < 0.02, f"Fee mismatch!"
run_test("Equity Intraday INFY Grid", test_equity_intraday)

# ─────────────────────────────────────────────────────────────────────────────
# SIMULATOR — FUTURES
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== SIMULATOR: FUTURES (PRIMARY CONCERN) ===")

def test_futures_nifty_dca():
    df = fetcher.fetch("NIFTY50", datetime(2024,1,1), datetime(2024,6,30), "nse", "1d")
    lot_sz = get_lot_size("NIFTY50")
    # 1 lot NIFTY50 @ ~22000 = 50 * 22000 = 11,00,000 notional
    # invest_per_buy must be >= 1 lot notional. Use 1,500,000 to comfortably cover 1 lot + costs
    approx_price = float(df["close"].median())
    min_invest   = lot_sz * approx_price * 1.1  # 10% buffer for slippage/fees
    print(f"  NIFTY50 lot_size={lot_sz}, approx_price={approx_price:.0f}, min_invest={min_invest:,.0f}")
    strat = DCAStrategy(buy_interval_hours=24*5, invest_per_buy_usd=min_invest, hold_days=30)
    sig = strat.generate_signals(df)
    sim = TradeSimulator("NIFTY50", capital=10_000_000,
                         use_indian_costs=True, market_type="futures",
                         brokerage_model="flat", brokerage_flat=20, lot_size=lot_sz)
    res = sim.run(sig)
    fees = res["total_fees_paid"]
    cb   = res["cost_breakdown"].get("total", 0)
    skips = res["lot_size_skips"]
    print(f"  NIFTY50 futures DCA: {len(res['trades'])} trades, fees={fees:.2f}, breakdown={cb:.2f}, lot_skips={skips}")
    assert len(res["trades"]) > 0, "Expected trades with sufficient invest amount!"
    assert abs(fees - cb) < 0.02, f"Fee mismatch! fees={fees} breakdown={cb}"
    assert skips == 0, f"Expected 0 lot-size skips, got {skips}"
    # Verify lot rounding: all quantities must be multiples of lot_size
    for t in res["trades"]:
        qty = t["quantity"]
        assert qty % lot_sz < 0.001 or qty < lot_sz, f"Lot violation: qty={qty}"
    m = calculate_metrics(res["trades"], res["equity_curve"], res["timestamps"], 10_000_000)
    print(f"  NIFTY50 futures metrics: return={m['total_return_pct']:.2f}% sharpe={m['sharpe_ratio']:.3f}")
run_test("Futures NIFTY50 DCA", test_futures_nifty_dca)

def test_futures_banknifty_grid():
    df = fetcher.fetch("BANKNIFTY", datetime(2024,1,1), datetime(2024,6,30), "nse", "1d")
    lot_sz = get_lot_size("BANKNIFTY")
    # 1 lot BANKNIFTY @ ~46000 = 15 * 46000 = 690,000 notional
    approx_price = float(df["close"].median())
    min_invest   = lot_sz * approx_price * 1.1
    print(f"  BANKNIFTY lot_size={lot_sz}, approx_price={approx_price:.0f}, min_invest={min_invest:,.0f}")
    lo = float(df["close"].min()) * 0.92
    hi = float(df["close"].max()) * 1.08
    strat = GridStrategy(lower_bound=lo, upper_bound=hi, num_levels=6, invest_per_level_usd=min_invest)
    sig = strat.generate_signals(df)
    sim = TradeSimulator("BANKNIFTY", capital=10_000_000,
                         use_indian_costs=True, market_type="futures",
                         brokerage_model="flat", brokerage_flat=20, lot_size=lot_sz)
    res = sim.run(sig)
    fees = res["total_fees_paid"]
    cb   = res["cost_breakdown"].get("total", 0)
    skips = res["lot_size_skips"]
    print(f"  BANKNIFTY futures Grid: {len(res['trades'])} trades, fees={fees:.2f}, breakdown={cb:.2f}, lot_skips={skips}")
    assert len(res["trades"]) > 0, "Expected trades with sufficient invest!"
    assert abs(fees - cb) < 0.02, f"Fee mismatch!"
run_test("Futures BANKNIFTY Grid", test_futures_banknifty_grid)

def test_futures_reliance_pla():
    df = fetcher.fetch("RELIANCE", datetime(2023,1,1), datetime(2023,12,31), "nse", "1d")
    lot_sz = get_lot_size("RELIANCE")
    # 1 lot RELIANCE @ ~2500 = 250 * 2500 = 625,000 notional
    approx_price = float(df["close"].median())
    min_invest   = lot_sz * approx_price * 1.1
    print(f"  RELIANCE lot_size={lot_sz}, approx_price={approx_price:.0f}, min_invest={min_invest:,.0f}")
    strat = PLAStrategy(fast_ema=12, slow_ema=26,
                        invest_per_level_usd=[min_invest, min_invest, min_invest*2, min_invest*3])
    sig = strat.generate_signals(df)
    sim = TradeSimulator("RELIANCE", capital=10_000_000,
                         use_indian_costs=True, market_type="futures",
                         brokerage_model="flat", brokerage_flat=20, lot_size=lot_sz)
    res = sim.run(sig)
    fees = res["total_fees_paid"]
    cb   = res["cost_breakdown"].get("total", 0)
    skips = res["lot_size_skips"]
    print(f"  RELIANCE futures PLA: {len(res['trades'])} trades, fees={fees:.2f}, breakdown={cb:.2f}, lot_skips={skips}")
    assert abs(fees - cb) < 0.02, f"Fee mismatch!"
run_test("Futures RELIANCE PLA", test_futures_reliance_pla)

def test_futures_insufficient_capital():
    """If capital can't afford even 1 lot, simulator should handle gracefully."""
    rows = [{"timestamp": datetime(2024,1,1)+timedelta(days=i),
             "close": 22500.0, "signal": "BUY" if i==1 else "HOLD",
             "quantity": 50.0} for i in range(10)]
    df = pd.DataFrame(rows)
    sim = TradeSimulator("NIFTY50", capital=5000,   # only 5k — cannot buy 1 lot at 22500
                         use_indian_costs=True, market_type="futures",
                         brokerage_model="flat", brokerage_flat=20, lot_size=50)
    res = sim.run(df)
    assert res["total_fees_paid"] == 0.0, "Fees charged despite no trade possible"
    assert len(res["trades"]) == 0, "Trades opened despite insufficient capital"
    print(f"  Correctly handled insufficient capital: 0 trades, 0 fees")
run_test("Futures insufficient capital (graceful skip)", test_futures_insufficient_capital)

def test_futures_lot_size_skip_tracking():
    """Simulator should count lot-size-skipped BUY signals."""
    # generate qty=10 for NIFTY50 with lot_size=50 → ALL 3 BUY signals should be skipped
    rows = [{"timestamp": datetime(2024,1,1)+timedelta(days=i),
             "close": 22000.0,
             "signal": "BUY" if i in [1,3,5] else "HOLD",
             "quantity": 10.0}   # 10 < lot_size=50 → will be rounded to 0
            for i in range(10)]
    df = pd.DataFrame(rows)
    sim = TradeSimulator("NIFTY50", capital=5_000_000, lot_size=50,
                         use_indian_costs=True, market_type="futures")
    res = sim.run(df)
    assert res["lot_size_skips"] == 3, f"Expected 3 lot-size skips, got {res['lot_size_skips']}"
    assert len(res["trades"]) == 0
    print(f"  lot_size_skips={res['lot_size_skips']} (expected 3) ✓")
run_test("Simulator tracks lot_size_skips correctly", test_futures_lot_size_skip_tracking)

# ─────────────────────────────────────────────────────────────────────────────
# LOT SIZE TESTS
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== LOT SIZE TESTS ===")

def test_lot_sizes():
    cases = [
        ("NIFTY50",50), ("NIFTY",50), ("BANKNIFTY",15),
        ("RELIANCE",250), ("HDFCBANK",550), ("TCS",150),
        ("SBIN",1500), ("ITC",3200), ("INFY",300),
        ("NIFTYBEES",1), ("BTC/USDT",1),
    ]
    for sym, expected in cases:
        got = get_lot_size(sym)
        assert got == expected, f"{sym}: expected {expected}, got {got}"
        print(f"  {sym:15s} lot_size={got}")
run_test("Lot sizes all correct", test_lot_sizes)

def test_lot_rounding():
    """73 units with lot_size=50 should become 50."""
    rows = [{"timestamp": datetime(2024,1,1)+timedelta(days=i),
             "close": 22000.0,
             "signal": "BUY" if i==1 else ("SELL" if i==10 else "HOLD"),
             "quantity": 73.0} for i in range(15)]
    df = pd.DataFrame(rows)
    sim = TradeSimulator("NIFTY50", capital=5000000, lot_size=50,
                         use_indian_costs=True, market_type="futures")
    res = sim.run(df)
    for t in res["trades"]:
        assert t["quantity"] % 50 < 0.001, f"Lot violation: qty={t['quantity']}"
        print(f"  Trade qty={t['quantity']} (correct multiple of 50)")
run_test("Lot rounding 73->50", test_lot_rounding)

def test_lot_rounding_edge_zero():
    """Quantity less than 1 lot should produce 0 and be skipped."""
    rows = [{"timestamp": datetime(2024,1,1)+timedelta(days=i),
             "close": 22000.0,
             "signal": "BUY" if i==1 else "HOLD",
             "quantity": 30.0} for i in range(5)]  # 30 < lot_size=50
    df = pd.DataFrame(rows)
    sim = TradeSimulator("NIFTY50", capital=5000000, lot_size=50,
                         use_indian_costs=True, market_type="futures")
    res = sim.run(df)
    assert len(res["trades"]) == 0, f"Should be 0 trades when qty<lot_size, got {len(res['trades'])}"
    print(f"  qty=30 < lot_size=50 correctly skipped: 0 trades")
run_test("Lot rounding qty<lot gives 0 (skip)", test_lot_rounding_edge_zero)

# ─────────────────────────────────────────────────────────────────────────────
# COST MODEL VALIDATION
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== COST MODEL VALIDATION ===")

def test_cost_futures_stt():
    calc = IndianCostModel()
    turnover = 1_100_000  # 1 lot NIFTY @ 22000 * 50
    buy  = calc.calculate(turnover, "BUY",  "futures", "flat", 20)
    sell = calc.calculate(turnover, "SELL", "futures", "flat", 20)
    # Futures: STT 0% BUY, 0.02% SELL
    assert buy.stt == 0.0,  f"Futures BUY STT should=0, got {buy.stt}"
    assert abs(sell.stt - turnover*0.0002) < 0.01, f"Futures SELL STT wrong: {sell.stt}"
    assert buy.stamp_duty > 0,  "Futures BUY stamp duty missing"
    assert sell.stamp_duty == 0, "Futures SELL should have no stamp duty"
    print(f"  Futures: buy.stt={buy.stt}, sell.stt={sell.stt:.2f} (expected {turnover*0.0002:.2f})")
    print(f"  buy.stamp={buy.stamp_duty:.2f}, sell.stamp={sell.stamp_duty:.2f}")
run_test("Futures STT correct (0 BUY, 0.02% SELL)", test_cost_futures_stt)

def test_cost_intraday_stt():
    calc = IndianCostModel()
    turnover = 500_000
    buy  = calc.calculate(turnover, "BUY",  "equity_intraday", "flat", 20)
    sell = calc.calculate(turnover, "SELL", "equity_intraday", "flat", 20)
    assert buy.stt == 0.0,  f"Intraday BUY STT should=0, got {buy.stt}"
    assert abs(sell.stt - turnover*0.00025) < 0.01, f"Intraday SELL STT wrong: {sell.stt}"
    print(f"  Intraday: buy.stt={buy.stt}, sell.stt={sell.stt:.2f}")
run_test("Intraday STT correct (0 BUY, 0.025% SELL)", test_cost_intraday_stt)

def test_cost_delivery_stt():
    calc = IndianCostModel()
    turnover = 500_000
    buy  = calc.calculate(turnover, "BUY",  "equity_delivery", "flat", 20)
    sell = calc.calculate(turnover, "SELL", "equity_delivery", "flat", 20)
    assert abs(buy.stt  - turnover*0.001) < 0.01, f"Delivery BUY STT wrong: {buy.stt}"
    assert abs(sell.stt - turnover*0.001) < 0.01, f"Delivery SELL STT wrong: {sell.stt}"
    print(f"  Delivery: buy.stt={buy.stt:.2f}, sell.stt={sell.stt:.2f}")
run_test("Delivery STT correct (0.1% both sides)", test_cost_delivery_stt)

def test_cost_options_stt():
    calc = IndianCostModel()
    premium = 100_000
    sell = calc.calculate(premium, "SELL", "options", "flat", 20)
    assert abs(sell.stt - premium*0.001) < 0.01, f"Options SELL STT wrong: {sell.stt}"
    print(f"  Options sell STT={sell.stt:.2f} (expected {premium*0.001:.2f})")
run_test("Options STT correct (0.1% SELL)", test_cost_options_stt)

def test_cost_gst_base():
    """GST should be 18% of (brokerage + exchange_charges + sebi_charges) only."""
    calc = IndianCostModel()
    cb = calc.calculate(100_000, "BUY", "equity_delivery", "flat", 20)
    expected_gst = (cb.brokerage + cb.exchange_charges + cb.sebi_charges) * 0.18
    assert abs(cb.gst - expected_gst) < 0.001, f"GST wrong: {cb.gst} vs expected {expected_gst}"
    print(f"  GST base check: gst={cb.gst:.4f} = 18% of ({cb.brokerage:.2f}+{cb.exchange_charges:.4f}+{cb.sebi_charges:.4f})")
run_test("GST computed on correct base", test_cost_gst_base)

def test_cost_total_equals_sum():
    """total should equal sum of all components."""
    calc = IndianCostModel()
    for mtype in ["equity_delivery","equity_intraday","futures","options"]:
        for side in ["BUY","SELL"]:
            cb = calc.calculate(200_000, side, mtype, "flat", 20)
            expected = cb.brokerage + cb.stt + cb.exchange_charges + cb.sebi_charges + cb.gst + cb.stamp_duty
            assert abs(cb.total - expected) < 0.001, f"{mtype} {side}: total={cb.total} != sum={expected}"
    print(f"  All market_type/side combinations: total == sum of components")
run_test("Cost total equals sum of components", test_cost_total_equals_sum)

# ─────────────────────────────────────────────────────────────────────────────
# METRICS
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== METRICS TESTS ===")

def test_metrics_btc_grid():
    df = fetcher.fetch("BTC/USDT", datetime(2023,1,1), datetime(2023,12,31), "binance", "1d")
    strat = GridStrategy(lower_bound=15000, upper_bound=35000, num_levels=6, invest_per_level_usd=500)
    sig = strat.generate_signals(df)
    sim = TradeSimulator("BTC/USDT", capital=10000)
    res = sim.run(sig)
    m = calculate_metrics(res["trades"], res["equity_curve"], res["timestamps"], 10000)
    print(f"  BTC Grid 2023: return={m['total_return_pct']:.2f}% sharpe={m['sharpe_ratio']:.3f} maxdd={m['max_drawdown_pct']:.2f}%")
    for key in ["sharpe_ratio","sortino_ratio","calmar_ratio","volatility_pct","max_drawdown_pct"]:
        val = m[key]
        assert not math.isnan(val), f"{key} is NaN!"
    assert 0 <= m["win_rate"] <= 100
    assert m["num_trades"] >= 0
run_test("Metrics BTC Grid no NaN/Inf", test_metrics_btc_grid)

def test_metrics_zero_trades():
    m = calculate_metrics([], [10000,10000,10000], ["2024-01-01","2024-01-02","2024-01-03"], 10000)
    assert m["num_trades"] == 0
    assert m["total_return_pct"] == 0.0
    assert m["win_rate"] == 0.0
    print(f"  Zero trades: all fields present, no crash")
run_test("Metrics zero trades edge case", test_metrics_zero_trades)

def test_metrics_single_trade():
    """Single winning trade."""
    trades = [{
        "entry_time": "2024-01-01T00:00:00",
        "entry_price": 100.0,
        "exit_time":  "2024-01-10T00:00:00",
        "exit_price":  110.0,
        "quantity": 10.0, "pnl": 100.0, "pnl_pct": 0.1, "fees": 0.5, "side": "LONG"
    }]
    eq = [10000, 10050, 10100, 10100]
    ts = ["2024-01-01","2024-01-02","2024-01-03","2024-01-04"]
    m = calculate_metrics(trades, eq, ts, 10000)
    assert m["num_trades"] == 1
    assert m["win_rate"] == 100.0
    assert m["best_trade"] == 100.0
    assert m["worst_trade"] == 100.0
    assert m["profit_factor"] == float("inf") or m["profit_factor"] > 999
    print(f"  Single trade: win_rate={m['win_rate']}% profit_factor={m['profit_factor']}")
run_test("Metrics single winning trade", test_metrics_single_trade)

def test_metrics_annualisation():
    """Check annualised return uses 252 trading days."""
    import numpy as np
    # 252 candles with +0.1% each = approx 28% annual
    n = 252
    capital = 10000.0
    eq = [capital * (1.001 ** i) for i in range(n+1)]
    ts = [(datetime(2023,1,2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n+1)]
    m = calculate_metrics([], eq, ts, capital)
    expected = ((1.001)**252 - 1) * 100  # ~28.1%
    print(f"  Ann return: {m['annualised_return_pct']:.2f}% (expected ~{expected:.2f}%)")
    assert abs(m["annualised_return_pct"] - expected) < 2.0, \
        f"Annualised return wrong: {m['annualised_return_pct']:.2f} vs expected ~{expected:.2f}"
run_test("Metrics annualisation (252 days)", test_metrics_annualisation)

# ─────────────────────────────────────────────────────────────────────────────
# DATA VALIDATOR
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== DATA VALIDATOR TESTS ===")

def test_validator_good_data():
    df = fetcher.fetch("RELIANCE", datetime(2024,1,1), datetime(2024,3,31), "nse", "1d")
    res = validator.validate(df)
    print(f"  RELIANCE NSE quality={res.quality_score:.1f}, passed={res.passed}")
    assert res.passed, f"Good data failed validation: {res.issues}"
run_test("Validator accepts good NSE data", test_validator_good_data)

def test_validator_bad_data():
    import numpy as np
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=10),
        "open":  [100]*10,
        "high":  [90]*10,   # high < low → bad!
        "low":   [110]*10,
        "close": [100]*10,
        "volume":[1000]*10,
    })
    res = validator.validate(df)
    print(f"  Bad data quality={res.quality_score:.1f}, issues={res.issues}")
    assert not res.passed or res.quality_score < 100, "Bad data should not get 100/100"
run_test("Validator catches high<low violation", test_validator_bad_data)

# ─────────────────────────────────────────────────────────────────────────────
# IS_INDIAN DETECTION
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== SYMBOL DETECTION TESTS ===")

def test_is_indian():
    assert is_indian("RELIANCE"),   "RELIANCE should be Indian"
    assert is_indian("RELIANCE.NS"),"RELIANCE.NS should be Indian"
    assert is_indian("NIFTY50"),    "NIFTY50 should be Indian"
    assert is_indian("BANKNIFTY"),  "BANKNIFTY should be Indian"
    assert is_indian("NIFTYBEES"),  "NIFTYBEES should be Indian"
    assert not is_indian("BTC/USDT"), "BTC/USDT should NOT be Indian"
    assert not is_indian("AAPL"),   "AAPL should NOT be Indian"
    assert not is_indian("NVDA"),   "NVDA should NOT be Indian"
    print("  All symbol detection checks passed")
run_test("is_indian() detection", test_is_indian)

# ─────────────────────────────────────────────────────────────────────────────
# WACB CORRECTNESS
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=== WACB TESTS ===")

def test_wacb_correct():
    """Manual WACB verification: buy 100@100, buy 100@120, sell ALL 200@130.
    WACB avg_entry = (100*100 + 100*120) / 200 = 110
    pnl            = (130 - 110) * 200 = 4000
    """
    rows = [
        {"timestamp": datetime(2024,1,i+1), "close": p, "signal": s, "quantity": q}
        for i,(p,s,q) in enumerate([
            (100, "BUY",  100.0),   # buy 100 units
            (120, "BUY",  100.0),   # buy 100 more → avg=110, pos=200
            (130, "SELL", 200.0),   # sell ALL 200 units
            (130, "HOLD",   0.0),
            (130, "HOLD",   0.0),
        ])
    ]
    df = pd.DataFrame(rows)
    sim = TradeSimulator("TEST", capital=100000,
                         use_indian_costs=False, fee_percent=0.0, slippage_percent=0.0)
    res = sim.run(df)
    # Selling 200 units at row 2 closes the whole 200-unit position → exactly 1 trade
    assert len(res["trades"]) == 1, f"Expected 1 trade, got {len(res['trades'])}"
    t = res["trades"][0]
    assert abs(t["entry_price"] - 110.0) < 0.01, f"WACB entry_price wrong: {t['entry_price']} (expected 110)"
    assert abs(t["pnl"] - 4000.0) < 0.1,        f"WACB pnl wrong: {t['pnl']} (expected 4000)"
    print(f"  WACB: entry={t['entry_price']:.2f} (expected 110.00), pnl={t['pnl']:.2f} (expected 4000.00)")
run_test("WACB entry price and PnL correct", test_wacb_correct)

def test_partial_sell():
    """Sell only half the position, verify remaining quantity."""
    rows = [
        {"timestamp": datetime(2024,1,i+1), "close": p,
         "signal": s, "quantity": q}
        for i,(p,s,q) in enumerate([
            (100,"BUY",200),(110,"SELL",100),(120,"SELL",100),(130,"HOLD",0),
        ])
    ]
    df = pd.DataFrame(rows)
    sim = TradeSimulator("TEST", capital=100000,
                         use_indian_costs=False, fee_percent=0.0, slippage_percent=0.0)
    res = sim.run(df)
    assert len(res["trades"]) == 2, f"Expected 2 partial trades, got {len(res['trades'])}"
    total_qty = sum(t["quantity"] for t in res["trades"])
    assert abs(total_qty - 200.0) < 0.01, f"Total sold qty should be 200, got {total_qty}"
    print(f"  Partial sell: {len(res['trades'])} trades, total_qty={total_qty}")
run_test("Partial sell WACB", test_partial_sell)

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE A — REGIME TF-AWARE
# ─────────────────────────────────────────────────────────────────────────────

def test_regime_tf_aware():
    from engine.regimes import classify_regimes
    from engine.metrics import _candles_per_day
    import numpy as np

    # Build two DataFrames for the same 2-year window using different fake intervals
    # daily: 2 candles/day × 252 days
    n_daily = 504
    ts_daily = pd.date_range("2022-01-01", periods=n_daily, freq="1D")
    close = 40000 + np.cumsum(np.random.default_rng(42).normal(0, 300, n_daily))
    close = np.abs(close)
    df_daily = pd.DataFrame({"timestamp": ts_daily, "close": close, "open": close, "high": close*1.01, "low": close*0.99})

    # 4h: same date range but 6 candles/day → 6 × 252 = 1512 candles
    n_4h = n_daily * 6
    ts_4h = pd.date_range("2022-01-01", periods=n_4h, freq="4h")
    close_4h = np.interp(np.linspace(0, n_daily - 1, n_4h), np.arange(n_daily), close)
    df_4h = pd.DataFrame({"timestamp": ts_4h, "close": close_4h, "open": close_4h, "high": close_4h*1.01, "low": close_4h*0.99})

    labels_daily = classify_regimes(df_daily)
    labels_4h    = classify_regimes(df_4h)

    cpd_daily = _candles_per_day(df_daily["timestamp"].tolist())
    cpd_4h    = _candles_per_day(df_4h["timestamp"].tolist())

    # Verify window sizing is in comparable real-day units
    from engine.regimes import _candles_per_day as cpd_fn  # noqa
    n_d = len(df_daily)
    n_4 = len(df_4h)

    import numpy as _np
    long_days_d = float(_np.clip(n_d / cpd_daily / 5, 10, 60))
    long_days_4 = float(_np.clip(n_4 / cpd_4h   / 5, 10, 60))

    diff = abs(long_days_d - long_days_4)
    assert diff < 5, f"long_days disagree by {diff:.1f}d across intervals (should be < 5d)"
    print(f"  long_days: daily={long_days_d:.1f}d  4h={long_days_4:.1f}d  diff={diff:.1f}d")

    # Regime pct distributions within ±30 pp (same period, different resampling)
    def pcts(labels):
        n = len(labels)
        return {r: labels.count(r) / n * 100 for r in ("bull","bear","sideways")}

    p_daily = pcts(labels_daily)
    # Subsample 4h labels to every 6th label to align candle counts
    labels_4h_sub = labels_4h[::6]
    p_4h = pcts(list(labels_4h_sub))

    for regime in ("bull","bear","sideways"):
        diff_r = abs(p_daily[regime] - p_4h[regime])
        assert diff_r < 30, f"Regime '{regime}' pct differs {diff_r:.1f}pp across intervals"
        print(f"  {regime}: daily={p_daily[regime]:.1f}%  4h≈{p_4h[regime]:.1f}%  diff={diff_r:.1f}pp")

run_test("Regime detection is timeframe-aware (Feature A)", test_regime_tf_aware)

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE B — STRESS TESTER
# ─────────────────────────────────────────────────────────────────────────────

def test_stress_non_mutating():
    from engine.stress import SCENARIO_PRESETS, apply_stress
    import numpy as np

    n = 300
    ts = pd.date_range("2022-01-01", periods=n, freq="1D")
    close = 40000 + np.cumsum(np.random.default_rng(1).normal(0, 200, n))
    df = pd.DataFrame({
        "timestamp": ts,
        "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": 100.0,
    })

    orig_close = df["close"].copy()

    for key, scenario in SCENARIO_PRESETS.items():
        perturbed = apply_stress(df, scenario, severity=1.0, seed=42)
        # Input must not be mutated
        pd.testing.assert_series_equal(df["close"], orig_close, check_names=False)
        # OHLCV consistency
        assert (perturbed["high"] >= perturbed["close"]).all(), f"{key}: high < close"
        assert (perturbed["low"]  <= perturbed["close"]).all(), f"{key}: low > close"
        assert (perturbed["close"] > 0).all(), f"{key}: non-positive close"
        print(f"  {key}: OK  close range [{perturbed.close.min():.0f}, {perturbed.close.max():.0f}]")

run_test("apply_stress is pure (non-mutating) + OHLCV consistent (Feature B)", test_stress_non_mutating)

def test_stress_monte_carlo_percentiles():
    from engine.stress import SCENARIO_PRESETS, run_stress_backtest
    from strategies.dca import DCAStrategy
    import numpy as np

    n = 300
    ts = pd.date_range("2022-01-01", periods=n, freq="1D")
    rng = np.random.default_rng(7)
    close = 40000 + np.cumsum(rng.normal(0, 300, n))
    close = np.abs(close)
    df = pd.DataFrame({
        "timestamp": ts,
        "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": 100.0,
    })

    scenario  = SCENARIO_PRESETS["covid_crash"]
    sim_kw    = dict(symbol="BTC/USDT", fee_percent=0.001, slippage_percent=0.001)
    strat_p   = {**DCAStrategy.default_params(), "invest_per_buy_usd": 500}

    result = run_stress_backtest(
        df             = df,
        strategy_cls   = DCAStrategy,
        strategy_params= strat_p,
        sim_kwargs     = sim_kw,
        capital        = 10_000,
        scenario       = scenario,
        severity       = 1.0,
        monte_carlo_runs = 20,
        seed           = 99,
    )

    mc = result.get("monte_carlo")
    assert mc is not None, "Expected monte_carlo in result"
    assert mc["runs"] == 20
    p5, p50, p95 = mc["return_pct"]["p5"], mc["return_pct"]["p50"], mc["return_pct"]["p95"]
    assert p5 <= p50, f"p5={p5} > p50={p50}"
    assert p50 <= p95, f"p50={p50} > p95={p95}"
    assert "baseline" in result
    assert "stressed" in result
    assert "series" in result
    print(f"  MC return: P5={p5:.1f}%  P50={p50:.1f}%  P95={p95:.1f}%")
    print(f"  Baseline trades: {result['baseline'].get('num_trades', 0)}")

run_test("Stress MC percentiles P5<=P50<=P95 (Feature B)", test_stress_monte_carlo_percentiles)


def test_trade_mc_needs_three_trades():
    from engine.stress import run_trade_mc

    trades = [
        {"pnl": 100.0},
        {"pnl": -50.0},
    ]

    result = run_trade_mc(trades, capital=10_000, n_runs=50, trade_skip_pct=0.10, seed=1)
    assert result["runs"] == 0
    assert result["original_trades"] == 2
    assert result["trade_skip_pct"] == 0.10
    assert "note" in result and "Need ≥3 trades" in result["note"]

run_test("trade_mc returns zero runs when fewer than 3 trades (Feature B)", test_trade_mc_needs_three_trades)

# ─────────────────────────────────────────────────────────────────────────────
# INDICATOR ENGINE + STRATEGY EXTENSION (ROADMAP Track 1)
# ─────────────────────────────────────────────────────────────────────────────

def _synthetic_ohlcv(n=300, seed=7):
    import numpy as np
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    close = pd.Series(100 + 0.12 * t + 12 * np.sin(t / 22) + np.cumsum(rng.standard_normal(n)) * 0.7)
    high = close + abs(rng.standard_normal(n)) * 0.6
    low = close - abs(rng.standard_normal(n)) * 0.6
    return pd.DataFrame({
        "timestamp": pd.date_range("2023-01-01", periods=n, freq="D"),
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": high, "low": low, "close": close,
        "volume": pd.Series(rng.integers(1000, 9000, n)).astype(float),
    })


def test_indicator_reference_values():
    from engine.indicators import compute, INDICATOR_CATALOG, TOTAL_OUTPUT_SERIES
    # Wilder RSI on the canonical StockCharts series → ~70.5 at index 14
    s = pd.Series([44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,
                   45.89,46.03,45.61,46.28,46.28,46.00,46.03,46.41,46.22,45.64])
    ref = pd.DataFrame({"open": s, "high": s, "low": s, "close": s, "volume": [1]*len(s)})
    rsi = compute(ref, "rsi", length=14)["rsi"]
    assert abs(float(rsi.iloc[14]) - 70.5) < 1.0, f"RSI={rsi.iloc[14]}"
    # ATR of a constant TR=2 series converges to 2.0
    flat = pd.DataFrame({"high": [10]*30, "low": [8]*30, "close": [9]*30, "open": [9]*30, "volume": [1]*30})
    assert abs(float(compute(flat, "atr", length=14)["atr"].iloc[-1]) - 2.0) < 1e-6
    # MACD histogram identity
    df = _synthetic_ohlcv()
    m = compute(df, "macd")
    import numpy as np
    assert np.allclose((m["macd"] - m["macd_signal"]).dropna(), m["macd_hist"].dropna())
    # Bollinger ordering lower < mid < upper
    bb = compute(df, "bbands", length=20, std=2.0).dropna()
    assert (bb.bb_lower < bb.bb_mid).all() and (bb.bb_mid < bb.bb_upper).all()
    assert TOTAL_OUTPUT_SERIES == sum(len(e["outputs"]) for e in INDICATOR_CATALOG)
    print(f"  indicators={len(INDICATOR_CATALOG)} output_series={TOTAL_OUTPUT_SERIES} RSI[14]={rsi.iloc[14]:.2f}")

run_test("Indicator engine reference values (RSI/ATR/MACD/Bollinger)", test_indicator_reference_values)


def test_indicator_catalog_compute_all():
    from engine.indicators import INDICATOR_CATALOG, compute
    df = _synthetic_ohlcv()
    for e in INDICATOR_CATALOG:
        out = compute(df, e["key"])
        assert list(out.columns) == e["outputs"], (e["key"], list(out.columns))
        assert not out.dropna().empty, f"{e['key']} all-NaN"
    print(f"  all {len(INDICATOR_CATALOG)} indicators compute; columns match catalog")

run_test("Indicator catalog: every indicator computes with declared outputs", test_indicator_catalog_compute_all)


def test_preset_strategies_emit_valid_signals():
    from strategies import STRATEGY_REGISTRY
    df = _synthetic_ohlcv()
    presets = ["RSI", "MACD", "BOLLINGER", "SUPERTREND", "DONCHIAN", "MACROSS"]
    for name in presets:
        cls = STRATEGY_REGISTRY[name]
        out = cls(**cls.default_params()).generate_signals(df)
        assert {"signal", "quantity", "meta"} <= set(out.columns), name
        assert set(out["signal"].unique()) <= {"BUY", "SELL", "HOLD"}, name
        assert cls.category() == "indicator", name
        assert len(cls.parameter_schema()) >= 2, name
    print(f"  {len(presets)} indicator presets emit valid signal/quantity/meta frames")

run_test("Indicator preset strategies emit valid signals", test_preset_strategies_emit_valid_signals)


def test_custom_strategy_evaluator():
    from strategies import STRATEGY_REGISTRY
    from engine.indicators import compute
    import numpy as np
    df = pd.DataFrame()
    n = 250
    rng = np.random.default_rng(3)
    close = pd.Series(100 + 15 * np.sin(np.arange(n) / 12) + np.cumsum(rng.standard_normal(n)) * 0.4)
    df = pd.DataFrame({"timestamp": pd.date_range("2023-01-01", periods=n, freq="D"),
                       "open": close.shift(1).fillna(close.iloc[0]),
                       "high": close + 1, "low": close - 1, "close": close,
                       "volume": pd.Series(rng.integers(1000, 9000, n)).astype(float)})
    Custom = STRATEGY_REGISTRY["CUSTOM"]
    s = Custom(**Custom.default_params())  # RSI<30 BUY / RSI>70 SELL
    out = s.generate_signals(df)
    rsi = compute(df, "rsi", length=14)["rsi"]
    buys = out[out.signal == "BUY"].index
    sells = out[out.signal == "SELL"].index
    assert len(buys) > 0, "expected at least one BUY"
    assert all(rsi.iloc[i] < 30 for i in buys), "every BUY must be at RSI<30"
    assert all(rsi.iloc[i] > 70 for i in sells), "every SELL must be at RSI>70"
    assert Custom.category() == "custom"
    print(f"  CUSTOM rsi<30/rsi>70: buys={len(buys)} sells={len(sells)} (all gated correctly)")

run_test("CustomStrategy rule evaluator gates signals correctly", test_custom_strategy_evaluator)


def test_strategy_schema_shape():
    from strategies import STRATEGY_REGISTRY
    for name, cls in STRATEGY_REGISTRY.items():
        sch = cls.parameter_schema()
        assert isinstance(sch, dict) and sch, name
        for pname, meta in sch.items():
            assert "type" in meta and "default" in meta, (name, pname)
            assert meta["type"] in ("number", "select", "bool", "text", "array"), (name, pname, meta["type"])
    print(f"  all {len(STRATEGY_REGISTRY)} strategies expose well-formed parameter schemas")

run_test("Strategy parameter_schema shape is valid for all strategies", test_strategy_schema_shape)


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
passed = sum(1 for r in results if r[0]=="PASS")
failed = sum(1 for r in results if r[0]=="FAIL")
print(f"TOTAL: {passed} PASSED, {failed} FAILED out of {len(results)}")
if failed:
    print("\nFAILED TESTS:")
    for r in results:
        if r[0]=="FAIL":
            print(f"  [{r[1]}] {r[2]}")
print("=" * 60)
if __name__ == "__main__":
    # Only exit when run as a script — a module-level sys.exit() crashes pytest
    # collection with INTERNALERROR.
    sys.exit(0 if failed == 0 else 1)
elif failed:
    # Under pytest: surface failures as a collection error instead of exiting.
    raise AssertionError(f"{failed} test(s) failed — see output above")
