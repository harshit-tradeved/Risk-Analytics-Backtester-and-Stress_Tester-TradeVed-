"""
Configuration settings for the TradeVed Backtester system.
All paths, constants, and environment-based settings live here.
"""
import os
import logging
from pathlib import Path

# Load .env file if present (credentials stay out of tracked code)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Base Paths ──────────────────────────────────────────────────────────────
BASE_DIR         = Path(__file__).parent
DATA_STORAGE_DIR = BASE_DIR / "data_storage"
REPORTS_DIR      = BASE_DIR / "reports"
CHARTS_DIR       = BASE_DIR / "charts"
LOGS_DIR         = BASE_DIR / "logs"

# Ensure all runtime directories exist
for _d in [DATA_STORAGE_DIR, REPORTS_DIR, CHARTS_DIR, LOGS_DIR]:
    _d.mkdir(exist_ok=True)

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'backtester.db'}")

# ── Admin auth (set ADMIN_TOKEN env var in production) ───────────────────────
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-admin-token-change-in-prod")

# ── API Settings ─────────────────────────────────────────────────────────────
API_TITLE       = "TradeVed Backtester API"
API_DESCRIPTION = "Production-grade cryptocurrency backtesting system with Grid, DCA & PLA strategies"
API_VERSION     = "1.0.0"
API_PREFIX      = "/api"

# ── External Data Sources ────────────────────────────────────────────────────
BINANCE_BASE_URL   = "https://api.binance.com"

# Binance optional API credentials (not required for public OHLCV data)
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ── TradingView credentials (optional — unlocks 2–3 years of free intraday data) ──
# Without these: ~10 months of 15m/1h data (no login, free).
# With a FREE TradingView account: 2–3 years of intraday data.
# Sign up at https://www.tradingview.com (no credit card needed).
# Set these as environment variables OR edit the strings below directly.
TV_USERNAME   = os.getenv("TV_USERNAME", "")    # set in backtester/.env
TV_PASSWORD   = os.getenv("TV_PASSWORD", "")    # set in backtester/.env
TV_AUTH_TOKEN = os.getenv("TV_AUTH_TOKEN", "")  # browser cookie — bypasses bot protection
TV_SESSIONID  = os.getenv("TV_SESSIONID",  "")  # sessionid cookie (Google OAuth users)

# ── Fyers API (9 years of NSE/BSE intraday data, free with demat account) ────
FYERS_CLIENT_ID    = os.getenv("FYERS_CLIENT_ID",    "")
FYERS_SECRET_KEY   = os.getenv("FYERS_SECRET_KEY",   "")
FYERS_REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI", "https://fyers.in")
FYERS_ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "")  # expires daily; refresh via fyers_auth.py

# ── Trading Defaults ──────────────────────────────────────────────────────────
DEFAULT_FEE_PERCENT      = 0.001   # 0.1 % Binance taker fee
DEFAULT_SLIPPAGE_PERCENT = 0.001   # 0.1 % market-impact slippage
DEFAULT_CAPITAL          = 10_000.0

# ── Rate Limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_PER_MINUTE = 100

# ── Caching ───────────────────────────────────────────────────────────────────
CACHE_TTL_SECONDS = 3_600   # 1 hour

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

import sys as _sys
_stream_handler = logging.StreamHandler(_sys.stdout)
_stream_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
# Reconfigure stdout to UTF-8 so ₹ and other non-ASCII characters don't crash on Windows
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # not available in older Python versions

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        _stream_handler,
        logging.FileHandler(LOGS_DIR / "backtester.log", encoding="utf-8"),
    ],
)

