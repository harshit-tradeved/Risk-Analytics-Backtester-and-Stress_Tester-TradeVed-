"""
Regression tests: live E2E run on a forex YouTube video (2026-07-10) — the
extraction LLM suggested symbol "AUDCAD", which isn't in the hardcoded
_FOREX_COMMODITY_MAP, so yfinance got the raw ticker and returned no data.
Any <CCY><CCY> currency pair must map to Yahoo's <CCYCCY>=X format, not just
the handful of pairs someone happened to enumerate.
"""
from backtesting.backend.data.fetcher import YFinanceFetcher, is_forex_pair


def test_to_yf_symbol_generalizes_currency_pairs():
    f = YFinanceFetcher()
    assert f._to_yf_symbol("AUDCAD") == "AUDCAD=X"
    assert f._to_yf_symbol("AUD/CAD") == "AUDCAD=X"
    assert f._to_yf_symbol("gbpjpy") == "GBPJPY=X"
    assert f._to_yf_symbol("EURUSD") == "EURUSD=X"  # was map-only; still works


def test_to_yf_symbol_does_not_mangle_non_forex_symbols():
    f = YFinanceFetcher()
    assert f._to_yf_symbol("AAPL") == "AAPL"
    assert f._to_yf_symbol("BTC/USDT") == "BTC-USD"     # crypto slash pair
    assert f._to_yf_symbol("ETH/USD") == "ETH-USD"      # ETH isn't a fiat code
    assert f._to_yf_symbol("AUDCAD=X") == "AUDCAD=X"    # already yf format
    assert f._to_yf_symbol("GOOGL") == "GOOGL"


def test_is_forex_pair_helper():
    assert is_forex_pair("AUDCAD")
    assert is_forex_pair("aud/cad")
    assert is_forex_pair("USDINR")
    assert not is_forex_pair("BTC/USDT")
    assert not is_forex_pair("RELIANCE")
    assert not is_forex_pair("AAPL")
