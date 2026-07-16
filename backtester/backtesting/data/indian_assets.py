"""
Indian Market Asset Registry
NSE/BSE stocks, ETFs, F&O lot sizes, index symbols.

All symbol → yfinance ticker mappings are verified against yfinance as of 2024.
Lot sizes are as per NSE circulars effective FY2024-25.
"""
from __future__ import annotations

# ── NSE Index → yfinance symbol ───────────────────────────────────────────────
INDEX_MAP: dict[str, str] = {
    "NIFTY50":      "^NSEI",
    "NIFTY":        "^NSEI",
    "NIFTY 50":     "^NSEI",
    "BANKNIFTY":    "^NSEBANK",
    "BANK NIFTY":   "^NSEBANK",
    "NIFTYNEXT50":  "^NSMIDCP100",
    "NIFTYMID50":   "^NSEMDCP50",
    "NIFTYIT":      "^CNXIT",
    "NIFTY IT":     "^CNXIT",
    "NIFTY100":     "^CNX100",
    "NIFTY200":     "^CNX200",
    "NIFTY500":     "^CNX500",
    "FINNIFTY":     "NIFTY_FIN_SERVICE.NS",
    "SENSEX":       "^BSESN",
    "BSE500":       "^BSE500",
    "VIX":          "^INDIAVIX",
    "INDIA VIX":    "^INDIAVIX",
}

# ── Nifty 50 stocks (NSE) ─────────────────────────────────────────────────────
NIFTY50: list[str] = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BHARTIARTL", "BPCL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBIN", "SBILIFE", "SHREECEM",
    "SUNPHARMA", "TATAMOTORS", "TATACONSUM", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "ULTRACEMCO", "UPL", "WIPRO",
]

# ── Additional popular NSE stocks ─────────────────────────────────────────────
POPULAR_NSE: list[str] = [
    "ZOMATO", "PAYTM", "NYKAA", "POLICYBZR", "IRCTC",
    "HAL", "BEL", "BHEL", "IRFC", "HUDCO", "RVNL",
    "DMART", "TRENT", "GODREJCP", "DABUR", "MARICO", "COLPAL",
    "PIDILITIND", "BERGEPAINT", "HAVELLS", "WHIRLPOOL", "VOLTAS",
    "MOTHERSON", "ASHOKLEY", "TVSMOTOR", "MRF", "EXIDEIND",
    "LUPIN", "BIOCON", "TORNTPHARM", "ALKEM", "AUROPHARMA",
    "IDFCFIRSTB", "FEDERALBNK", "BANDHANBNK", "AUBANK", "RBLBANK",
    "VEDL", "SAIL", "NMDC", "MOIL", "NATIONALUM",
    "ADANIGREEN", "ADANIPOWER", "ADANITRANS", "TATAPOWER", "TORNTPOWER",
    "INDUSTOWER", "MPHASIS", "PERSISTENT", "LTIM", "COFORGE",
    "DIXON", "AMBER", "ASTRAL", "POLYCAB", "LNTECHNOLOGY",
    "GODREJPROP", "OBEROIRLTY", "DLF", "PRESTIGE", "SOBHA",
]

# ── NSE ETFs (with yfinance suffix .NS) ───────────────────────────────────────
NSE_ETFS: dict[str, str] = {
    "NIFTYBEES":    "Nifty 50 ETF (Nippon)",
    "BANKBEES":     "Bank Nifty ETF (Nippon)",
    "GOLDBEES":     "Gold ETF (Nippon)",
    "SILVERBEES":   "Silver ETF (Nippon)",
    "ITBEES":       "Nifty IT ETF (Nippon)",
    "JUNIORBEES":   "Nifty Next 50 ETF (Nippon)",
    "MOM100":       "Nifty Midcap Momentum ETF",
    "PSUBNKBEES":   "PSU Bank ETF",
    "CPSEETF":      "CPSE ETF",
    "LIQUIDBEES":   "Liquid BeES (overnight fund)",
    "NETFGILT5Y":   "Gilt 5Y ETF (Nippon)",
    "SETFNIF50":    "Nifty 50 ETF (SBI)",
    "ICICIB22":     "Nifty ETF (ICICI)",
    "NETF":         "Nifty ETF (DSP)",
    "MAFSETF50":    "Nifty 50 ETF (Mirae)",
    "HNGSNGBEES":   "Hang Seng ETF (Nippon)",
    "NIFTYBETTF":   "Nifty BETI ETF",
}

