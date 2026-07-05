"""
Indicator Engine — pure pandas/numpy technical indicators.
=========================================================

Why no external TA library
--------------------------
The deploy pins numpy 2.4 + pandas 3.0. ``pandas-ta 0.3.14b0`` does
``from numpy import NaN`` (removed in numpy >= 2.0) and relies on pandas APIs
deleted in pandas 3.0 (``DataFrame.append`` etc.). Rather than babysit a pin or
monkeypatch, every indicator here is implemented from its textbook formula in
pandas/numpy. This is self-contained, deploy-safe, and gives us stable output
column names that strategies and the rule-builder reference directly.

Public surface
--------------
- ``INDICATOR_CATALOG``  : list[dict] — UI/rule-builder metadata for every indicator.
- ``CATALOG_BY_KEY``     : dict[str, dict] — same, keyed by ``key``.
- ``compute(df, key, **params) -> pd.DataFrame`` — compute one indicator, return a
  DataFrame whose columns are the indicator's stable ``outputs`` names.
- ``GROUPS`` : the indicator groups (momentum/trend/volatility/volume/overlap).

Contract
--------
Every ``compute`` call returns a DataFrame indexed identically to the input ``df``
with one or more named columns. Strategies reference those names directly, e.g.::

    rsi = compute(df, "rsi", length=14)["rsi"]
    bb  = compute(df, "bbands", length=20, std=2.0)   # bb_lower / bb_mid / bb_upper
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

GROUPS = ("overlap", "momentum", "trend", "volatility", "volume", "structure")


# ─────────────────────────────────────────────────────────────────────────────
# Low-level building blocks
# ─────────────────────────────────────────────────────────────────────────────

def _series(df: pd.DataFrame, col: str = "close") -> pd.Series:
    return df[col].astype(float)


def sma(s: pd.Series, length: int) -> pd.Series:
    return s.rolling(int(length), min_periods=int(length)).mean()


def ema(s: pd.Series, length: int) -> pd.Series:
    return s.ewm(span=int(length), adjust=False).mean()


def wma(s: pd.Series, length: int) -> pd.Series:
    length = int(length)
    weights = np.arange(1, length + 1, dtype=float)
    return s.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def rma(s: pd.Series, length: int) -> pd.Series:
    """Wilder's smoothing (used by RSI/ATR/ADX).

    Properly seeded: the first output is the SMA of the first ``length`` valid
    values (skipping any leading NaNs, e.g. from ``.diff()``), then recursively
    smoothed as ``(prev*(length-1) + value) / length``. This matches the
    textbook Wilder reference; a plain ``ewm`` seeds off the first sample and
    diverges on short series.
    """
    length = int(length)
    vals = s.to_numpy(dtype=float)
    n = len(vals)
    out = np.full(n, np.nan)
    valid = ~np.isnan(vals)
    if valid.sum() < length:
        return pd.Series(out, index=s.index)
    first = int(np.argmax(valid))          # index of first non-NaN value
    seed_end = first + length              # need `length` values from `first`
    if seed_end > n:
        return pd.Series(out, index=s.index)
    prev = float(np.mean(vals[first:seed_end]))
    out[seed_end - 1] = prev
    for i in range(seed_end, n):
        v = vals[i] if not np.isnan(vals[i]) else 0.0
        prev = (prev * (length - 1) + v) / length
        out[i] = prev
    return pd.Series(out, index=s.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = _series(df, "high"), _series(df, "low"), _series(df, "close")
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


# ─────────────────────────────────────────────────────────────────────────────
# Overlap / moving averages
# ─────────────────────────────────────────────────────────────────────────────

def _sma(df, length=20):
    return _frame({"sma": sma(_series(df), length)}, df)


def _ema(df, length=20):
    return _frame({"ema": ema(_series(df), length)}, df)


def _wma(df, length=20):
    return _frame({"wma": wma(_series(df), length)}, df)


def _hma(df, length=20):
    """Hull MA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))."""
    length = int(length)
    s = _series(df)
    half = max(1, length // 2)
    sqrt_len = max(1, int(round(np.sqrt(length))))
    raw = 2 * wma(s, half) - wma(s, length)
    return _frame({"hma": wma(raw, sqrt_len)}, df)


def _vwap(df, length=14):
    """Rolling VWAP over `length` candles (typical price weighted by volume)."""
    tp = (_series(df, "high") + _series(df, "low") + _series(df, "close")) / 3.0
    vol = _series(df, "volume")
    length = int(length)
    pv = (tp * vol).rolling(length, min_periods=1).sum()
    vv = vol.rolling(length, min_periods=1).sum().replace(0, np.nan)
    return _frame({"vwap": pv / vv}, df)


# ─────────────────────────────────────────────────────────────────────────────
# Momentum
# ─────────────────────────────────────────────────────────────────────────────

def _rsi(df, length=14):
    s = _series(df)
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)  # all-gains → RSI 100
    return _frame({"rsi": rsi}, df)


def _macd(df, fast=12, slow=26, signal=9):
    s = _series(df)
    macd_line = ema(s, fast) - ema(s, slow)
    macd_signal = ema(macd_line, signal)
    macd_hist = macd_line - macd_signal
    return _frame({"macd": macd_line, "macd_signal": macd_signal, "macd_hist": macd_hist}, df)


def _stoch(df, k=14, d=3, smooth_k=3):
    high, low, close = _series(df, "high"), _series(df, "low"), _series(df, "close")
    k = int(k)
    ll = low.rolling(k, min_periods=k).min()
    hh = high.rolling(k, min_periods=k).max()
    raw_k = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    stoch_k = raw_k.rolling(int(smooth_k), min_periods=int(smooth_k)).mean()
    stoch_d = stoch_k.rolling(int(d), min_periods=int(d)).mean()
    return _frame({"stoch_k": stoch_k, "stoch_d": stoch_d}, df)


def _cci(df, length=20):
    tp = (_series(df, "high") + _series(df, "low") + _series(df, "close")) / 3.0
    length = int(length)
    ma = tp.rolling(length, min_periods=length).mean()
    md = (tp - ma).abs().rolling(length, min_periods=length).mean()
    cci = (tp - ma) / (0.015 * md.replace(0, np.nan))
    return _frame({"cci": cci}, df)


def _roc(df, length=10):
    s = _series(df)
    return _frame({"roc": 100 * (s - s.shift(int(length))) / s.shift(int(length))}, df)


def _mom(df, length=10):
    s = _series(df)
    return _frame({"mom": s - s.shift(int(length))}, df)


def _willr(df, length=14):
    high, low, close = _series(df, "high"), _series(df, "low"), _series(df, "close")
    length = int(length)
    hh = high.rolling(length, min_periods=length).max()
    ll = low.rolling(length, min_periods=length).min()
    willr = -100 * (hh - close) / (hh - ll).replace(0, np.nan)
    return _frame({"willr": willr}, df)


def _tsi(df, fast=13, slow=25):
    s = _series(df)
    m = s.diff()
    abs_m = m.abs()
    ema1 = ema(ema(m, slow), fast)
    ema2 = ema(ema(abs_m, slow), fast)
    return _frame({"tsi": 100 * ema1 / ema2.replace(0, np.nan)}, df)


# ─────────────────────────────────────────────────────────────────────────────
# Trend
# ─────────────────────────────────────────────────────────────────────────────

def _adx(df, length=14):
    high, low = _series(df, "high"), _series(df, "low")
    up = high.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr = true_range(df)
    atr = rma(tr, length)
    plus_di = 100 * rma(plus_dm, length) / atr.replace(0, np.nan)
    minus_di = 100 * rma(minus_dm, length) / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = rma(dx, length)
    return _frame({"adx": adx, "plus_di": plus_di, "minus_di": minus_di}, df)


def _aroon(df, length=25):
    length = int(length)
    high, low = _series(df, "high"), _series(df, "low")
    aroon_up = high.rolling(length + 1, min_periods=length + 1).apply(
        lambda x: 100 * (length - (len(x) - 1 - int(np.argmax(x)))) / length, raw=True)
    aroon_down = low.rolling(length + 1, min_periods=length + 1).apply(
        lambda x: 100 * (length - (len(x) - 1 - int(np.argmin(x)))) / length, raw=True)
    return _frame({"aroon_up": aroon_up, "aroon_down": aroon_down,
                   "aroon_osc": aroon_up - aroon_down}, df)


def _supertrend(df, length=10, multiplier=3.0):
    length = int(length)
    mult = float(multiplier)
    high, low, close = _series(df, "high"), _series(df, "low"), _series(df, "close")
    hl2 = (high + low) / 2.0
    atr = rma(true_range(df), length)
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    n = len(df)
    final_upper = upper.copy().to_numpy()
    final_lower = lower.copy().to_numpy()
    st = np.full(n, np.nan)
    direction = np.ones(n)  # 1 = uptrend, -1 = downtrend
    close_v = close.to_numpy()

    for i in range(1, n):
        if not np.isnan(final_upper[i - 1]):
            if upper.iloc[i] < final_upper[i - 1] or close_v[i - 1] > final_upper[i - 1]:
                final_upper[i] = upper.iloc[i]
            else:
                final_upper[i] = final_upper[i - 1]
            if lower.iloc[i] > final_lower[i - 1] or close_v[i - 1] < final_lower[i - 1]:
                final_lower[i] = lower.iloc[i]
            else:
                final_lower[i] = final_lower[i - 1]

        if np.isnan(st[i - 1]):
            direction[i] = 1
            st[i] = final_lower[i]
            continue
        if close_v[i] > final_upper[i]:
            direction[i] = 1
        elif close_v[i] < final_lower[i]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        st[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    return _frame({"supertrend": pd.Series(st, index=df.index),
                   "supertrend_dir": pd.Series(direction, index=df.index)}, df)


def _psar(df, step=0.02, max_step=0.2):
    step = float(step)
    max_step = float(max_step)
    high = _series(df, "high").to_numpy()
    low = _series(df, "low").to_numpy()
    n = len(df)
    psar = np.full(n, np.nan)
    if n == 0:
        return _frame({"psar": pd.Series(psar, index=df.index)}, df)

    bull = True
    af = step
    ep = high[0]
    psar[0] = low[0]
    for i in range(1, n):
        prev = psar[i - 1]
        psar[i] = prev + af * (ep - prev)
        if bull:
            psar[i] = min(psar[i], low[i - 1], low[max(i - 2, 0)])
            if high[i] > ep:
                ep = high[i]
                af = min(af + step, max_step)
            if low[i] < psar[i]:
                bull = False
                psar[i] = ep
                ep = low[i]
                af = step
        else:
            psar[i] = max(psar[i], high[i - 1], high[max(i - 2, 0)])
            if low[i] < ep:
                ep = low[i]
                af = min(af + step, max_step)
            if high[i] > psar[i]:
                bull = True
                psar[i] = ep
                ep = high[i]
                af = step
    return _frame({"psar": pd.Series(psar, index=df.index)}, df)


# ─────────────────────────────────────────────────────────────────────────────
# Volatility
# ─────────────────────────────────────────────────────────────────────────────

def _atr(df, length=14):
    return _frame({"atr": rma(true_range(df), length)}, df)


def _bbands(df, length=20, std=2.0):
    length = int(length)
    s = _series(df)
    mid = sma(s, length)
    sd = s.rolling(length, min_periods=length).std(ddof=0)
    upper = mid + float(std) * sd
    lower = mid - float(std) * sd
    width = (upper - lower) / mid.replace(0, np.nan)
    return _frame({"bb_lower": lower, "bb_mid": mid, "bb_upper": upper, "bb_width": width}, df)


def _keltner(df, length=20, multiplier=2.0):
    length = int(length)
    s = _series(df)
    mid = ema(s, length)
    atr = rma(true_range(df), length)
    upper = mid + float(multiplier) * atr
    lower = mid - float(multiplier) * atr
    return _frame({"kc_lower": lower, "kc_mid": mid, "kc_upper": upper}, df)


def _donchian(df, length=20):
    length = int(length)
    high, low = _series(df, "high"), _series(df, "low")
    # Shift by 1 so dc_upper/dc_lower reflect the PREVIOUS period's channel extremes.
    # This is the standard Donchian convention for breakout signals: today's close
    # vs yesterday's N-period high/low. Without the shift, close can never exceed
    # dc_upper (since close <= high always), making cross_above impossible.
    upper = high.rolling(length, min_periods=length).max().shift(1)
    lower = low.rolling(length, min_periods=length).min().shift(1)
    return _frame({"dc_lower": lower, "dc_mid": (upper + lower) / 2.0, "dc_upper": upper}, df)


def _stdev(df, length=20):
    return _frame({"stdev": _series(df).rolling(int(length), min_periods=int(length)).std(ddof=0)}, df)


# ─────────────────────────────────────────────────────────────────────────────
# Volume
# ─────────────────────────────────────────────────────────────────────────────

def _obv(df):
    close, vol = _series(df, "close"), _series(df, "volume")
    sign = np.sign(close.diff().fillna(0.0))
    return _frame({"obv": (sign * vol).cumsum()}, df)


def _mfi(df, length=14):
    length = int(length)
    tp = (_series(df, "high") + _series(df, "low") + _series(df, "close")) / 3.0
    rmf = tp * _series(df, "volume")
    delta = tp.diff()
    pos_mf = rmf.where(delta > 0, 0.0).rolling(length, min_periods=length).sum()
    neg_mf = rmf.where(delta < 0, 0.0).rolling(length, min_periods=length).sum()
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    return _frame({"mfi": 100 - (100 / (1 + mfr))}, df)


def _cmf(df, length=20):
    length = int(length)
    high, low, close, vol = (_series(df, "high"), _series(df, "low"),
                             _series(df, "close"), _series(df, "volume"))
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mfv = mfm * vol
    cmf = mfv.rolling(length, min_periods=length).sum() / vol.rolling(length, min_periods=length).sum().replace(0, np.nan)
    return _frame({"cmf": cmf}, df)


# ─────────────────────────────────────────────────────────────────────────────
# Support/Resistance & session-structure
# ─────────────────────────────────────────────────────────────────────────────
# Added to cover a real coverage gap found via reel_pipeline_test_results_100.xlsx
# (148-URL run): "draw support/resistance", "opening range breakout", and
# "Ichimoku cloud" strategy content was correctly identified by triage as real
# strategy content but couldn't be expressed as a rule — these three make the
# most common of those patterns expressible.

def _pivot(df, length=1):
    """
    Classic floor pivot points, computed from the PRIOR `length`-period
    high/low/close and held constant for the current bar (no look-ahead —
    length=1 on daily candles reproduces the textbook daily pivot).
    """
    length = int(length)
    high, low, close = _series(df, "high"), _series(df, "low"), _series(df, "close")
    prev_high  = high.rolling(length, min_periods=length).max().shift(1)
    prev_low   = low.rolling(length, min_periods=length).min().shift(1)
    prev_close = close.shift(length)
    pivot = (prev_high + prev_low + prev_close) / 3.0
    r1 = 2 * pivot - prev_low
    s1 = 2 * pivot - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)
    return _frame({"pivot": pivot, "pivot_r1": r1, "pivot_r2": r2,
                   "pivot_s1": s1, "pivot_s2": s2}, df)


def _orb(df, opening_candles=15):
    """
    Opening Range Breakout: the high/low of the first `opening_candles` bars
    of each session (grouped by calendar date of `timestamp`), held constant
    for the rest of that session. NaN during the opening range itself (the
    range isn't known yet — masking this avoids look-ahead leakage).
    """
    n = int(opening_candles)
    if "timestamp" not in df.columns:
        nan_col = pd.Series(np.nan, index=df.index)
        return _frame({"orb_high": nan_col, "orb_low": nan_col}, df)
    date = pd.to_datetime(df["timestamp"]).dt.date
    high, low = _series(df, "high"), _series(df, "low")
    day_idx = date.groupby(date).cumcount()
    or_high = high.where(day_idx < n).groupby(date).transform("max")
    or_low  = low.where(day_idx < n).groupby(date).transform("min")
    or_high = or_high.where(day_idx >= n)
    or_low  = or_low.where(day_idx >= n)
    return _frame({"orb_high": or_high, "orb_low": or_low}, df)


def _ichimoku(df, tenkan=9, kijun=26, senkou_b=52):
    """
    Ichimoku Cloud. tenkan_sen/kijun_sen are the standard midpoint lines.
    senkou_a/senkou_b are shifted FORWARD by `kijun` periods to match how the
    cloud is plotted relative to price — at bar t this uses only data up to
    t-kijun, so it's not look-ahead. Chikou span is intentionally omitted:
    it's conventionally read by eye against past price, not used as a
    forward rule input, and including it as a same-index column would
    require a backward shift that leaks future closes.
    """
    tenkan, kijun, senkou_b = int(tenkan), int(kijun), int(senkou_b)
    high, low = _series(df, "high"), _series(df, "low")
    tenkan_sen = (high.rolling(tenkan, min_periods=tenkan).max()
                  + low.rolling(tenkan, min_periods=tenkan).min()) / 2.0
    kijun_sen = (high.rolling(kijun, min_periods=kijun).max()
                 + low.rolling(kijun, min_periods=kijun).min()) / 2.0
    senkou_a = ((tenkan_sen + kijun_sen) / 2.0).shift(kijun)
    senkou_b_line = ((high.rolling(senkou_b, min_periods=senkou_b).max()
                       + low.rolling(senkou_b, min_periods=senkou_b).min()) / 2.0).shift(kijun)
    return _frame({"tenkan_sen": tenkan_sen, "kijun_sen": kijun_sen,
                   "senkou_a": senkou_a, "senkou_b": senkou_b_line}, df)


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch + helpers
# ─────────────────────────────────────────────────────────────────────────────

def _frame(cols: dict[str, pd.Series], df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(cols)
    out.index = df.index
    return out


# key → compute fn
_DISPATCH: dict[str, Callable[..., pd.DataFrame]] = {
    "sma": _sma, "ema": _ema, "wma": _wma, "hma": _hma, "vwap": _vwap,
    "rsi": _rsi, "macd": _macd, "stoch": _stoch, "cci": _cci, "roc": _roc,
    "mom": _mom, "willr": _willr, "tsi": _tsi,
    "adx": _adx, "aroon": _aroon, "supertrend": _supertrend, "psar": _psar,
    "atr": _atr, "bbands": _bbands, "keltner": _keltner, "donchian": _donchian, "stdev": _stdev,
    "obv": _obv, "mfi": _mfi, "cmf": _cmf,
    "pivot": _pivot, "orb": _orb, "ichimoku": _ichimoku,
}


def compute(df: pd.DataFrame, key: str, **params) -> pd.DataFrame:
    """Compute one indicator. Returns a DataFrame with the indicator's output columns."""
    key = key.lower()
    fn = _DISPATCH.get(key)
    if fn is None:
        raise KeyError(f"Unknown indicator '{key}'. Available: {sorted(_DISPATCH)}")
    meta = CATALOG_BY_KEY[key]
    # Clamp user-supplied values into the catalog's declared [min, max] range —
    # a rule-builder payload with length=0/negative would otherwise crash pandas
    # (500 on /backtest/run, silent all-zero runs under stress MC).
    by_name = {p["name"]: p for p in meta["params"]}
    clean = {}
    for k, v in params.items():
        p = by_name.get(k)
        if p is None:
            continue
        try:
            clean[k] = min(max(float(v), p["min"]), p["max"])
        except (TypeError, ValueError):
            clean[k] = p["default"]
    return fn(df, **clean)


# ─────────────────────────────────────────────────────────────────────────────
# Catalog metadata (drives the rule-builder UI + /api/indicators)
# ─────────────────────────────────────────────────────────────────────────────

def _p(name, default, lo, hi, step=1):
    return {"name": name, "default": default, "min": lo, "max": hi, "step": step}


INDICATOR_CATALOG: list[dict[str, Any]] = [
    # ── Overlap ──
    {"key": "sma", "label": "Simple Moving Average", "group": "overlap",
     "params": [_p("length", 20, 2, 400)], "outputs": ["sma"]},
    {"key": "ema", "label": "Exponential Moving Average", "group": "overlap",
     "params": [_p("length", 20, 2, 400)], "outputs": ["ema"]},
    {"key": "wma", "label": "Weighted Moving Average", "group": "overlap",
     "params": [_p("length", 20, 2, 400)], "outputs": ["wma"]},
    {"key": "hma", "label": "Hull Moving Average", "group": "overlap",
     "params": [_p("length", 20, 2, 400)], "outputs": ["hma"]},
    {"key": "vwap", "label": "Volume-Weighted Avg Price", "group": "overlap",
     "params": [_p("length", 14, 2, 200)], "outputs": ["vwap"]},
    # ── Momentum ──
    {"key": "rsi", "label": "Relative Strength Index", "group": "momentum",
     "params": [_p("length", 14, 2, 100)], "outputs": ["rsi"]},
    {"key": "macd", "label": "MACD", "group": "momentum",
     "params": [_p("fast", 12, 2, 100), _p("slow", 26, 3, 200), _p("signal", 9, 2, 100)],
     "outputs": ["macd", "macd_signal", "macd_hist"]},
    {"key": "stoch", "label": "Stochastic Oscillator", "group": "momentum",
     "params": [_p("k", 14, 2, 100), _p("d", 3, 1, 50), _p("smooth_k", 3, 1, 50)],
     "outputs": ["stoch_k", "stoch_d"]},
    {"key": "cci", "label": "Commodity Channel Index", "group": "momentum",
     "params": [_p("length", 20, 2, 200)], "outputs": ["cci"]},
    {"key": "roc", "label": "Rate of Change", "group": "momentum",
     "params": [_p("length", 10, 1, 200)], "outputs": ["roc"]},
    {"key": "mom", "label": "Momentum", "group": "momentum",
     "params": [_p("length", 10, 1, 200)], "outputs": ["mom"]},
    {"key": "willr", "label": "Williams %R", "group": "momentum",
     "params": [_p("length", 14, 2, 100)], "outputs": ["willr"]},
    {"key": "tsi", "label": "True Strength Index", "group": "momentum",
     "params": [_p("fast", 13, 2, 100), _p("slow", 25, 3, 200)], "outputs": ["tsi"]},
    # ── Trend ──
    {"key": "adx", "label": "Average Directional Index", "group": "trend",
     "params": [_p("length", 14, 2, 100)], "outputs": ["adx", "plus_di", "minus_di"]},
    {"key": "aroon", "label": "Aroon", "group": "trend",
     "params": [_p("length", 25, 2, 200)], "outputs": ["aroon_up", "aroon_down", "aroon_osc"]},
    {"key": "supertrend", "label": "Supertrend", "group": "trend",
     "params": [_p("length", 10, 2, 100), _p("multiplier", 3.0, 0.5, 10, 0.5)],
     "outputs": ["supertrend", "supertrend_dir"]},
    {"key": "psar", "label": "Parabolic SAR", "group": "trend",
     "params": [_p("step", 0.02, 0.001, 0.2, 0.001), _p("max_step", 0.2, 0.05, 1.0, 0.05)],
     "outputs": ["psar"]},
    # ── Volatility ──
    {"key": "atr", "label": "Average True Range", "group": "volatility",
     "params": [_p("length", 14, 2, 100)], "outputs": ["atr"]},
    {"key": "bbands", "label": "Bollinger Bands", "group": "volatility",
     "params": [_p("length", 20, 2, 200), _p("std", 2.0, 0.5, 5, 0.5)],
     "outputs": ["bb_lower", "bb_mid", "bb_upper", "bb_width"]},
    {"key": "keltner", "label": "Keltner Channels", "group": "volatility",
     "params": [_p("length", 20, 2, 200), _p("multiplier", 2.0, 0.5, 10, 0.5)],
     "outputs": ["kc_lower", "kc_mid", "kc_upper"]},
    {"key": "donchian", "label": "Donchian Channels", "group": "volatility",
     "params": [_p("length", 20, 2, 200)], "outputs": ["dc_lower", "dc_mid", "dc_upper"]},
    {"key": "stdev", "label": "Standard Deviation", "group": "volatility",
     "params": [_p("length", 20, 2, 200)], "outputs": ["stdev"]},
    # ── Volume ──
    {"key": "obv", "label": "On-Balance Volume", "group": "volume",
     "params": [], "outputs": ["obv"]},
    {"key": "mfi", "label": "Money Flow Index", "group": "volume",
     "params": [_p("length", 14, 2, 100)], "outputs": ["mfi"]},
    {"key": "cmf", "label": "Chaikin Money Flow", "group": "volume",
     "params": [_p("length", 20, 2, 200)], "outputs": ["cmf"]},
    # ── Structure (support/resistance & session) ──
    {"key": "pivot", "label": "Pivot Points (Classic)", "group": "structure",
     "params": [_p("length", 1, 1, 200)],
     "outputs": ["pivot", "pivot_r1", "pivot_r2", "pivot_s1", "pivot_s2"]},
    {"key": "orb", "label": "Opening Range Breakout (intraday intervals only)", "group": "structure",
     "params": [_p("opening_candles", 15, 1, 200)],
     "outputs": ["orb_high", "orb_low"]},
    {"key": "ichimoku", "label": "Ichimoku Cloud", "group": "structure",
     "params": [_p("tenkan", 9, 2, 100), _p("kijun", 26, 3, 200), _p("senkou_b", 52, 5, 400)],
     "outputs": ["tenkan_sen", "kijun_sen", "senkou_a", "senkou_b"]},
]

CATALOG_BY_KEY: dict[str, dict] = {e["key"]: e for e in INDICATOR_CATALOG}

# Every catalog entry that lists an output column contributes selectable signals.
# Total distinct output series available to the rule-builder:
TOTAL_OUTPUT_SERIES = sum(len(e["outputs"]) for e in INDICATOR_CATALOG)
