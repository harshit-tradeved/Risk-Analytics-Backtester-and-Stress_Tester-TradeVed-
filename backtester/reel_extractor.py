"""
Reel → Strategy IR Extractor

Two-stage LLM pipeline:
  1. triage()              — cheap single call: is this a testable strategy?
  2. extract_strategy_ir() — two-prompt extraction → strict Strategy IR JSON + gap flags

LLM provider is controlled by LLM_PROVIDER in config / .env:
  LLM_PROVIDER=azure      → Azure OpenAI Responses API (default — GPT-5.3-Codex)
  LLM_PROVIDER=openai     → standard OpenAI Chat Completions (OPENAI_API_KEY + OPENAI_MODEL)
  LLM_PROVIDER=anthropic  → Anthropic Messages API (ANTHROPIC_API_KEY + ANTHROPIC_MODEL)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)


# ── Provider-agnostic LLM call ────────────────────────────────────────────────

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_llm_text(text: str, max_chars: int = 12_000) -> str:
    """
    Strip control characters (NULs etc. — Whisper/OCR output occasionally
    contains these and Azure's Responses API returns a bare 400 with no
    diagnosis-friendly detail for a malformed payload) and cap length so a
    single oversized transcript can't blow the request budget.
    """
    cleaned = _CONTROL_CHAR_RE.sub("", text)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n...[truncated]"
    return cleaned


# Guardrails the top-level shape of extract_strategy_ir's normalize step at
# the API level (structured-output / JSON-schema enforcement) rather than
# relying on prompt instructions the model can ignore. Tonight's live testing
# found the model inventing its own top-level keys (name/version/direction/
# market instead of the required {strategy, params} shape) even after the
# prompt was hardened and an LLM repair retry was added — both are "ask
# nicely" mechanisms the model can still deviate from. A strict schema means
# the API itself rejects any response that doesn't have exactly "strategy"
# (string) and "params" (object) at the top level of strategy_ir; "params"
# "params" is a JSON-ENCODED STRING in this schema, not a nested object.
# Azure/OpenAI strict structured-output mode requires additionalProperties:
# false on every nested object with no exceptions for "I want this one to
# stay open" — tried {"type":"object","additionalProperties":true} first and
# the API rejected the schema outright (400: "additionalProperties is
# required to be supplied and to be false"). params genuinely needs to vary
# per strategy (DCA/GRID/PLA/CUSTOM/indicator-presets all have different
# fields) so enumerating every field for every strategy as a giant strict
# union isn't a maintainable option. Encoding it as a string sidesteps the
# conflict entirely: the OUTER envelope (exactly {strategy, params} and
# nothing else) is fully strict-enforced — that's the actual bug this exists
# to prevent — while params keeps its natural flexibility. Decoded back into
# a dict in _normalize_to_ir/_normalize_to_ir_with_retry after parsing.
NORMALIZE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy_ir": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "strategy": {"type": "string", "enum": sorted(STRATEGY_REGISTRY.keys())},
                        "params": {"type": "string", "description": "JSON-encoded object, e.g. '{\"entry_rules\": [], ...}'"},
                    },
                    "required": ["strategy", "params"],
                    "additionalProperties": False,
                },
            ],
        },
        "gaps": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "suggested_symbol":   {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "suggested_source":   {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "suggested_interval": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": [
        "strategy_ir", "gaps", "confidence",
        "suggested_symbol", "suggested_source", "suggested_interval",
    ],
    "additionalProperties": False,
}


def _decode_params_string(result: dict[str, Any]) -> dict[str, Any]:
    """The schema forces strategy_ir.params to arrive as a JSON string
    (see NORMALIZE_RESPONSE_SCHEMA's comment) — decode it back to a dict
    for every downstream caller that expects the normal IR shape."""
    ir = result.get("strategy_ir")
    if isinstance(ir, dict) and isinstance(ir.get("params"), str):
        try:
            ir["params"] = json.loads(ir["params"])
        except (TypeError, ValueError):
            ir["params"] = {}
    return result


def _llm(system: str, user: str, max_tokens: int = 1200, response_schema: dict | None = None) -> str:
    """
    Call the configured LLM provider with retry-with-backoff on rate limits /
    transient failures. Found via reel_pipeline_test_results_large.xlsx (95-URL
    run): 51/95 rows failed on Azure 429 with no retry — this was the dominant
    failure mode at any real concurrency. Found via reel_pipeline_test_results_100.xlsx
    (148-URL run): a handful of 400s with no diagnosable body — payload is now
    sanitized up front and the Azure branch surfaces the real response body.
    """
    import time as _time
    import random as _random

    system = _sanitize_llm_text(system, max_chars=6_000)
    user   = _sanitize_llm_text(user, max_chars=12_000)

    last_exc: Exception | None = None
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            return _llm_once(system, user, max_tokens, response_schema)
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            is_transient = (
                "429" in msg or "rate limit" in msg or "rate_limit" in msg
                or "timeout" in msg or "503" in msg or "502" in msg or "504" in msg
                or type(e).__name__ in ("RateLimitError", "APIConnectionError", "APITimeoutError")
            )
            if not is_transient or attempt == max_attempts - 1:
                raise
            # Exponential backoff with jitter: 1-2s, 2-4s, 4-8s, 8-16s
            backoff = (2 ** attempt) * (1 + _random.random())
            logger.warning("LLM call failed (attempt %d/%d, transient=%s): %s — retrying in %.1fs",
                            attempt + 1, max_attempts, is_transient, e, backoff)
            _time.sleep(backoff)
    raise last_exc  # unreachable, satisfies type checkers


def _llm_once(system: str, user: str, max_tokens: int = 1200, response_schema: dict | None = None) -> str:
    """Single attempt at calling the configured LLM provider. Returns the response text."""
    from config import (
        LLM_PROVIDER, OPENAI_API_KEY, OPENAI_MODEL,
        ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
        AZURE_API_KEY, AZURE_ENDPOINT, AZURE_MODEL,
    )

    provider = LLM_PROVIDER.lower().strip()

    # ── Azure OpenAI Responses API (GPT-5.3-Codex) ───────────────────────────
    if provider == "azure":
        if not AZURE_API_KEY:
            raise RuntimeError("AZURE_API_KEY is not set in backtester/.env")
        import requests as _req
        # Responses API uses `instructions` (system) + `input` (user) + `max_output_tokens`
        payload = {
            "model":             AZURE_MODEL,
            "instructions":      system,
            "input":             user,
            "max_output_tokens": max_tokens,
        }
        if response_schema is not None:
            payload["text"] = {"format": {
                "type": "json_schema", "name": "extraction_response",
                "strict": True, "schema": response_schema,
            }}
        resp = _req.post(
            AZURE_ENDPOINT,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {AZURE_API_KEY}",
            },
            json=payload,
            timeout=60,
        )
        if not resp.ok:
            # Surface the real response body — resp.raise_for_status() alone gives
            # no diagnosable detail (this is how the 400s in the 148-URL run went
            # unexplained). Content-filter/safety-block 400s are NOT retried by the
            # transient-check above (deliberately — retrying won't change a filter
            # decision), but now at least the cause is visible in logs.
            raise RuntimeError(
                f"{resp.status_code} Client Error: {resp.reason} for url: {AZURE_ENDPOINT} — body: {resp.text[:500]}"
            )
        data = resp.json()
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") in ("output_text", "text"):
                        return part["text"].strip()
        raise RuntimeError(f"Azure: no text in response output: {data}")

    # ── Anthropic ─────────────────────────────────────────────────────────────
    if provider == "anthropic":
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic SDK not installed. Run: pip install anthropic")
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in backtester/.env")
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp   = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()

    # ── OpenAI (standard) ─────────────────────────────────────────────────────
    try:
        import openai
    except ImportError:
        raise RuntimeError("openai SDK not installed. Run: pip install openai")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set in backtester/.env")
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response_format = (
        {"type": "json_schema", "json_schema": {
            "name": "extraction_response", "strict": True, "schema": response_schema,
        }}
        if response_schema is not None else {"type": "json_object"}
    )
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        response_format=response_format,
    )
    return resp.choices[0].message.content.strip()


def _parse_json(raw: str) -> dict:
    """Strip markdown fences if present, then parse JSON."""
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    return json.loads(raw)


# ── Indicator catalog (injected into prompts) ─────────────────────────────────
_INDICATOR_KEYS = """
sma(length) → sma
ema(length) → ema
wma(length) → wma
hma(length) → hma
vwap(length) → vwap
rsi(length) → rsi
macd(fast,slow,signal) → macd, macd_signal, macd_hist
stoch(k,d,smooth_k) → stoch_k, stoch_d
cci(length) → cci
roc(length) → roc
mom(length) → mom
willr(length) → willr
tsi(fast,slow) → tsi
adx(length) → adx, plus_di, minus_di
aroon(length) → aroon_up, aroon_down, aroon_osc
supertrend(length,multiplier) → supertrend, supertrend_dir
psar(step,max_step) → psar
atr(length) → atr
bbands(length,std) → bb_lower, bb_mid, bb_upper, bb_width
keltner(length,multiplier) → kc_lower, kc_mid, kc_upper
donchian(length) → dc_lower, dc_mid, dc_upper
stdev(length) → stdev
obv() → obv
mfi(length) → mfi
cmf(length) → cmf
pivot(length) → pivot, pivot_r1, pivot_r2, pivot_s1, pivot_s2  (classic floor pivot / support-resistance levels)
orb(opening_candles) → orb_high, orb_low  (opening range breakout — intraday intervals only, NOT daily/weekly)
ichimoku(tenkan,kijun,senkou_b) → tenkan_sen, kijun_sen, senkou_a, senkou_b  (Ichimoku cloud; no chikou span)
price columns: open, high, low, close, volume
operators: > >= < <= cross_above cross_below
"""

_KNOWN_PRESETS = {
    "RSI", "MACD", "BOLLINGER", "SUPERTREND", "DONCHIAN", "MACROSS",
    "STOCH_CROSS", "STOCH_OBOS", "CCI_REV", "CCI_TREND", "WILLIAMS",
    "ROC", "MOMENTUM", "TSI", "ADX_TREND", "DI_CROSS", "PSAR",
    "AROON_CROSS", "AROON_OBOS", "SMA_CROSS", "WMA_CROSS", "HMA_CROSS",
    "TRIPLE_EMA", "GOLDEN_CROSS", "VWAP_CROSS", "OBV_TREND", "MFI_OBOS",
    "CMF_ZERO", "KC_BREAK", "ATR_BREAK", "BB_SQUEEZE",
}


# ── Stage 0 — Triage ──────────────────────────────────────────────────────────

_TRIAGE_SYSTEM = """You are a financial content classifier.
Classify the given reel transcript/caption as one of:
  testable_strategy  — contains explicit entry AND exit rules with at least one indicator or price level
  partial_strategy   — mentions indicators but missing entry OR exit rules
  market_commentary  — analysis/opinion with no actionable rules
  motivational       — general trading mindset content
  advertisement      — product/course promotion

CRITICAL RULE: If the text contains explicit, concrete entry conditions (e.g. "buy when RSI < 30", "enter at breakout with high volume", "price above 200 MA") AND explicit exit/risk rules (e.g. "SL 5%", "target 10%", "sell when RSI > 70"), classify as testable_strategy — EVEN IF the post also contains a call-to-action like "comment to get the strategy", "follow me", or "DM for more". The presence of a CTA does NOT override explicit rules.

Reply with ONLY valid JSON (no markdown):
{"type": "<one of above>", "confidence": 0.0-1.0, "reason": "<1 sentence>"}"""


def triage(transcript: str, caption: str = "") -> dict[str, Any]:
    """
    Quick triage: does this reel contain a testable trading strategy?
    Returns: {is_strategy, is_complete, type, confidence, reason}
    """
    # Use up to 2000 chars; send transcript content first so rules aren't truncated by a long caption
    transcript_part = transcript.strip()[:1800]
    caption_part    = caption.strip()[:200]
    snippet = (transcript_part + ("\n\nCaption: " + caption_part if caption_part else "")).strip()
    try:
        data = _parse_json(_llm(_TRIAGE_SYSTEM, snippet, max_tokens=200))
        t = data.get("type", "market_commentary")
        return {
            "is_strategy": t in ("testable_strategy", "partial_strategy"),
            "is_complete": t == "testable_strategy",
            "type":        t,
            "confidence":  float(data.get("confidence", 0.5)),
            "reason":      data.get("reason", ""),
        }
    except Exception as e:
        # A failed/errored LLM call (timeout, 4xx/5xx from the provider, bad JSON)
        # is NOT the same thing as "this content isn't a trading strategy" — it must
        # stay distinguishable so callers don't silently tell the user "no testable
        # strategy found" when the real cause was a provider outage.
        logger.warning("triage failed (provider error, not a real classification): %s", e)
        return {"is_strategy": False, "is_complete": False, "type": "provider_error",
                "confidence": 0.0, "reason": str(e), "provider_error": True}


# ── Stage 1 — Clean & Isolate (Prompt 1) ─────────────────────────────────────

_CLEAN_SYSTEM = f"""You are a trading strategy parser.
Extract ONLY what is explicitly stated in the transcript. Never invent indicators, parameters, or thresholds.

Your task:
1. Repair garbled speech-to-text (e.g. "our aside" → "RSI", "e m a" → "EMA").
2. Strip all narrative, motivation, and promotional text.
3. Extract only actionable rules into these fields:
   - entry_conditions: list of what triggers a buy
   - exit_conditions: list of what triggers a sell/close
   - instrument: specific ticker if visible/mentioned (e.g. NVDA, TSLA, RELIANCE), or asset class, or null
   - timeframe: chart interval e.g. "1d", "4h", "15m" (or null)
   - stop_loss: explicit stop rule (or null)
   - take_profit: explicit profit target (or null)
   - position_size: any sizing rule (or null)

For any field that is vague or absent, use "REQUIRES_SPECIFICATION" instead of guessing.

Available indicators (ONLY use these keys):
{_INDICATOR_KEYS}

Reply with ONLY valid JSON (no markdown):
{{
  "entry_conditions": ["<explicit rule>", ...],
  "exit_conditions": ["<explicit rule>", ...],
  "instrument": "<symbol or REQUIRES_SPECIFICATION>",
  "timeframe": "<interval or REQUIRES_SPECIFICATION>",
  "stop_loss": "<rule or null>",
  "take_profit": "<rule or null>",
  "position_size": "<rule or null>",
  "notes": "<anything ambiguous that the user should review>"
}}"""


def _clean_and_isolate(transcript: str, caption: str = "") -> dict[str, Any]:
    content = f"CAPTION:\n{caption}\n\nTRANSCRIPT:\n{transcript}".strip()
    return _parse_json(_llm(_CLEAN_SYSTEM, content, max_tokens=800))


# ── Stage 2 — Normalize to Strategy IR (Prompt 2) ────────────────────────────

_NORMALIZE_SYSTEM = f"""You are a trading strategy compiler. Your job is to convert structured trading conditions into a runnable Strategy IR JSON.

IMPORTANT — MANDATORY OUTPUT RULE: If the input describes ANY identifiable
entry logic (even one condition), you MUST emit a non-null strategy_ir.
"gaps" is informational only — it tells the user what was approximated or
defaulted, it must NEVER be a reason to withhold strategy_ir. A strategy_ir
with sensible defaults filled in and a long "gaps" list is always the
correct output. Only withhold strategy_ir (set it to null) when there is
truly zero identifiable entry condition anywhere in the input — that case
should be rare, since triage already filtered out non-strategy content
before this step ever runs.

Fill every gap you possibly can using the approved approximations below,
and when NONE of them apply, fall back to the MANDATORY DEFAULTS section
at the end rather than leaving a field unset.

═══ APPROVED GAP-FILLING PATTERNS ═══
Use these instead of adding to gaps:

Volatility contraction / VCP / range tightening / squeeze:
  → entry rule: atr(5) < atr(20)  [short ATR below long ATR = contracting volatility]

High volume on breakout / volume surge confirmation:
  → entry rule: cmf(20) > 0   [positive Chaikin Money Flow = buying pressure]
  OR: mfi(14) > 60  [Money Flow Index > 60 = bullish volume pressure]

% Stop loss (e.g. "5% stop loss", "SL at 5%"):
  → set params.stop_loss_pct = <number>  [NOT a rule — the engine handles it natively]

% Take profit (e.g. "10% target", "TP at 10%", "1:2 risk-reward with 5% SL"):
  → set params.take_profit_pct = <number>  [NOT a rule — the engine handles it natively]
  → For 1:N risk-reward: take_profit_pct = stop_loss_pct * N

RSI confirming momentum on breakout (momentum confirmation):
  → entry rule: rsi(14) > 50

Price above MA for trend filter ("above 200 MA", "above 50 EMA"):
  → entry rule: close > sma(200)  or  close > ema(50)

Donchian/Turtle breakout ("breakout of 20-period high"):
  → entry rule: close cross_above donchian(20) output dc_upper
  → exit rule:  close cross_below donchian(10) output dc_lower  [Turtle exit = 10-period low]

Support/resistance zones, "price rejected at a level", pivot-based S/R trading:
  → entry rule: close cross_above pivot(1) output pivot_r1  [breakout above resistance]
  → OR: close cross_below pivot(1) output pivot_s1  [breakdown below support — for a short-style exit/reversal]
  → Increase pivot's `length` param for a longer look-back S/R level (e.g. length=5 for a
    weekly-equivalent pivot on daily candles) instead of adding to gaps for "recent swing high/low".