# ── F&O Lot Sizes (NSE, as of FY2024-25) ─────────────────────────────────────
# Source: NSE circular NSCCL/CMPT/56264/2024
# Note: Lot sizes are revised quarterly. Verify at nseindia.com before live use.
FO_LOT_SIZES: dict[str, int] = {
    # ── Index F&O ──────────────────────────────────────────
    "NIFTY50":    50,    "NIFTY":     50,
    "BANKNIFTY":  15,    "FINNIFTY":  40,
    "MIDCPNIFTY": 75,    "SENSEX":    10,

    # ── Equity F&O (Nifty 50 members) ─────────────────────
    "ADANIENT":   125,   "ADANIPORTS":  1250,  "APOLLOHOSP":  125,
    "ASIANPAINT": 200,   "AXISBANK":    1200,  "BAJAJ-AUTO":  75,
    "BAJFINANCE": 125,   "BAJAJFINSV":  125,   "BHARTIARTL":  1000,
    "BPCL":       3000,  "BRITANNIA":   200,   "CIPLA":       650,
    "COALINDIA":  4200,  "DIVISLAB":    200,   "DRREDDY":     125,
    "EICHERMOT":  150,   "GRASIM":      475,   "HCLTECH":     700,
    "HDFCBANK":   550,   "HDFCLIFE":    1100,  "HEROMOTOCO":  300,
    "HINDALCO":   3500,  "HINDUNILVR":  300,   "ICICIBANK":   700,
    "INDUSINDBK": 525,   "INFY":        300,   "ITC":         3200,
    "JSWSTEEL":   1350,  "KOTAKBANK":   400,   "LT":          300,
    "M&M":        700,   "MARUTI":      75,    "NESTLEIND":   50,
    "NTPC":       4800,  "ONGC":        3850,  "POWERGRID":   4800,
    "RELIANCE":   250,   "SBIN":        1500,  "SBILIFE":     750,
    "SHREECEM":   25,    "SUNPHARMA":   700,   "TATAMOTORS":  2400,
    "TATACONSUM": 875,   "TATASTEEL":   5500,  "TCS":         150,
    "TECHM":      600,   "TITAN":       375,   "ULTRACEMCO":  100,
    "UPL":        1300,  "WIPRO":       2800,
    # ── Other popular F&O stocks ───────────────────────────
    "ZOMATO":     4500,  "IRCTC":       875,   "HAL":         175,
    "IDFCFIRSTB": 7000,  "TVSMOTOR":    350,   "ASHOKLEY":    6500,
    "NMDC":       7500,  "VEDL":        3250,  "TATAPOWER":   3375,
    "INDUSTOWER": 2800,  "PERSISTENT":  250,   "MPHASIS":     400,
    "LTIM":       150,   "COFORGE":     200,
}

# ── Curated UI dropdown — symbol: display label ───────────────────────────────
NSE_DROPDOWN: dict[str, str] = {
    # Indices
    "NIFTY50":    "NIFTY 50 (Index)",
    "BANKNIFTY":  "BANK NIFTY (Index)",
    "SENSEX":     "SENSEX (Index/BSE)",
    # Large cap
    "RELIANCE":   "Reliance Industries",
    "TCS":        "Tata Consultancy Services",
    "HDFCBANK":   "HDFC Bank",
    "INFY":       "Infosys",
    "ICICIBANK":  "ICICI Bank",
    "BHARTIARTL": "Bharti Airtel",
    "SBIN":       "State Bank of India",
    "HINDUNILVR": "Hindustan Unilever",
    "ITC":        "ITC Ltd",
    "LT":         "Larsen & Toubro",
    "KOTAKBANK":  "Kotak Mahindra Bank",
    "AXISBANK":   "Axis Bank",
    "BAJFINANCE": "Bajaj Finance",
    "MARUTI":     "Maruti Suzuki",
    "HCLTECH":    "HCL Technologies",
    "WIPRO":      "Wipro",
    "TATAMOTORS": "Tata Motors",
    "SUNPHARMA":  "Sun Pharma",
    "TITAN":      "Titan Company",
    # Mid-cap / popular
    "ZOMATO":     "Zomato",
    "IRCTC":      "IRCTC",
    "HAL":        "Hindustan Aeronautics",
    "DMART":      "Avenue Supermarts (DMart)",
    "TRENT":      "Trent (Zara/Westside)",
    # ETFs
    "NIFTYBEES":  "NIFTYBEES ETF",
    "BANKBEES":   "BANKBEES ETF",
    "GOLDBEES":   "Gold ETF (GOLDBEES)",
    "LIQUIDBEES": "Liquid ETF",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def to_yf_symbol(symbol: str, exchange: str = "NSE") -> str:
    """
    Convert a plain Indian symbol to its yfinance ticker.

    Examples:
        to_yf_symbol("RELIANCE")       → "RELIANCE.NS"
        to_yf_symbol("TCS", "BSE")     → "TCS.BO"
        to_yf_symbol("NIFTY50")        → "^NSEI"
        to_yf_symbol("RELIANCE.NS")    → "RELIANCE.NS"  (pass-through)
        to_yf_symbol("^NSEI")          → "^NSEI"        (pass-through)
    """
    s = symbol.strip().upper()

    # Already a yfinance ticker
    if s.endswith(".NS") or s.endswith(".BO") or s.startswith("^"):
        return s

    # Index
    if s in INDEX_MAP:
        return INDEX_MAP[s]

    # Stock / ETF → add exchange suffix
    suffix = ".BO" if exchange.upper() == "BSE" else ".NS"
    return f"{s}{suffix}"


def is_indian(symbol: str) -> bool:
    """Return True if the symbol is recognised as an Indian market instrument."""
    s = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    return (
        symbol.upper().endswith(".NS")
        or symbol.upper().endswith(".BO")
        or s in INDEX_MAP
        or s in NIFTY50
        or s in POPULAR_NSE
        or s in NSE_ETFS
        or s in FO_LOT_SIZES
    )


def get_lot_size(symbol: str) -> int:
    """Return F&O lot size for symbol. Returns 1 for non-F&O instruments."""
    s = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    return FO_LOT_SIZES.get(s, 1)


def clean_symbol(symbol: str) -> str:
    """Strip exchange suffix to get the bare NSE symbol."""
    return symbol.strip().upper().replace(".NS", "").replace(".BO", "")
