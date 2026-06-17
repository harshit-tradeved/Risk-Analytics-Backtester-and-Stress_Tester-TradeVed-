"""
Data Fetcher — pulls OHLCV candles from multiple sources:
  1. Binance REST API  (no auth needed for public klines)
  2. yfinance          (stocks / forex / crypto / Indian markets)
  3. NSE (India)       — yfinance with .NS suffix + Indian symbol resolution
  4. BSE (India)       — yfinance with .BO suffix + Indian symbol resolution

All methods return a pandas DataFrame with columns:
  timestamp | open | high | low | close | volume

Indian symbol auto-resolution examples:
  "RELIANCE"  + source="nse"  →  yfinance ticker "RELIANCE.NS"
  "TCS"       + source="bse"  →  yfinance ticker "TCS.BO"
  "NIFTY50"   + source="nse"  →  yfinance ticker "^NSEI"
  "GOLDBEES"  + source="nse"  →  yfinance ticker "GOLDBEES.NS"
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Literal, Optional

import pandas as pd
import requests

from data.indian_assets import to_yf_symbol as _indian_to_yf

# TradingView / Fyers credentials — set in config.py or via env vars
try:
    from config import (
        TV_USERNAME        as _TV_USERNAME,
        TV_PASSWORD        as _TV_PASSWORD,
        TV_AUTH_TOKEN      as _TV_AUTH_TOKEN,
        TV_SESSIONID       as _TV_SESSIONID,
        FYERS_CLIENT_ID    as _FYERS_CLIENT_ID,
        FYERS_ACCESS_TOKEN as _FYERS_ACCESS_TOKEN,
    )
except ImportError:
    _TV_USERNAME        = ""
    _TV_PASSWORD        = ""
    _TV_AUTH_TOKEN      = ""
    _TV_SESSIONID       = ""
    _FYERS_CLIENT_ID    = ""
    _FYERS_ACCESS_TOKEN = ""
    _TV_SESSIONID  = ""


def _get_tv_token_from_session(sessionid: str) -> str:
    """
    Exchange a TradingView sessionid cookie for the WebSocket auth_token JWT.
    Works for Google OAuth users who don't have auth_token set directly.
    TradingView embeds the auth_token in every page's HTML for logged-in users.
    """
    import re
    try:
        resp = requests.get(
            "https://www.tradingview.com/",
            cookies={"sessionid": sessionid},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
        )
        # TV embeds: "auth_token":"eyJ..." inside a JSON blob in the page HTML
        m = re.search(r'"auth_token"\s*:\s*"([^"]{20,})"', resp.text)
        if m:
            token = m.group(1)
            logger.info("tvdatafeed: extracted auth_token from TradingView page (sessionid auth)")
            return token
        logger.warning("tvdatafeed: sessionid valid but auth_token not found in page HTML")
    except Exception as exc:
        logger.warning("tvdatafeed: sessionid→token extraction failed: %s", exc)
    return ""

logger = logging.getLogger(__name__)

# ── Interval helpers ──────────────────────────────────────────────────────────
BINANCE_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _to_ms(dt: datetime) -> int:
    """Convert datetime → millisecond UNIX timestamp."""
    return int(dt.timestamp() * 1000)

def _normalize_symbol_binance(symbol: str) -> str:
    """'BTC/USDT' → 'BTCUSDT'"""
    return symbol.replace("/", "").replace("-", "").upper()

def _base_currency(symbol: str) -> str:
    """'BTC/USDT' → 'BTC'"""
    return symbol.split("/")[0].upper()


# ─────────────────────────────────────────────────────────────────────────────
# Binance Fetcher
# ─────────────────────────────────────────────────────────────────────────────

class BinanceFetcher:
    # api.binance.com is geo-blocked (HTTP 451) from many datacenter IPs (e.g. cloud
    # hosts). data-api.binance.vision is Binance's public market-data mirror — same
    # /api/v3/klines contract, no geo-restriction. Override via BINANCE_BASE_URL in
    # production (Railway/cloud); local dev keeps the default.
    BASE_URL = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
    MAX_CANDLES_PER_REQUEST = 1000

    def fetch(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch OHLCV klines from Binance public REST API.
        Automatically paginates if the date range spans >1000 candles.
        """
        binance_sym = _normalize_symbol_binance(symbol)
        binance_interval = BINANCE_INTERVAL_MAP.get(interval, "1d")

        url = f"{self.BASE_URL}/api/v3/klines"
        all_records: list[list] = []

        current_start = start_date
        while current_start < end_date:
            params = {
                "symbol":    binance_sym,
                "interval":  binance_interval,
                "startTime": _to_ms(current_start),
                "endTime":   _to_ms(end_date),
                "limit":     self.MAX_CANDLES_PER_REQUEST,
            }
            data = None
            for attempt in range(3):
                try:
                    resp = requests.get(url, params=params, timeout=20)
                    resp.raise_for_status()
                    data = resp.json()
                    if data:
                        break
                    # Empty response — transient rate-limit window; retry with backoff
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        logger.warning("Binance empty response for %s (attempt %d/3), retrying in %ds", symbol, attempt + 1, wait)
                        time.sleep(wait)
                except requests.RequestException as exc:
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        logger.warning("Binance request failed (attempt %d/3): %s. Retrying in %ds", attempt + 1, exc, wait)
                        time.sleep(wait)
                    else:
                        logger.error("Binance request failed after 3 attempts: %s", exc)
            if not data:
                break

            all_records.extend(data)

            # Advance start to the last candle's close time + 1 ms
            last_open_ms = data[-1][0]
            current_start = datetime.utcfromtimestamp(last_open_ms / 1000) + timedelta(milliseconds=1)

            if len(data) < self.MAX_CANDLES_PER_REQUEST:
                break  # no more pages

            time.sleep(0.05)   # respect rate limits

        if not all_records:
            raise ValueError(f"No data returned from Binance for {symbol} [{start_date} – {end_date}]")

        df = pd.DataFrame(all_records, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ])

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        df.sort_values("timestamp", inplace=True)
        df.drop_duplicates("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        logger.info("Binance: fetched %d candles for %s", len(df), symbol)
        return df



# ─────────────────────────────────────────────────────────────────────────────
# Synthetic Intraday Generator
# ─────────────────────────────────────────────────────────────────────────────

class SyntheticIntradayGenerator:
    """
    Generates synthetic intraday OHLCV candles from daily OHLCV data.

    Technique: Brownian Bridge disaggregation.
      - For each daily candle, generates N sub-candles using a geometric
        Brownian bridge that starts at the daily Open, ends at the daily Close,
        and is scaled so the path touches the daily High and Low exactly once.
      - Volume is distributed with a U-shaped intraday profile (more at open/close).

    This is a standard backtesting technique when real intraday data is unavailable.
    The synthetic paths are statistically consistent with daily OHLCV and preserve
    trend and volatility characteristics that matter for strategy simulation.
    """

    # NSE market hours: 9:15 AM to 3:30 PM IST
    _NSE_START_MINUTES = 9 * 60 + 15   # 555 minutes from midnight
    _CANDLES: dict[str, int] = {
        "1m": 375, "5m": 75, "15m": 26, "30m": 13, "1h": 7, "4h": 2,
    }
    _MINUTES: dict[str, int] = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240,
    }

    def generate(
        self,
        daily_df: pd.DataFrame,
        interval:  str = "15m",
        seed:      int = 42,
    ) -> pd.DataFrame:
        """
        Convert a daily OHLCV DataFrame → synthetic intraday OHLCV DataFrame.

        daily_df must have columns: timestamp, open, high, low, close, volume
        Returns a DataFrame with the same columns but at `interval` granularity.
        """
        import numpy as np

        n_sub  = self._CANDLES.get(interval, 26)
        step_m = self._MINUTES.get(interval, 15)
        rng    = np.random.default_rng(seed)

        all_rows: list[dict] = []

        for _, day in daily_df.iterrows():
            day_ts  = pd.Timestamp(day["timestamp"])
            d_open  = float(day["open"])
            d_close = float(day["close"])
            d_high  = float(day["high"])
            d_low   = float(day["low"])
            d_vol   = float(day["volume"])

            if d_open <= 0 or d_high < d_low:
                continue

            # ── Brownian Bridge from open to close ────────────────────────────
            # Generate a standard bridge: w[0]=0, w[n]=1
            increments = rng.normal(0, 1, n_sub)
            bridge     = np.cumsum(increments)
            # Force endpoints: bridge[0]=0, bridge[-1]=target
            target_log = np.log(d_close / d_open)
            daily_vol_est = max(0.001, np.log(d_high / d_low))
            bridge_scaled = bridge * (daily_vol_est / (np.std(bridge) + 1e-9))
            # Shift so it ends at target_log
            bridge_scaled += np.linspace(0, target_log - bridge_scaled[-1], n_sub)

            # Convert log-returns to prices
            prices = d_open * np.exp(np.cumsum(bridge_scaled))
            prices[0] = d_open
            prices[-1] = d_close

            # ── Scale so path hits daily high and low exactly ─────────────────
            p_max = prices.max()
            p_min = prices.min()
            rng_p = p_max - p_min
            if rng_p > 1e-8:
                prices = (prices - p_min) / rng_p * (d_high - d_low) + d_low
            # Restore open/close exactly after scaling
            prices[0]  = d_open
            prices[-1] = d_close

            # ── U-shaped volume profile (more volume at open and close) ───────
            t_norm  = np.linspace(0, 1, n_sub)
            vol_wts = 0.4 + 0.6 * (1 - np.sin(np.pi * t_norm)) ** 2
            vol_wts = vol_wts / vol_wts.sum()
            vols    = d_vol * vol_wts * rng.uniform(0.7, 1.3, n_sub)

            # ── Build OHLC per sub-candle ─────────────────────────────────────
            for i in range(n_sub):
                sub_open  = d_open if i == 0 else prices[i - 1]
                sub_close = prices[i]
                noise_pct = daily_vol_est / n_sub * 0.4
                sub_high  = max(sub_open, sub_close) * (1 + abs(float(rng.normal(0, noise_pct))))
                sub_low   = min(sub_open, sub_close) * (1 - abs(float(rng.normal(0, noise_pct))))

                # Clamp to daily range
                sub_high = min(sub_high, d_high)
                sub_low  = max(sub_low,  d_low)
                sub_high = max(sub_high, max(sub_open, sub_close))
                sub_low  = min(sub_low,  min(sub_open, sub_close))

                ts = day_ts + pd.Timedelta(minutes=self._NSE_START_MINUTES + i * step_m)
                all_rows.append({
                    "timestamp": ts,
                    "open":      round(sub_open,  2),
                    "high":      round(sub_high,  2),
                    "low":       round(sub_low,   2),
                    "close":     round(sub_close, 2),
                    "volume":    max(0.0, round(float(vols[i]), 0)),
                })

        df = pd.DataFrame(all_rows)
        if not df.empty:
            df.sort_values("timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)
        logger.info(
            "SyntheticIntraday: %d daily candles → %d %s candles",
            len(daily_df), len(df), interval,
        )
        return df


# ─────────────────────────────────────────────────────────────────────────────
# yfinance Fetcher
# ─────────────────────────────────────────────────────────────────────────────

class YFinanceFetcher:
    """Fetches OHLCV data using yfinance (stocks, ETFs, BTC-USD, etc.)."""

    INTERVAL_MAP = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "4h": "1h",  # yfinance doesn't support 4h natively
        "1d": "1d", "1w": "1wk",
    }

    # yfinance only serves intraday data for recent windows
    _MAX_DAYS: dict[str, int] = {
        "1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "90m": 60, "1h": 730,
    }

    @classmethod
    def _clamp_interval(cls, yf_interval: str, days: int) -> str:
        """Downgrade yf interval when date range exceeds what yfinance supports."""
        max_days = cls._MAX_DAYS.get(yf_interval)
        if max_days is None or days <= max_days:
            return yf_interval
        if days <= 730:
            logger.warning(
                "yfinance: interval %s supports only %d days; date range=%d days — falling back to 1h",
                yf_interval, max_days, days,
            )
            return "1h"
        logger.warning(
            "yfinance: interval %s supports only %d days; date range=%d days — falling back to 1d",
            yf_interval, max_days, days,
        )
        return "1d"

    def _to_yf_symbol(self, symbol: str, exchange: str = "") -> str:
        """
        Convert a symbol to yfinance ticker format.

        Handles:
          'BTC/USDT'         → 'BTC-USD'
          'AAPL'             → 'AAPL'        (US stocks — pass-through)
          'RELIANCE.NS'      → 'RELIANCE.NS' (already yfinance format)
          '^NSEI'            → '^NSEI'       (indices — pass-through)
        """
        s = symbol.strip()
        # Already in yfinance format
        if s.endswith(".NS") or s.endswith(".BO") or s.startswith("^"):
            return s
        # Crypto pairs: 'BTC/USDT' → 'BTC-USD'
        if "/" in s:
            base, quote = s.split("/")
            quote = "USD" if quote.upper() == "USDT" else quote
            return f"{base}-{quote}"
        return s

    def fetch(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ImportError("Install yfinance: pip install yfinance") from exc

        yf_sym      = self._to_yf_symbol(symbol)
        yf_interval = self.INTERVAL_MAP.get(interval, "1d")
        date_days   = max(1, (end_date - start_date).days)
        yf_interval = self._clamp_interval(yf_interval, date_days)

        ticker = yf.Ticker(yf_sym)
        raw = ticker.history(
            start=start_date.strftime("%Y-%m-%d"),
            end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval=yf_interval,
            auto_adjust=True,
        )

        if raw.empty:
            raise ValueError(f"yfinance returned no data for {symbol}")

        df = raw.reset_index()
        ts_col = "Datetime" if "Datetime" in df.columns else "Date"
        df.rename(columns={
            ts_col:  "timestamp",
            "Open":  "open",
            "High":  "high",
            "Low":   "low",
            "Close": "close",
            "Volume":"volume",
        }, inplace=True)

        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # Surface interval substitutions (4h→1h, range-clamped 15m→1h/1d) so
        # callers can warn the user instead of silently mislabeling results.
        _rev = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "1d": "1d", "1wk": "1w"}
        eff = _rev.get(yf_interval, yf_interval)
        if eff != interval:
            df.attrs["effective_interval"] = eff

        logger.info("yfinance: fetched %d candles for %s", len(df), symbol)
        return df


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# OpenChart Fetcher (NSE charting API — ~10 years free, no login)
# ─────────────────────────────────────────────────────────────────────────────

