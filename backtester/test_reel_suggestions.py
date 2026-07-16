"""Tests for reel_extractor.normalize_suggestions — the LLM's suggested
symbol/source/interval must be coerced to the exact values the frontend
selects and the data fetchers accept (live E2E, 2026-07-10: the endpoint
returned symbol="BTCUSD", source="BINANCE" raw, auto-filling the config with
an invalid symbol/source pair)."""
from reel_extractor import normalize_suggestions


def test_live_e2e_case_btcusd_binance():
    sym, src, itv = normalize_suggestions("BTCUSD", "BINANCE", "1d")
    assert (sym, src, itv) == ("BTC/USDT", "binance", "1d")


def test_live_e2e_case_unrecognized_source_variant_still_slashes_symbol():
    """Live UI testing (2026-07-13): LLM said source="Binance (Crypto)"-style
    text outside the alias table; symbol slash-insertion must not depend on
    the source string parsing cleanly — a bare quote-suffixed symbol is
    unambiguously crypto regardless of source phrasing."""
    sym, src, _ = normalize_suggestions("BTCUSD", "some future crypto exchange", "1d")
    assert sym == "BTC/USDT"
    assert src is None  # unknown source alias still degrades to None


def test_binance_symbol_variants():
    assert normalize_suggestions("ethusdt", "binance", None)[0] == "ETH/USDT"
    assert normalize_suggestions("SOLUSDC", "Binance", None)[0] == "SOL/USDC"
    assert normalize_suggestions("BNBBUSD", "binance", None)[0] == "BNB/BUSD"
    assert normalize_suggestions("ETHBTC", "binance", None)[0] == "ETH/BTC"
    # Already-slashed symbols are left alone.
    assert normalize_suggestions("BTC/USDT", "binance", None)[0] == "BTC/USDT"


def test_source_aliases_and_unknown_source():
    assert normalize_suggestions("AAPL", "YAHOO", None)[1] == "yfinance"
    assert normalize_suggestions("AAPL", "yfinance", None)[1] == "yfinance"
    assert normalize_suggestions("RELIANCE", "NSE", None)[1] == "nse"
    assert normalize_suggestions("RELIANCE", "BSE", None)[1] == "bse"
    # Unknown source → None so the frontend keeps its current value.
    assert normalize_suggestions("BTC", "COINBASE", None)[1] is None
    assert normalize_suggestions("BTC", None, None)[1] is None


def test_nse_symbol_strips_exchange_suffix_and_uppercases():
    sym, src, _ = normalize_suggestions("reliance.NS", "nse", None)
    assert (sym, src) == ("RELIANCE", "nse")


def test_yfinance_symbol_uppercased():
    assert normalize_suggestions("aapl", "yahoo", None)[0] == "AAPL"


def test_interval_whitelist():
    assert normalize_suggestions(None, None, "1D")[2] == "1d"
    assert normalize_suggestions(None, None, "4h")[2] == "4h"
    # Not in the supported set → None (frontend keeps its current value).
    assert normalize_suggestions(None, None, "3m")[2] is None
    assert normalize_suggestions(None, None, "daily")[2] is None
    assert normalize_suggestions(None, None, None)[2] is None
