"""
AI Forward-Test Engine — synthetic future path generation.

When KRONOS_URL env var is set, paths are fetched from the Kronos GPU service
(Modal / FastAPI); otherwise a local circular block-bootstrap provides the
identical UX without GPU spend.  The data contract is stable:
  generate_paths(df, n_paths, horizon) -> list[pd.DataFrame]
so swapping the backend is zero downstream-code change.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

KRONOS_URL: Optional[str] = os.getenv("KRONOS_URL")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _infer_bar_delta(df: pd.DataFrame) -> pd.Timedelta:
    """Infer the bar interval from consecutive timestamps."""
    if len(df) >= 2:
        return df["timestamp"].iloc[-1] - df["timestamp"].iloc[-2]
    return pd.Timedelta(days=1)


# ─────────────────────────────────────────────────────────────────────────────
# Local fallback: circular block bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def _block_bootstrap_paths(
    df:         pd.DataFrame,
    n_paths:    int,
    horizon:    int,
    block_size: int = 20,
    seed:       Optional[int] = None,
) -> list[pd.DataFrame]:
    """
    Circular block bootstrap — generates N synthetic forward OHLCV DataFrames.

    Algorithm:
    1. Compute per-bar return ratios (close[t]/close[t-1]), H/C, L/C, O/C ratios
       from the historical data.
    2. For each path: sample overlapping blocks of `block_size` start-points
       (circular, so blocks wrap around the series) and concatenate to length horizon.
    3. Reconstruct OHLCV starting from the last historical close, enforcing
       H >= max(O,C) and L <= min(O,C) on each bar.

    Each path continues from the last close in `df`, producing a plausible future
    that preserves the autocorrelation structure of the historical series.
    """
    if len(df) < 2:
        raise ValueError("Need at least 2 historical candles for bootstrap")

    closes = df["close"].values.astype(float)
    opens  = df["open"].values.astype(float)
    highs  = df["high"].values.astype(float)
    lows   = df["low"].values.astype(float)
    vols   = df["volume"].values.astype(float)

    eps = 1e-10
    safe_prev  = np.where(closes[:-1] != 0.0, closes[:-1], eps)
    safe_cur   = np.where(closes[1:]  != 0.0, closes[1:],  eps)

    ret_ratio = closes[1:] / safe_prev
    hl_ratio  = highs[1:]  / safe_cur
    lc_ratio  = lows[1:]   / safe_cur
    oc_ratio  = opens[1:]  / safe_prev

    vol_mean = float(vols[1:].mean()) if vols[1:].mean() > 0 else 1.0
    vol_norm = vols[1:] / vol_mean

    n_valid    = len(closes) - 1
    rng        = np.random.default_rng(seed)
    delta      = _infer_bar_delta(df)
    last_ts    = df["timestamp"].iloc[-1]
    last_close = float(closes[-1])

    paths: list[pd.DataFrame] = []

    for _ in range(n_paths):
        n_blocks = math.ceil(horizon / block_size) + 1
        starts   = rng.integers(0, n_valid, size=n_blocks)

        ret_seq, hl_seq, lc_seq, oc_seq, vol_seq = [], [], [], [], []
        for s in starts:
            for k in range(block_size):
                idx = (int(s) + k) % n_valid
                ret_seq.append(float(ret_ratio[idx]))
                hl_seq.append(float(hl_ratio[idx]))
                lc_seq.append(float(lc_ratio[idx]))
                oc_seq.append(float(oc_ratio[idx]))
                vol_seq.append(float(vol_norm[idx]))

        ret_seq = ret_seq[:horizon]
        hl_seq  = hl_seq[:horizon]
        lc_seq  = lc_seq[:horizon]
        oc_seq  = oc_seq[:horizon]
        vol_seq = vol_seq[:horizon]

        close_arr = np.empty(horizon)
        open_arr  = np.empty(horizon)
        high_arr  = np.empty(horizon)
        low_arr   = np.empty(horizon)
        vol_arr   = np.empty(horizon)

        prev_close = last_close
        for i in range(horizon):
            c = max(prev_close * ret_seq[i], eps)
            o = max(prev_close * oc_seq[i],  eps)
            h = max(c * hl_seq[i], o, c)
            l = min(c * lc_seq[i], o, c)
            l = max(l, eps)
            v = max(vol_seq[i] * vol_mean, 0.0)

            close_arr[i] = c
            open_arr[i]  = o
            high_arr[i]  = h
            low_arr[i]   = l
            vol_arr[i]   = v
            prev_close   = c

        timestamps = [last_ts + delta * (i + 1) for i in range(horizon)]
        paths.append(pd.DataFrame({
            "timestamp": timestamps,
            "open":      open_arr,
            "high":      high_arr,
            "low":       low_arr,
            "close":     close_arr,
            "volume":    vol_arr,
        }))

    return paths


# ─────────────────────────────────────────────────────────────────────────────
# Kronos HTTP client
# ─────────────────────────────────────────────────────────────────────────────

class KronosClient:
    """
    HTTP client for the Kronos GPU forecast service.
    Falls back to block bootstrap on any error so the endpoint never breaks.
    """

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")

    def generate_paths(
        self,
        df:      pd.DataFrame,
        n_paths: int,
        horizon: int,
        seed:    Optional[int] = None,
    ) -> list[pd.DataFrame]:
        try:
            import httpx  # lazy — may not be installed in dev
            ctx = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
            ctx["timestamp"] = ctx["timestamp"].astype(str)
            resp = httpx.post(
                f"{self._url}/forecast",
                json={
                    "context":  ctx.to_dict(orient="records"),
                    "n_paths":  n_paths,
                    "horizon":  horizon,
                    "seed":     seed,
                },
                timeout=300.0,  # 5 min — GPU cold-start + 100-path batch can take ~2 min
            )
            resp.raise_for_status()
            data = resp.json()
            paths: list[pd.DataFrame] = []
            for rows in data["paths"]:
                pdf = pd.DataFrame(rows)
                pdf["timestamp"] = pd.to_datetime(pdf["timestamp"])
                paths.append(pdf)
            return paths
        except Exception as exc:
            logger.warning("Kronos unavailable (%s) — using block bootstrap", exc)
            return _block_bootstrap_paths(df, n_paths, horizon, seed=seed)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def generate_paths(
    df:         pd.DataFrame,
    n_paths:    int,
    horizon:    int,
    block_size: int = 20,
    seed:       Optional[int] = None,
) -> list[pd.DataFrame]:
    """
    Generate N synthetic future OHLCV paths of `horizon` bars.

    Uses Kronos when KRONOS_URL env var is set; falls back to block bootstrap.
    Each path starts from the last close in `df`.
    The returned DataFrames have columns: timestamp, open, high, low, close, volume.
    """
    if KRONOS_URL:
        return KronosClient(KRONOS_URL).generate_paths(df, n_paths, horizon, seed)
    return _block_bootstrap_paths(df, n_paths, horizon, block_size, seed)


def generate_one_path(
    df:         pd.DataFrame,
    horizon:    int,
    block_size: int = 20,
    seed:       Optional[int] = None,
) -> pd.DataFrame:
    """
    Generate a single synthetic forward OHLCV path of `horizon` bars.

    Used by the SSE streaming endpoint so each path can be yielded as it
    completes rather than waiting for a full batch (critical for Kronos on
    CPU where a 100-path batch can take minutes).
    """
    if KRONOS_URL:
        paths = KronosClient(KRONOS_URL).generate_paths(df, 1, horizon, seed)
        return paths[0]
    return _block_bootstrap_paths(df, 1, horizon, block_size, seed)[0]
