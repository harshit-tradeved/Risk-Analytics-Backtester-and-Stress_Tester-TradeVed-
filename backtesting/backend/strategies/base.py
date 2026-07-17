"""
Base strategy abstract class.

Every strategy must implement:
  - default_params()  → dict of param_name: default_value
  - generate_signals() → pd.DataFrame with column 'signal' (BUY / SELL / HOLD)
                         and optionally 'quantity'
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class SignalRow:
    index:    int
    signal:   str    # "BUY" | "SELL" | "HOLD"
    quantity: float  # units to trade
    price:    float
    metadata: dict   # any extra info (e.g., grid_level, ema_cross)


def Param(
    type:       str = "number",      # 'number' | 'select' | 'bool' | 'text' | 'array'
    label:      str | None = None,
    default:    Any = None,
    min:        float | None = None,
    max:        float | None = None,
    step:       float | None = None,
    options:    list | None = None,  # for 'select'
    group:      str | None = None,   # UI grouping, e.g. 'Sizing', 'Exit'
    depends_on: dict | None = None,  # {"field": "exit_type", "value": "profit"} — conditional visibility
    help:       str | None = None,
) -> dict[str, Any]:
    """Declare UI metadata for a single strategy parameter (used by the
    schema-driven frontend form). Only non-None fields are emitted."""
    d: dict[str, Any] = {"type": type}
    for k, v in (
        ("label", label), ("default", default), ("min", min), ("max", max),
        ("step", step), ("options", options), ("group", group),
        ("depends_on", depends_on), ("help", help),
    ):
        if v is not None:
            d[k] = v
    return d


def _humanize(name: str) -> str:
    return name.replace("_usd", " (USD)").replace("_pct", " %").replace("_", " ").strip().title()


def _derive_param(name: str, default: Any) -> dict[str, Any]:
    """Infer a reasonable UI schema for a param from its default value
    (back-compat for strategies that don't declare a rich schema)."""
    if isinstance(default, bool):
        ptype, step = "bool", None
    elif isinstance(default, int):
        ptype, step = "number", 1
    elif isinstance(default, float):
        ptype, step = "number", 0.1
    elif isinstance(default, (list, tuple)):
        ptype, step = "array", None
    else:
        ptype, step = "text", None
    schema: dict[str, Any] = {"type": ptype, "label": _humanize(name), "default": default}
    if step is not None:
        schema["step"] = step
    return schema


def signals_from_masks(
    df:          pd.DataFrame,
    entry_mask:  pd.Series,
    exit_mask:   pd.Series,
    invest_usd:  float = 0.0,
    qty_fallback: float = 1.0,
) -> pd.DataFrame:
    """Convert boolean entry/exit masks into the signal/quantity/meta contract.

    Long-only state machine: BUY the position when ``entry_mask`` is True and we
    are flat; SELL the full position when ``exit_mask`` is True and we are long.
    Position size is ``invest_usd / price`` when ``invest_usd > 0``, else
    ``qty_fallback`` units. Returns ``df`` (copied) with signal/quantity/meta.

    Shared by every indicator preset strategy and the custom rule builder so the
    signal-walking logic lives in exactly one place.
    """
    df = df.copy()
    close = df["close"].astype(float).to_numpy()
    em = entry_mask.fillna(False).to_numpy().astype(bool)
    xm = exit_mask.fillna(False).to_numpy().astype(bool)
    n = len(df)

    signals = ["HOLD"] * n
    qtys    = [0.0] * n
    meta    = [{} for _ in range(n)]

    in_pos = False
    held_qty = 0.0
    entry_px = 0.0
    for i in range(n):
        price = close[i]
        if not in_pos and em[i]:
            qty = (invest_usd / price) if (invest_usd > 0 and price > 0) else qty_fallback
            if qty > 0:
                signals[i] = "BUY"
                qtys[i] = qty
                meta[i] = {"entry": True}
                in_pos, held_qty, entry_px = True, qty, price
        elif in_pos and xm[i]:
            signals[i] = "SELL"
            qtys[i] = held_qty
            meta[i] = {"exit": True,
                       "pnl_pct": round((price - entry_px) / entry_px * 100, 2) if entry_px else 0.0}
            in_pos, held_qty, entry_px = False, 0.0, 0.0

    df["signal"]   = signals
    df["quantity"] = qtys
    df["meta"]     = meta
    return df


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    def __init__(self, **params):
        defaults = self.default_params()
        # Merge: defaults first, then override with any supplied params.
        # Unknown keys are dropped — params come from the public API, and
        # mass-assigning arbitrary names onto self could shadow methods.
        merged = {**defaults, **{k: v for k, v in params.items() if k in defaults}}
        self._validate_params(merged)
        self.__dict__.update(merged)
        self.params = merged

    # ── Abstract interface ────────────────────────────────────────────────────

    @staticmethod
    @abstractmethod
    def default_params() -> dict[str, Any]:
        """Return the default parameter set for this strategy."""

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals for every candle in df.

        Args:
            df: DataFrame with columns timestamp, open, high, low, close, volume

        Returns:
            df with additional columns:
              signal   : 'BUY' | 'SELL' | 'HOLD'
              quantity : units to trade (may be 0 for HOLD)
        """

    # ── Optional hooks ────────────────────────────────────────────────────────

    def _validate_params(self, params: dict):
        """Override to add parameter validation (raises ValueError on failure)."""

    # Category for the frontend strategy picker: 'classic' | 'indicator' | 'custom'
    CATEGORY: str = "classic"

    @classmethod
    def name(cls) -> str:
        return cls.__name__.replace("Strategy", "").upper()

    @classmethod
    def description(cls) -> str:
        return (cls.__doc__ or "").strip().split("\n")[0]

    @classmethod
    def category(cls) -> str:
        return cls.CATEGORY

    @classmethod
    def param_schema(cls) -> dict[str, dict[str, Any]]:
        """Override to declare rich UI metadata per parameter via Param(...).

        Any param omitted here is auto-derived from default_params(). Returns
        a partial dict {param_name: Param(...)} — it is merged over the
        derived defaults in parameter_schema()."""
        return {}

    @classmethod
    def parameter_schema(cls) -> dict[str, Any]:
        """Structured UI schema for every parameter, consumed by the
        schema-driven frontend form and GET /api/strategies.

        Each entry: {type, label, default, [min, max, step, options, group,
        depends_on, help]}. Built by deriving a schema from each default value
        and overlaying any rich declarations from param_schema()."""
        defaults = cls.default_params()
        declared = cls.param_schema()
        schema: dict[str, Any] = {}
        for name, default in defaults.items():
            entry = _derive_param(name, default)
            if name in declared:
                entry.update(declared[name])
            entry.setdefault("default", default)
            schema[name] = entry
        return schema