Opening Range Breakout / ORB (only valid on intraday intervals — 1m/5m/15m/30m/1h/4h, NOT 1d/1w):
  → entry rule: close cross_above orb(15) output orb_high
  → exit rule:  close cross_below orb(15) output orb_low
  → If the transcript describes ORB but suggested_interval would be "1d", set suggested_interval
    to "15m" or "1h" instead (ORB is meaningless on daily candles — there's no intraday session).

Ichimoku Cloud strategy ("TK cross", "price above/below the cloud", "cloud breakout"):
  → TK cross entry rule: ichimoku() output tenkan_sen cross_above ichimoku() output kijun_sen
  → Cloud breakout entry rule: close cross_above ichimoku() output senkou_a

Dynamic/rolling-price stop loss ("low of previous N candles", "recent swing low",
"below the last N-candle low", trailing stop that follows price):
  → exit rule: close cross_below donchian({{"length": N or 10}}) output dc_lower
  → (mirror for shorts: close cross_above donchian({{"length": N or 10}}) output dc_upper)
  → ALSO set stop_loss_pct to a conservative numeric estimate (see MANDATORY DEFAULTS)
    so the engine still has a hard percent-based backstop even with the rule-based exit.

Risk:reward ratio target when the stop isn't a flat percent (e.g. "1:2 R:R",
"risk 1 to make 2", target based on stop distance):
  → Approximate stop_loss_pct using the MANDATORY DEFAULTS value, then
    take_profit_pct = stop_loss_pct * N (the ratio's second number).

Position sizing described as "% risk per trade" (e.g. "risk 1% per trade") rather
than a flat dollar amount:
  → Convert to invest_per_trade_usd using the MANDATORY DEFAULTS capital assumption:
    invest_per_trade_usd = round(10000 * risk_pct / 100 * 10)  [i.e. size the position
    so a full stop-out roughly matches the stated risk fraction of a $10,000 account]
  → If the risk % itself isn't numeric either, just use invest_per_trade_usd = 1000.

Custom/proprietary/branded indicator names not in the catalog (e.g. a named
"XYZ Oscillator", "ABC Trend Ribbon", a creator's own indicator brand):
  → NEVER add these to gaps or drop the condition. Approximate using the closest
    catalog indicator by DESCRIBED BEHAVIOR, not name:
    - described as trend-strength / trend-following / "ribbon" / directional →
      supertrend() or adx() or ema(50)/ema(200) crossover
    - described as momentum / oscillator swinging between bounds →
      rsi(14) or stochastic() or roc()
    - described as volatility / squeeze / bands →
      bollinger() or atr() or keltner()
    - described as volume / money flow →
      obv() or cmf(20) or mfi(14)
  → State the approximation in "gaps" for transparency, but ALWAYS still include
    the approximated rule in entry_rules/exit_rules — do not omit the condition.

Vague/ambiguous stop-loss description with no number ("stop above the crossover",
"stop below the trend line", "tight stop", any qualitative-only stop):
  → set stop_loss_pct to the MANDATORY DEFAULTS value. Note the approximation in gaps.

Ambiguous or filler timeframe mention ("the time frame", "this timeframe", "on the
chart" with no concrete unit):
  → suggested_interval = "1d" (same as when timeframe is unmentioned entirely).
    Never add timeframe to gaps merely for being vague — only if a specific,
    unresolvable custom timeframe is explicitly demanded.

═══ IR SCHEMA — FOLLOW EXACTLY, NO EXCEPTIONS ═══

strategy_ir has EXACTLY two top-level keys, always: "strategy" and "params".
Never add any other top-level key (no "name", "version", "market", "direction",
"instrument" at the top level, etc.) — anything beyond entry/exit rules and the
numeric params below belongs in "gaps" as prose, not as a new JSON field.

IMPORTANT: the response schema requires "params" to be a JSON-encoded STRING
(e.g. "{{\\"entry_rules\\": [], \\"stop_loss_pct\\": 3}}"), not a nested JSON
object — serialize whatever params object you'd otherwise write as a string.

(A) Known preset if conditions match exactly:
    {{"strategy": "<NAME>", "params": {{...}}}}
    Known presets: {sorted(_KNOWN_PRESETS)}

(B) CUSTOM strategy for everything else:
    {{
      "strategy": "CUSTOM",
      "params": {{
        "entry_rules": [<rule>, ...],
        "exit_rules":  [<rule>, ...],   // can be empty [] if no explicit rule exit
        "logic": "AND",
        "invest_per_trade_usd": 1000,
        "stop_loss_pct":   0,           // set > 0 if stop loss % mentioned
        "take_profit_pct": 0            // set > 0 if take profit % mentioned
      }}
    }}
    entry_rules/exit_rules live INSIDE "params", never as top-level siblings of "params".

Rule shape — use these EXACT field names, no substitutes:
  {{"left": {{"indicator":"<key>","params":{{}},"output":"<col>"}}, "operator":"<op>", "right": {{"value":<n>}}}}
  Use {{"price": "close"}} to reference a raw price column.
  The comparison field is ALWAYS named "operator" (never "op"). Indicator references are
  ALWAYS named "indicator" (never "type"/"name" nesting). Do not restructure this shape.

Available indicators:
{_INDICATOR_KEYS}

═══ INSTRUMENT & TIMEFRAME DETECTION ═══
Also extract from the content:
- suggested_symbol: the ticker/asset most appropriate for this strategy
  - FIRST priority: if any specific ticker/stock name is explicitly shown on screen or spoken (e.g. NVDA, TSLA, RELIANCE, INFY, BANKNIFTY, AAPL) → use THAT exact ticker symbol
  - If general crypto strategy with no specific coin → "BTC/USDT"
  - If general Indian equity/index strategy with no specific stock → "NIFTY50"
  - If general US equity strategy with no specific ticker identified → null
  - Never substitute a placeholder ticker when a real one is visible or mentioned
  - For forex/commodities (e.g. gold, silver, EUR/USD): the backend now normalizes
    common jargon tickers (XAUUSD, EURUSD, WTI, ...) to Yahoo Finance format
    automatically, so plain jargon tickers like "XAUUSD" are fine to suggest
- suggested_source: "binance" | "yfinance" | "nse" | "bse" — infer from asset class
- suggested_interval: map timeframe to one of: "1m","3m","5m","15m","30m","1h","4h","1d","1w"
  - If not mentioned → "1d"

═══ MANDATORY DEFAULTS ═══
Apply these whenever a field is unspecified or only qualitatively described —
they exist so strategy_ir is NEVER null just because one field lacked an
exact number. Always list what you defaulted in "gaps" for transparency.
- invest_per_trade_usd → 1000
- stop_loss_pct        → 3    (conservative short-term default)
- take_profit_pct      → 6    (2:1 reward:risk against the default stop)
- suggested_interval   → "1d"
- entry_rules / exit_rules → [] is acceptable ONLY if genuinely no rule-based
  condition exists AND stop_loss_pct/take_profit_pct alone define the trade;
  never use [] as a way to avoid approximating a described condition.

═══ RULES ═══
- Only use indicators in the catalog above. Never invent new ones.
- Apply every approved gap-filling pattern before falling back to MANDATORY DEFAULTS.
- strategy_ir must be non-null whenever any entry condition is identifiable — see
  the MANDATORY OUTPUT RULE at the top. Gaps describe approximations, they never
  justify withholding strategy_ir.

Reply with ONLY valid JSON (no markdown):
{{
  "strategy_ir": {{...}},
  "gaps": ["<approximations and defaults applied, for user transparency>", ...],
  "confidence": 0.0-1.0,
  "suggested_symbol": "<ticker or null>",
  "suggested_source": "<binance|yfinance|nse|bse or null>",
  "suggested_interval": "<interval>"
}}"""


def _normalize_to_ir(cleaned: dict[str, Any]) -> dict[str, Any]:
    result = _parse_json(_llm(_NORMALIZE_SYSTEM, json.dumps(cleaned, indent=2), max_tokens=1200,
                               response_schema=NORMALIZE_RESPONSE_SCHEMA))
    return _decode_params_string(result)


_NORMALIZE_RETRY_SYSTEM = _NORMALIZE_SYSTEM + """

═══ RETRY NOTICE ═══
Your previous attempt on this exact input returned strategy_ir: null. That is
not an acceptable output per the MANDATORY OUTPUT RULE above — this input DOES
have an identifiable entry condition. Apply the MANDATORY DEFAULTS section
and any matching APPROVED GAP-FILLING PATTERN to build a working strategy_ir
now. Do not return null again."""


def _normalize_to_ir_with_retry(cleaned: dict[str, Any]) -> dict[str, Any]:
    """
    One deterministic retry if the model still withholds strategy_ir despite
    the prompt's mandatory-output rule — mirrors the same self-repair pattern
    improvement_agent.repair_improved_ir() already uses elsewhere in this
    pipeline (feed the model its own failure, ask it to try again with a
    firmer instruction) rather than giving up on the first null.
    """
    result = _decode_params_string(_parse_json(_llm(
        _NORMALIZE_SYSTEM, json.dumps(cleaned, indent=2), max_tokens=1200,
        response_schema=NORMALIZE_RESPONSE_SCHEMA,
    )))
    if result.get("strategy_ir"):
        return result
    logger.warning("normalize_to_ir returned null strategy_ir, retrying once with firmer instruction")
    retry_result = _decode_params_string(_parse_json(_llm(
        _NORMALIZE_RETRY_SYSTEM, json.dumps(cleaned, indent=2), max_tokens=1200,
        response_schema=NORMALIZE_RESPONSE_SCHEMA,
    )))
    return retry_result if retry_result.get("strategy_ir") else result


# ── Public API ────────────────────────────────────────────────────────────────

def extract_strategy_ir(transcript: str, caption: str = "") -> dict[str, Any]:
    """
    Full two-prompt extraction pipeline.
    Returns:
      {
        "strategy_ir": {...},   # ready to POST to /api/strategy/from-ir
        "gaps": [...],          # REQUIRES_SPECIFICATION items for user to fill
        "confidence": 0-1,
        "cleaned": {...},       # intermediate cleaned conditions
        "error": "..."          # present only on failure
      }
    """
    try:
        cleaned = _clean_and_isolate(transcript, caption)
    except Exception as e:
        logger.error("extract P1 failed: %s", e)
        return {"strategy_ir": None, "gaps": [], "confidence": 0.0, "error": str(e)}

    try:
        result = _normalize_to_ir_with_retry(cleaned)
    except Exception as e:
        logger.error("extract P2 failed: %s", e)
        return {"strategy_ir": None, "gaps": [], "confidence": 0.0,
                "cleaned": cleaned, "error": str(e)}

    return {
        "strategy_ir":        result.get("strategy_ir"),
        "gaps":               result.get("gaps", []),
        "confidence":         float(result.get("confidence", 0.5)),
        "cleaned":            cleaned,
        "suggested_symbol":   result.get("suggested_symbol"),
        "suggested_source":   result.get("suggested_source"),
        "suggested_interval": result.get("suggested_interval"),
    }
