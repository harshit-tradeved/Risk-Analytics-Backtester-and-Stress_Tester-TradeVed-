"""
Kronos forecast service.

Wraps KronosPredictor in a FastAPI endpoint that matches the contract
expected by engine/forecast.py KronosClient:

  POST /forecast
    body: { context: [{timestamp,open,high,low,close,volume},...],
            n_paths: int, horizon: int, seed: int|null }
  response: { paths: [ [{timestamp,open,high,low,close,volume},...], ... ] }

Run locally:
  python -m uvicorn main:app --port 8001

Then set KRONOS_URL=http://localhost:8001 in your backtester environment.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ── Kronos repo path ──────────────────────────────────────────────────────────
# The Kronos repo (https://github.com/shiyu-coder/Kronos) must be cloned
# alongside this file:  kronos_service/Kronos/
# Run setup.py (or manually: git clone https://github.com/shiyu-coder/Kronos)
_KRONOS_REPO = Path(__file__).parent / "Kronos"
if not _KRONOS_REPO.exists():
    raise RuntimeError(
        "Kronos repo not found. Run:\n"
        "  cd kronos_service && git clone https://github.com/shiyu-coder/Kronos"
    )
sys.path.insert(0, str(_KRONOS_REPO))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Model selection ───────────────────────────────────────────────────────────
# Override via env vars:
#   KRONOS_MODEL=NeoQuasar/Kronos-base   (default: Kronos-small)
#   KRONOS_TOKENIZER=NeoQuasar/Kronos-Tokenizer-base
#   KRONOS_DEVICE=cuda   (default: cpu)
_MODEL_ID     = os.getenv("KRONOS_MODEL",     "NeoQuasar/Kronos-small")
_TOKENIZER_ID = os.getenv("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base")
_DEVICE       = os.getenv("KRONOS_DEVICE",    "cpu")
_MAX_CONTEXT  = 512  # Kronos-small / Kronos-base context window

app = FastAPI(title="Kronos Forecast Service")

# ── Load model at startup (once) ──────────────────────────────────────────────
logger.info("Loading Kronos tokenizer: %s", _TOKENIZER_ID)
_tokenizer = KronosTokenizer.from_pretrained(_TOKENIZER_ID)

logger.info("Loading Kronos model: %s  device=%s", _MODEL_ID, _DEVICE)
_model = Kronos.from_pretrained(_MODEL_ID)

_predictor = KronosPredictor(_model, _tokenizer, device=_DEVICE, max_context=_MAX_CONTEXT)
logger.info("Kronos ready.")


# ── Request / response schemas ────────────────────────────────────────────────

class OHLCVBar(BaseModel):
    timestamp: str
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float = 0.0


class ForecastRequest(BaseModel):
    context:  list[OHLCVBar]
    n_paths:  int = 100
    horizon:  int = 90
    seed:     Optional[int] = None
    temperature: float = 1.0
    top_p:       float = 0.9


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "model": _MODEL_ID}


# ── Forecast endpoint ─────────────────────────────────────────────────────────

@app.post("/forecast")
def forecast(req: ForecastRequest):
    """
    Generate n_paths forward OHLCV paths of length horizon bars.

    Uses predict_batch: passes the same context N times so Kronos generates
    N independent samples in one batched forward pass (far faster than N
    sequential calls).
    """
    if len(req.context) < 2:
        raise HTTPException(400, "Need at least 2 historical candles")

    n_paths = max(1, req.n_paths)
    horizon = max(1, req.horizon)

    # Build context DataFrame
    ctx = pd.DataFrame([b.model_dump() for b in req.context])
    ctx["timestamp"] = pd.to_datetime(ctx["timestamp"])
    ctx = ctx.sort_values("timestamp").reset_index(drop=True)

    # Infer bar delta from context
    delta = ctx["timestamp"].iloc[-1] - ctx["timestamp"].iloc[-2]
    last_ts = ctx["timestamp"].iloc[-1]

    # Future timestamps for each path (same for all paths)
    y_timestamps = pd.Series([last_ts + delta * (i + 1) for i in range(horizon)])

    # Trim context to max_context
    if len(ctx) > _MAX_CONTEXT:
        ctx = ctx.tail(_MAX_CONTEXT).reset_index(drop=True)

    # OHLCV columns Kronos expects (volume + amount optional)
    cols = ["open", "high", "low", "close"]
    if "volume" in ctx.columns:
        cols.append("volume")
    x_df = ctx[cols].copy()
    x_ts = ctx["timestamp"].reset_index(drop=True)

    # Use predict_batch: repeat the same input N times → N independent paths
    # (each sample is drawn stochastically via temperature sampling)
    try:
        pred_list = _predictor.predict_batch(
            df_list            = [x_df]        * n_paths,
            x_timestamp_list   = [x_ts]        * n_paths,
            y_timestamp_list   = [y_timestamps] * n_paths,
            pred_len           = horizon,
            T                  = req.temperature,
            top_p              = req.top_p,
            sample_count       = 1,
            verbose            = False,
        )
    except Exception as exc:
        logger.exception("Kronos predict_batch failed")
        raise HTTPException(500, f"Kronos inference failed: {exc}")

    paths: list[list[dict]] = []
    for pred_df in pred_list:
        rows = []
        for i, ts in enumerate(y_timestamps):
            rows.append({
                "timestamp": ts.isoformat(),
                "open":   _safe_float(pred_df, "open",   i),
                "high":   _safe_float(pred_df, "high",   i),
                "low":    _safe_float(pred_df, "low",    i),
                "close":  _safe_float(pred_df, "close",  i),
                "volume": _safe_float(pred_df, "volume", i) if "volume" in pred_df.columns else 0.0,
            })
        paths.append(rows)

    return {"paths": paths}


def _safe_float(df: pd.DataFrame, col: str, i: int) -> float:
    try:
        v = float(df[col].iloc[i])
        return v if np.isfinite(v) else 0.0
    except Exception:
        return 0.0
