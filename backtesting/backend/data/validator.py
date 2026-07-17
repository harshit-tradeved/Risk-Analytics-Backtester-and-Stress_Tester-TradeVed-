"""
Data Validator — quality checks for OHLCV DataFrames.

Checks performed:
  1. Schema validation  (required columns present)
  2. Type validation    (numeric dtypes)
  3. Range validation   (prices > 0, volume >= 0, high >= low, high >= open, etc.)
  4. Continuity check   (no unexpected date gaps)
  5. Duplicate check    (duplicate timestamps)
  6. Outlier detection  (price changes > configurable Z-score threshold)
  7. NaN / Inf check

Returns:
  ValidationResult with quality_score (0–100) and a list of issues.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


@dataclass
class ValidationResult:
    quality_score: float = 100.0
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    passed: bool = True

    def add_issue(self, msg: str, deduction: float = 5.0):
        self.issues.append(msg)
        self.quality_score = max(0.0, self.quality_score - deduction)
        self.passed = self.quality_score >= 50.0

    def add_warning(self, msg: str, deduction: float = 2.0):
        self.warnings.append(msg)
        self.quality_score = max(0.0, self.quality_score - deduction)


class DataValidator:
    """Validates an OHLCV DataFrame and computes a quality score."""

    def __init__(
        self,
        outlier_z_threshold: float = 5.0,
        max_gap_multiplier: float = 3.0,
    ):
        self.outlier_z_threshold = outlier_z_threshold
        self.max_gap_multiplier  = max_gap_multiplier

    # ── Public entry point ────────────────────────────────────────────────────

    def validate(self, df: pd.DataFrame, interval: str = "1d") -> ValidationResult:
        """Run all checks and return a ValidationResult."""
        result = ValidationResult()

        self._check_schema(df, result)
        if result.quality_score < 50:
            return result  # cannot proceed without columns

        self._check_types(df, result)
        self._check_ranges(df, result)
        self._check_duplicates(df, result)
        self._check_continuity(df, result, interval)
        self._check_outliers(df, result)
        self._check_nan_inf(df, result)
        self._collect_stats(df, result)

        result.passed = result.quality_score >= 50.0
        logger.info(
            "Validation complete — score: %.1f | issues: %d | warnings: %d",
            result.quality_score, len(result.issues), len(result.warnings)
        )
        return result

    # ── Internal checks ───────────────────────────────────────────────────────

    def _check_schema(self, df: pd.DataFrame, result: ValidationResult):
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            result.add_issue(f"Missing required columns: {missing}", deduction=30.0)

    def _check_types(self, df: pd.DataFrame, result: ValidationResult):
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
                result.add_issue(f"Column '{col}' is not numeric", deduction=10.0)

    def _check_ranges(self, df: pd.DataFrame, result: ValidationResult):
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                bad = (df[col] <= 0).sum()
                if bad:
                    result.add_issue(f"{bad} non-positive values in '{col}'", deduction=10.0)

        if "volume" in df.columns:
            bad = (df["volume"] < 0).sum()
            if bad:
                result.add_issue(f"{bad} negative volume values", deduction=5.0)

        if {"high", "low"}.issubset(df.columns):
            bad = (df["high"] < df["low"]).sum()
            if bad:
                result.add_issue(f"{bad} rows where high < low", deduction=10.0)

        if {"high", "open", "close"}.issubset(df.columns):
            bad = ((df["high"] < df["open"]) | (df["high"] < df["close"])).sum()
            if bad:
                result.add_warning(f"{bad} rows where high < open or close", deduction=3.0)

        if {"low", "open", "close"}.issubset(df.columns):
            bad = ((df["low"] > df["open"]) | (df["low"] > df["close"])).sum()
            if bad:
                result.add_warning(f"{bad} rows where low > open or close", deduction=3.0)

    def _check_duplicates(self, df: pd.DataFrame, result: ValidationResult):
        if "timestamp" not in df.columns:
            return
        dups = df.duplicated("timestamp").sum()
        if dups:
            result.add_issue(f"{dups} duplicate timestamps", deduction=5.0)

    def _check_continuity(self, df: pd.DataFrame, result: ValidationResult, interval: str):
        if "timestamp" not in df.columns or len(df) < 2:
            return

        ts = pd.to_datetime(df["timestamp"]).sort_values().reset_index(drop=True)
        diffs = ts.diff().dropna()
        median_diff = diffs.median()

        threshold = median_diff * self.max_gap_multiplier
        gaps = diffs[diffs > threshold]

        if len(gaps):
            pct_missing = len(gaps) / len(df) * 100
            deduction = min(20.0, pct_missing * 2)
            result.add_warning(
                f"{len(gaps)} gaps larger than {self.max_gap_multiplier}× median interval "
                f"({pct_missing:.1f}% of candles)",
                deduction=deduction,
            )

    def _check_outliers(self, df: pd.DataFrame, result: ValidationResult):
        if "close" not in df.columns or len(df) < 5:
            return

        returns = df["close"].pct_change().dropna()
        mean_r  = returns.mean()
        std_r   = returns.std()

        if std_r < 1e-10:
            return

        z_scores = ((returns - mean_r) / std_r).abs()
        outliers = (z_scores > self.outlier_z_threshold).sum()

        if outliers:
            result.add_warning(
                f"{outliers} extreme return(s) detected (Z > {self.outlier_z_threshold:.0f}σ)",
                deduction=min(10.0, outliers * 2),
            )

    def _check_nan_inf(self, df: pd.DataFrame, result: ValidationResult):
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col not in df.columns:
                continue
            nan_cnt = df[col].isna().sum()
            inf_cnt = np.isinf(df[col].replace([np.inf, -np.inf], np.nan).fillna(0)).sum()
            if nan_cnt:
                result.add_issue(f"{nan_cnt} NaN values in '{col}'", deduction=5.0)
            if inf_cnt:
                result.add_issue(f"{inf_cnt} Inf values in '{col}'", deduction=5.0)

    def _collect_stats(self, df: pd.DataFrame, result: ValidationResult):
        result.stats = {
            "total_rows":    len(df),
            "date_range":    {
                "start": str(df["timestamp"].min()) if "timestamp" in df.columns else None,
                "end":   str(df["timestamp"].max()) if "timestamp" in df.columns else None,
            },
            "close_mean":    float(df["close"].mean())   if "close"  in df.columns else None,
            "close_min":     float(df["close"].min())    if "close"  in df.columns else None,
            "close_max":     float(df["close"].max())    if "close"  in df.columns else None,
            "volume_total":  float(df["volume"].sum())   if "volume" in df.columns else None,
        }
