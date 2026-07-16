"""
Reel Strategy Improvement Pipeline — Critique → Improve → Judge.

Three stages, all grounded in REAL numbers computed by the deterministic
backtest engine (never fabricated by an LLM):

  1. critique_and_improve(ir, metrics, ...) — LLM reads the actual computed
     metrics of the original backtest, names concrete problems, and proposes
     a modified Strategy IR (`improved_ir`) meant to address them. The LLM
     never states improved numbers itself — that's the engine's job.
  2. (caller) re-runs `improved_ir` through the real backtest engine to get
     `improved_metrics`. This module only performs arithmetic diffing of
     the two metrics dicts — no LLM involved, so the reported deltas are
     exactly what the engine computed.
  3. judge_pipeline(trace) — a second, independent LLM call that reviews the
     entire trace end-to-end (transcript → extraction → critique →
     improved IR → both metric sets → diff) and flags anything dishonest,
     inconsistent, unimplemented, or overfit. It does not recompute
     metrics; it audits process integrity.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from reel_to_backtest.reel_extractor import _llm, _parse_json, _INDICATOR_KEYS  # provider-agnostic LLM call

logger = logging.getLogger(__name__)

# Metrics we compare / expose. Keys match `results` dict built in main.py.
_DIFF_METRICS = [
    ("total_return_pct",   "Total Return %",   "higher_better"),
    ("annualised_return_pct", "Annualised Return %", "higher_better"),
    ("sharpe_ratio",       "Sharpe Ratio",      "higher_better"),
    ("sortino_ratio",      "Sortino Ratio",     "higher_better"),
    ("calmar_ratio",       "Calmar Ratio",      "higher_better"),
    ("max_drawdown_pct",   "Max Drawdown %",    "lower_abs_better"),
    ("win_rate",           "Win Rate %",        "higher_better"),
    ("profit_factor",      "Profit Factor",     "higher_better"),
    ("num_trades",         "Number of Trades",  "neutral"),
    ("final_equity",       "Final Equity",      "higher_better"),
    ("total_fees_paid",    "Total Fees Paid",   "lower_better"),
]


# ── Stage 1 — Critique + Improve ──────────────────────────────────────────────

_CRITIQUE_SYSTEM = f"""You are a quantitative trading strategy reviewer.

You will be given:
  - The Strategy IR (JSON) that was actually backtested.
  - The REAL, engine-computed performance metrics from that backtest.
  - The reel-extraction gaps (constraints the extractor could not express).