class FyersDataFetcher:
    """
    Fetches OHLCV data from Fyers API v3.
    Provides ~9 years of NSE/BSE intraday history at no cost (free demat account).

    Setup:
      1. Create app at fyers.in/api-dashboard → get client_id + secret_key
      2. Run: python fyers_auth.py  (once per day — generates access_token)
      3. Set FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN in backtester/.env

    Chunks requests into 100-day windows (Fyers intraday limit per request).
    """

    # Fyers resolution codes for intraday intervals
    _RESOLUTION: dict[str, str] = {
        "1m": "1", "2m": "2", "3m": "3", "5m": "5", "10m": "10",
        "15m": "15", "20m": "20", "30m": "30", "1h": "60", "2h": "120",
        "4h": "240", "1d": "D",
    }

    # Symbol format: "NSE:SYMBOL-EQ" for equities, "NSE:NIFTY50-INDEX" for indices
    _INDEX_SYMBOLS: set[str] = {
        "NIFTY50", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX",
        "NIFTYBANK", "NIFTY BANK", "^NSEI", "^NSEBANK",
    }
    _INDEX_SUFFIX: dict[str, str] = {
        "NIFTY50":   "NSE:NIFTY50-INDEX",
        "NIFTY":     "NSE:NIFTY50-INDEX",
        "^NSEI":     "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
        "NIFTYBANK": "NSE:NIFTYBANK-INDEX",
        "^NSEBANK":  "NSE:NIFTYBANK-INDEX",
        "FINNIFTY":  "NSE:FINNIFTY-INDEX",
        "SENSEX":    "BSE:SENSEX-INDEX",
    }

    def _fyers_symbol(self, symbol: str, exchange: str) -> str:
        upper = symbol.upper()
        if upper in self._INDEX_SUFFIX:
            return self._INDEX_SUFFIX[upper]
        ex = exchange.upper()
        return f"{ex}:{upper}-EQ"

    def fetch(
        self,
        symbol:     str,
        exchange:   str,
        start_date: datetime,
        end_date:   datetime,
        interval:   str = "15m",
        client_id:     str = "",
        access_token:  str = "",
    ) -> pd.DataFrame:
        try:
            from fyers_apiv3 import fyersModel
        except ImportError:
            raise ImportError("Install fyers-apiv3: pip install fyers-apiv3")

        cid   = client_id    or _FYERS_CLIENT_ID
        token = access_token or _FYERS_ACCESS_TOKEN
        if not cid or not token:
            raise ValueError("FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN must be set — run fyers_auth.py")

        res = self._RESOLUTION.get(interval)
        if res is None:
            raise ValueError(f"Fyers does not support interval '{interval}'")

        sym = self._fyers_symbol(symbol, exchange)
        fyers = fyersModel.FyersModel(client_id=cid, token=token, is_async=False, log_path="")

        # Chunk into 100-day windows (Fyers intraday limit)
        chunk_days = 100
        chunks: list[tuple[datetime, datetime]] = []
        cur = start_date
        while cur < end_date:
            chunk_end = min(cur + timedelta(days=chunk_days), end_date)
            chunks.append((cur, chunk_end))
            cur = chunk_end + timedelta(days=1)

        logger.info("fyers: fetching %s [%s] %d chunks (%s → %s)",
                    sym, interval, len(chunks), start_date.date(), end_date.date())

        frames: list[pd.DataFrame] = []
        for c_start, c_end in chunks:
            data = {
                "symbol":      sym,
                "resolution":  res,
                "date_format": "1",
                "range_from":  c_start.strftime("%Y-%m-%d"),
                "range_to":    c_end.strftime("%Y-%m-%d"),
                "cont_flag":   "1",
            }
            resp = fyers.history(data=data)
            if resp.get("s") != "ok" or not resp.get("candles"):
                logger.debug("fyers: no candles for chunk %s → %s", c_start.date(), c_end.date())
                continue
            df_chunk = pd.DataFrame(
                resp["candles"],
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df_chunk["timestamp"] = pd.to_datetime(df_chunk["timestamp"], unit="s")
            frames.append(df_chunk)

        if not frames:
            raise ValueError(f"Fyers returned no data for {sym} [{interval}]. Token may be expired — run fyers_auth.py")

        df = pd.concat(frames, ignore_index=True)
        df.drop_duplicates(subset=["timestamp"], inplace=True)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        logger.info("fyers: %d candles for %s [%s]", len(df), sym, interval)
        return df


class OpenChartFetcher:
    """
    Wraps the `openchart` package (v0.2+) which uses NSE's own public charting API.
    Provides multi-year intraday history for NSE/BSE symbols at no cost.
    No login or broker account required.

    pip install openchart

    API: NSEData.historical(symbol, segment, start, end, interval)
      segment='IDX' for indices, 'EQ' for equities, 'FO' for futures/options
    """

    # openchart interval → NSE charting interval (only these are valid)
    _INTERVAL_MAP: dict[str, str] = {
        "1m": "1m", "5m": "5m", "10m": "10m",
        "15m": "15m", "30m": "30m", "1h": "1h",
        "1d": "1d", "1w": "1w",
    }

    # Symbols that are indices → segment='IDX'
    _INDEX_SYMBOLS: set[str] = {
        "NIFTY50", "NIFTY", "NIFTY 50",
        "BANKNIFTY", "NIFTY BANK", "^NSEI", "^NSEBANK",
        "FINNIFTY", "NIFTY FIN SERVICE",
        "MIDCPNIFTY", "SENSEX",
    }

    # NSE display-name overrides  (our symbol → openchart symbol)
    _SYMBOL_MAP: dict[str, str] = {
        "NIFTY50":   "NIFTY 50",
        "^NSEI":     "NIFTY 50",
        "BANKNIFTY": "NIFTY BANK",
        "^NSEBANK":  "NIFTY BANK",
        "FINNIFTY":  "NIFTY FIN SERVICE",
    }

    _nse_data = None  # singleton

    @classmethod
    def _get_nse(cls):
        try:
            from openchart import NSEData
        except ImportError:
            raise ImportError("Install openchart: pip install openchart")
        if cls._nse_data is None:
            cls._nse_data = NSEData()
        return cls._nse_data

    def _segment(self, symbol: str) -> str:
        return "IDX" if symbol.upper() in self._INDEX_SYMBOLS else "EQ"

    def fetch(
        self,
        symbol:     str,
        exchange:   str,
        start_date: datetime,
        end_date:   datetime,
        interval:   str = "15m",
    ) -> pd.DataFrame:
        nse = self._get_nse()
        sym = self._SYMBOL_MAP.get(symbol.upper(), symbol.upper())
        seg = self._segment(symbol)
        ivl = self._INTERVAL_MAP.get(interval)
        if ivl is None:
            raise ValueError(f"openchart does not support interval '{interval}'")

        logger.info("openchart: fetching %s (seg=%s) [%s] %s → %s", sym, seg, ivl, start_date.date(), end_date.date())
        raw = nse.historical(symbol=sym, segment=seg, start=start_date, end=end_date, interval=ivl)

        if raw is None or (hasattr(raw, "empty") and raw.empty):
            raise ValueError(f"openchart returned no data for {sym} [{ivl}]")

        # Normalise: openchart returns a DataFrame indexed by timestamp
        df = raw.reset_index() if raw.index.name else raw.copy()
        df.columns = [c.lower() for c in df.columns]
        ts_col = next((c for c in df.columns if "date" in c or "time" in c), None)
        if ts_col and ts_col != "timestamp":
            df.rename(columns={ts_col: "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].dropna(subset=["close"])
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        logger.info("openchart: %d candles for %s [%s]", len(df), sym, ivl)
        return df


# ─────────────────────────────────────────────────────────────────────────────
# Unified DataFetcher
# ─────────────────────────────────────────────────────────────────────────────

Source = Literal["binance", "yfinance", "nse", "bse", "auto"]


class TvDatafeedFetcher:
    """
    Fetches OHLCV data from TradingView via tvdatafeed (free, no login required).

    Without login: ~10 months of 15m data.
    With a free TradingView account: 2–3 years of 15m data.
    Covers NSE, BSE, and global exchanges.
    """

    # Candles per trading day — used to compute n_bars from date range
    _CANDLES_PER_DAY: dict[str, float] = {
        "1m": 375, "5m": 75, "15m": 26, "30m": 13,
        "1h": 7, "4h": 2, "1d": 1, "1w": 0.2,
    }

    # NSE symbols that differ from the standard name on TradingView
    _NSE_SYMBOL_MAP: dict[str, str] = {
        "NIFTY50": "NIFTY",
        "^NSEI":   "NIFTY",
        "NIFTY":   "NIFTY",
    }

    @classmethod
    def _tv_interval(cls, interval: str):
        try:
            from tvDatafeed import Interval
        except ImportError:
            raise ImportError("Install tvdatafeed: pip install git+https://github.com/rongardF/tvdatafeed.git")
        return {
            "1m":  Interval.in_1_minute,
            "5m":  Interval.in_5_minute,
            "15m": Interval.in_15_minute,
            "30m": Interval.in_30_minute,
            "1h":  Interval.in_1_hour,
            "4h":  Interval.in_4_hour,
            "1d":  Interval.in_daily,
            "1w":  Interval.in_weekly,
        }.get(interval, Interval.in_daily)

    def fetch(
        self,
        symbol:     str,
        exchange:   str,
        start_date: datetime,
        end_date:   datetime,
        interval:   str = "15m",
        username:   str = "",
        password:   str = "",
    ) -> pd.DataFrame:
        try:
            from tvDatafeed import TvDatafeed
        except ImportError:
            raise ImportError("Install tvdatafeed: pip install git+https://github.com/rongardF/tvdatafeed.git")

        tv_sym    = self._NSE_SYMBOL_MAP.get(symbol.upper(), symbol.upper())
        tv_ivl    = self._tv_interval(interval)
        days      = max(1, (end_date - start_date).days + 1)
        cpd       = self._CANDLES_PER_DAY.get(interval, 1)

        # Priority:
        #  1. Explicit auth_token (password-based accounts)
        #  2. sessionid cookie → extract auth_token from page (Google OAuth accounts)
        #  3. username/password login
        #  4. anonymous (no login, ~10 months / ~5 000 bars)
        auth_token = _TV_AUTH_TOKEN
        if not auth_token and _TV_SESSIONID:
            auth_token = _get_tv_token_from_session(_TV_SESSIONID)

        if auth_token:
            tv = TvDatafeed()
            tv.token = auth_token
            logger.info("tvdatafeed: using auth_token (extended history)")
            # Proven token — can request up to 20 000 bars safely
            n_bars = min(20_000, max(200, int(days * cpd * 1.25)))
        elif _TV_SESSIONID:
            # Google OAuth user: sessionid auth failed to get token → use nologin directly.
            # Passing broken credentials to TvDatafeed leaves it in a broken state;
            # a fresh nologin instance correctly returns ~5 000 bars.
            tv = TvDatafeed()
            logger.info("tvdatafeed: sessionid auth unavailable, using nologin (~10 months)")
            n_bars = min(6_000, max(200, int(days * cpd * 1.25)))
        else:
            u = username or _TV_USERNAME
            p = password or _TV_PASSWORD
            if u and p:
                tv = TvDatafeed(username=u, password=p)
                logger.info("tvdatafeed: attempting login as '%s'", u)
            else:
                tv = TvDatafeed()
            # Free tier caps at ~5 000 bars
            n_bars = min(6_000, max(200, int(days * cpd * 1.25)))

        logger.info("tvdatafeed: fetching %s on %s [%s] n_bars=%d", tv_sym, exchange, interval, n_bars)
        raw = tv.get_hist(symbol=tv_sym, exchange=exchange, interval=tv_ivl, n_bars=n_bars)

        if raw is None or raw.empty:
            raise ValueError(f"tvdatafeed returned no data for {symbol} on {exchange} [{interval}]")

        df = raw.reset_index()
        df.rename(columns={"datetime": "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()

        # Filter to requested date range
        df = df[
            (df["timestamp"] >= pd.Timestamp(start_date)) &
            (df["timestamp"] <= pd.Timestamp(end_date))
        ]
        df = df.dropna(subset=["close", "open", "high", "low"])
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        logger.info("tvdatafeed: %d candles returned for %s [%s]", len(df), tv_sym, interval)
        return df


class IndianMarketFetcher:
    """
    Fetches OHLCV data for Indian NSE/BSE assets.

    Routing (intraday intervals: 1m/5m/15m/30m/1h/4h):
      1. tvdatafeed — TradingView, free, no auth, ~10 months without login
      2. Synthetic disaggregation — Brownian Bridge from daily OHLCV, unlimited history,
         zero cost, statistically consistent with daily data.
      Daily/weekly → yfinance (unlimited history, split-adjusted).

    Symbol resolution:
      "RELIANCE" + exchange="NSE"  →  tvdatafeed "RELIANCE" on NSE  / yfinance "RELIANCE.NS"
      "NIFTY50"  + any             →  tvdatafeed "NIFTY" on NSE      / yfinance "^NSEI"
    """

    _FY   = FyersDataFetcher()
    _OC   = OpenChartFetcher()
    _TV   = TvDatafeedFetcher()
    _YF   = YFinanceFetcher()
    _SYN  = SyntheticIntradayGenerator()

    _INTRADAY = {"1m", "5m", "15m", "30m", "1h", "4h"}

    # tvdatafeed without login serves ~300 trading days (~10 months) of intraday
    _TV_FREE_TRADING_DAYS = 300

    def fetch(
        self,
        symbol:     str,
        start_date: datetime,
        end_date:   datetime,
        interval:   str = "1d",
        exchange:   str = "NSE",
        synthetic:  bool = False,
    ) -> pd.DataFrame:
        if interval in self._INTRADAY:
            df = self._fetch_intraday(symbol, exchange, start_date, end_date, interval, synthetic)
        else:
            df = self._fetch_daily(symbol, exchange, start_date, end_date, interval)

        bad = (df["high"] < df["low"]).sum()
        if bad:
            logger.warning("Indian data quality: %d rows with high < low — dropping", bad)
            df = df[df["high"] >= df["low"]].copy()

        df["close"] = df["close"].ffill()
        df = df.dropna(subset=["close", "open", "high", "low"])
        df.reset_index(drop=True, inplace=True)

        logger.info("IndianFetcher: %d candles for %s (%s) [%s]", len(df), symbol, exchange, interval)
        return df

    def _fetch_intraday(
        self, symbol: str, exchange: str,
        start_date: datetime, end_date: datetime,
        interval: str, synthetic: bool,
    ) -> pd.DataFrame:
        """
        Priority order:
          1. Fyers API — 9 years free with demat account (requires daily token refresh)
          2. openchart — NSE public charting API, ~10 years (blocked by Akamai currently)
          3. tvdatafeed — TradingView, ~10 months free, no login
          4. synthetic disaggregation — Brownian Bridge from daily, unlimited history
          5. yfinance fallback (auto-clamped to its 60-day / 730-day limits)
        """
        trading_days = max(1, (end_date - start_date).days * 5 // 7)
        min_expected = trading_days * 3  # sanity floor: ≥3 candles/day

        if not synthetic:
            # ── 1. Fyers API ─────────────────────────────────────────────────
            if _FYERS_CLIENT_ID and _FYERS_ACCESS_TOKEN:
                try:
                    df = self._FY.fetch(symbol, exchange.upper(), start_date, end_date, interval)
                    if not df.empty and len(df) >= min_expected:
                        return df
                except Exception as exc:
                    logger.warning("Fyers failed for %s [%s]: %s — trying next source", symbol, interval, exc)

            # ── 2. openchart ────────────────────────────────────────────────
            try:
                df = self._OC.fetch(symbol, exchange.upper(), start_date, end_date, interval)
                if not df.empty and len(df) >= min_expected:
                    return df
                if not df.empty:
                    # Partial real data — fill gap before oldest openchart candle with synthetic
                    oldest_real = df["timestamp"].min()
                    if oldest_real > pd.Timestamp(start_date) + pd.Timedelta(days=30):
                        syn_end = oldest_real - pd.Timedelta(minutes=15)
                        syn_df = self._synthesize(symbol, exchange, start_date, syn_end.to_pydatetime(), interval)
                        syn_df["synthetic"] = True
                        df["synthetic"] = False
                        return pd.concat([syn_df, df], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
                    return df
            except Exception as exc:
                logger.warning("openchart failed for %s [%s]: %s — trying tvdatafeed", symbol, interval, exc)

            # ── 2. tvdatafeed ───────────────────────────────────────────────
            try:
                df = self._TV.fetch(symbol, exchange.upper(), start_date, end_date, interval)
                if not df.empty:
                    if len(df) >= min_expected:
                        return df
                    # Partial real data — supplement earlier period with synthetic
                    logger.info(
                        "tvdatafeed returned %d candles (< %d expected); supplementing with synthetic",
                        len(df), min_expected,
                    )
                    oldest_real = df["timestamp"].min()
                    if oldest_real > pd.Timestamp(start_date) + pd.Timedelta(days=30):
                        syn_end = oldest_real - pd.Timedelta(minutes=15)
                        syn_df = self._synthesize(symbol, exchange, start_date, syn_end.to_pydatetime(), interval)
                        syn_df["synthetic"] = True
                        df["synthetic"] = False
                        return pd.concat([syn_df, df], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
                    return df
            except Exception as exc:
                logger.warning("tvdatafeed failed for %s [%s]: %s", symbol, interval, exc)

        # ── 3. Synthetic disaggregation ─────────────────────────────────────
        use_synthetic = synthetic or trading_days > self._TV_FREE_TRADING_DAYS
        if use_synthetic:
            return self._synthesize(symbol, exchange, start_date, end_date, interval)

        # ── 4. yfinance (last resort, auto-clamped) ─────────────────────────
        yf_sym = _indian_to_yf(symbol, exchange)
        return self._YF.fetch(yf_sym, start_date, end_date, interval)

    def _synthesize(
        self, symbol: str, exchange: str,
        start_date: datetime, end_date: datetime, interval: str,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV and disaggregate into synthetic intraday candles."""
        logger.info(
            "Generating synthetic %s candles for %s from daily OHLCV (%s → %s)",
            interval, symbol, start_date.date(), end_date.date(),
        )
        daily_df = self._fetch_daily(symbol, exchange, start_date, end_date, "1d")
        if daily_df.empty:
            raise ValueError(f"No daily data available for {symbol} to synthesize intraday")
        syn_df = self._SYN.generate(daily_df, interval=interval)
        syn_df["synthetic"] = True
        return syn_df

    def _fetch_daily(self, symbol: str, exchange: str, start_date: datetime, end_date: datetime, interval: str) -> pd.DataFrame:
        yf_sym = _indian_to_yf(symbol, exchange)
        logger.info("Indian market (daily): %s → yfinance %s", symbol, yf_sym)
        df = self._YF.fetch(yf_sym, start_date, end_date, interval)
        df = df[df["timestamp"].dt.dayofweek < 5].copy()
        return df


class DataFetcher:
    """
    Unified interface that routes to the right data source.

    source options:
        'binance'   — Binance REST API (best for crypto)
        'yfinance'  — yfinance (US stocks, ETFs, forex, crypto)
        'nse'       — NSE India (via yfinance with .NS suffix)
        'bse'       — BSE India (via yfinance with .BO suffix)
        'auto'      — tries Binance → yfinance

    Indian market examples:
        fetch("RELIANCE", ..., source="nse")
        fetch("TCS",      ..., source="bse")
        fetch("NIFTY50",  ..., source="nse")
        fetch("NIFTYBEES",..., source="nse")
    """

    def __init__(self):
        self._binance    = BinanceFetcher()
        self._yfinance   = YFinanceFetcher()
        self._indian     = IndianMarketFetcher()

    def fetch(
        self,
        symbol:     str,
        start_date: datetime,
        end_date:   datetime,
        source:     Source = "binance",
        interval:   str    = "1d",
        synthetic_intraday: bool = False,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for any asset from any supported source.

        synthetic_intraday=True forces synthetic Brownian-Bridge disaggregation from daily
        data for NSE/BSE intraday intervals — gives unlimited history at zero cost.

        Returns pd.DataFrame with columns:
            timestamp | open | high | low | close | volume | source
        """
        # ── Indian markets ────────────────────────────────────────────────────
        if source == "nse":
            df = self._indian.fetch(symbol, start_date, end_date, interval, exchange="NSE", synthetic=synthetic_intraday)
            df["source"] = "nse"
            return df

        if source == "bse":
            df = self._indian.fetch(symbol, start_date, end_date, interval, exchange="BSE", synthetic=synthetic_intraday)
            df["source"] = "bse"
            return df

        # ── Crypto / US markets / auto fallback ───────────────────────────────
        fetchers: dict[str, any] = {
            "binance":  self._binance.fetch,
            "yfinance": self._yfinance.fetch,
        }

        order = ["binance", "yfinance"] if source == "auto" else [source]

        last_exc: Optional[Exception] = None
        for src in order:
            fn = fetchers.get(src)
            if fn is None:
                continue
            try:
                logger.info("Fetching %s from %s (%s → %s)…",
                            symbol, src, start_date.date(), end_date.date())
                df = fn(symbol, start_date, end_date, interval)
                if not df.empty:
                    df["source"] = src
                    return df
            except Exception as exc:
                logger.warning("Source '%s' failed for %s: %s", src, symbol, exc)
                last_exc = exc

        raise ValueError(
            f"All data sources failed for '{symbol}'. Last error: {last_exc}"
        )