Your job:
1. Identify concrete, EVIDENCE-BASED problems using ONLY the numbers given
   (e.g. "0 trades — entry conditions never triggered", "Sharpe -0.3 with
   36% max drawdown — no stop loss set", "high win rate but negative
   expectancy — profit_factor < 1 means losers are bigger than winners",
   "only 3 trades over the period — thresholds too tight to be
   statistically meaningful"). Do NOT invent problems not supported by the
   data. Do NOT claim any specific improved number — you cannot know the
   outcome of a change until it is actually re-backtested.
2. Propose a MODIFIED Strategy IR ("improved_ir") that structurally
   addresses each problem you named. Valid moves:
   - Add/adjust stop_loss_pct / take_profit_pct
   - Loosen or tighten indicator thresholds that caused too few / too many trades
   - Add a trend or volatility filter rule to reduce whipsaws
   - Adjust invest_per_trade_usd / position sizing
   - Change indicator periods (e.g. RSI length, EMA periods) if evidence supports it
   You MUST keep the same "strategy" IR shape/schema as the input. Only use
   indicators from this catalog:
{_INDICATOR_KEYS}
   Do not change entry/exit rule COUNT drastically — make targeted, explainable edits.
3. List each change you made as {{"field": "<param path>", "before": <val>, "after": <val>, "reason": "<why, tied to a named problem>"}}.

Be conservative: prefer 1-4 targeted changes over a full rewrite. Never suggest something
the engine cannot express (only fields in the schema below).

Reply with ONLY valid JSON (no markdown):
{{
  "problems": ["<concrete evidence-based problem>", ...],
  "changes":  [{{"field": "...", "before": "...", "after": "...", "reason": "..."}}, ...],
  "improved_ir": {{"strategy": "<NAME>", "params": {{...}}}},
  "confidence": 0.0-1.0
}}"""


def critique_and_improve(
    ir: dict[str, Any],
    metrics: dict[str, Any],
    gaps: list[str] | None = None,
    symbol: str = "",
    interval: str = "1d",
) -> dict[str, Any]:
    """
    Single LLM call: name real problems in the original backtest and propose
    a structurally-improved IR. Returns {problems, changes, improved_ir, confidence}
    or {..., error} on failure. Caller is responsible for validating/re-running
    `improved_ir` — this function never fabricates outcome numbers.
    """
    payload = {
        "symbol":   symbol,
        "interval": interval,
        "strategy_ir": ir,
        "actual_metrics": {
            "total_return_pct":      metrics.get("total_return_pct"),
            "annualised_return_pct": metrics.get("annualised_return_pct"),
            "sharpe_ratio":          metrics.get("sharpe_ratio"),
            "sortino_ratio":         metrics.get("sortino_ratio"),
            "max_drawdown_pct":      metrics.get("max_drawdown_pct"),
            "calmar_ratio":          metrics.get("calmar_ratio"),
            "win_rate":              metrics.get("win_rate"),
            "profit_factor":         metrics.get("profit_factor"),
            "num_trades":            metrics.get("num_trades"),
            "final_equity":          metrics.get("final_equity"),
            "initial_capital":       metrics.get("initial_capital"),
        },
        "extraction_gaps": gaps or [],
    }
    try:
        raw    = _llm(_CRITIQUE_SYSTEM, json.dumps(payload, indent=2), max_tokens=1600)
        result = _parse_json(raw)
        return {
            "problems":     result.get("problems", []),
            "changes":      result.get("changes", []),
            "improved_ir":  result.get("improved_ir"),
            "confidence":   float(result.get("confidence", 0.5)),
        }
    except Exception as e:
        logger.error("critique_and_improve failed: %s", e)
        return {"problems": [], "changes": [], "improved_ir": None, "confidence": 0.0, "error": str(e)}


def repair_improved_ir(
    ir: dict[str, Any],
    errors: list[str],
    original_ir: dict[str, Any],
) -> dict[str, Any] | None:
    """One-shot self-repair: feed validator errors back to the LLM and ask for a fix."""
    system = f"""You are a trading strategy IR repair tool. The following Strategy IR
failed schema validation. Fix ONLY the invalid fields — keep every valid part unchanged.
Only use indicators from this catalog:
{_INDICATOR_KEYS}

Reply with ONLY the corrected JSON IR object (no markdown, no wrapper):
{{"strategy": "<NAME>", "params": {{...}}}}"""
    user = json.dumps({"invalid_ir": ir, "validation_errors": errors, "original_ir": original_ir}, indent=2)
    try:
        raw = _llm(system, user, max_tokens=900)
        return _parse_json(raw)
    except Exception as e:
        logger.error("repair_improved_ir failed: %s", e)
        return None


# ── Stage 2 — Diff (pure arithmetic, no LLM) ──────────────────────────────────

def compute_diff(original: dict[str, Any], improved: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic, LLM-free diff between two `results` metric dicts."""
    rows = []
    for key, label, direction in _DIFF_METRICS:
        o = original.get(key)
        i = improved.get(key)
        if o is None or i is None:
            continue
        try:
            o_f, i_f = float(o), float(i)
        except (TypeError, ValueError):
            continue
        delta = i_f - o_f
        pct_change = (delta / abs(o_f) * 100) if o_f != 0 else (None if i_f == 0 else float("inf"))
        if direction == "higher_better":
            better = delta > 0
        elif direction == "lower_better":
            better = delta < 0
        elif direction == "lower_abs_better":
            better = abs(i_f) < abs(o_f)
        else:
            better = None
        rows.append({
            "key": key, "label": label,
            "original": o_f, "improved": i_f,
            "delta": delta,
            "pct_change": (None if pct_change in (float("inf"), float("-inf")) else pct_change),
            "better": better,
        })
    return rows


# ── Stage 3 — Judge (independent audit LLM) ───────────────────────────────────

_JUDGE_SYSTEM = """You are an independent audit LLM overseeing an automated
"reel → backtest → critique → improve" pipeline end-to-end. You did NOT
produce any of the numbers below — the backtest engine computed them
deterministically. Your job is to catch dishonesty, inconsistency, or
overfitting in the PROCESS, not to re-derive numbers yourself.

Check specifically:
1. Does every item in "changes" correspond to an actual, verifiable
   difference between original_ir and improved_ir params? Flag any claimed
   change that isn't actually present in improved_ir.
2. Does every named "problem" have support in original_metrics? Flag
   fabricated or unsupported problems.
3. Is "diff" internally consistent with original_metrics/improved_metrics
   (improved - original == delta, roughly)? Flag if not.
4. Same symbol/date range/capital used for both runs? (given in "config" —
   if config shows the improved run used different market conditions, the
   comparison is invalid — flag it.)
5. Overfitting risk: do the changes look like narrow curve-fitting to this
   exact historical window (e.g. oddly specific thresholds, too many
   simultaneous parameter changes, indicator periods that suspiciously
   match visible price patterns) rather than generalizable improvements?
6. Any indicator/strategy in improved_ir not in the approved catalog?

Reply with ONLY valid JSON (no markdown):
{
  "approved": true|false,
  "issues": ["<specific, cite which check failed and why>", ...],
  "overfit_risk": "low"|"medium"|"high",
  "notes": "<1-3 sentence honest summary for the end user>"
}"""


def judge_pipeline(trace: dict[str, Any]) -> dict[str, Any]:
    """
    Independent audit of the full reel→critique→improve trace.
    `trace` should include: transcript (optional), original_ir, improved_ir,
    problems, changes, original_metrics, improved_metrics, diff, config.
    """
    try:
        raw    = _llm(_JUDGE_SYSTEM, json.dumps(trace, indent=2, default=str), max_tokens=900)
        result = _parse_json(raw)
        return {
            "approved":     bool(result.get("approved", False)),
            "issues":       result.get("issues", []),
            "overfit_risk": result.get("overfit_risk", "medium"),
            "notes":        result.get("notes", ""),
        }
    except Exception as e:
        logger.error("judge_pipeline failed: %s", e)
        return {
            "approved": False,
            "issues": [f"Judge LLM call failed: {e}"],
            "overfit_risk": "unknown",
            "notes": "Judge could not run — treat results as unverified.",
        }
