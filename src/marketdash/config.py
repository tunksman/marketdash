import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # marketdash/
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "market.duckdb"

DATA_DIR.mkdir(exist_ok=True)
RAW_DIR.mkdir(exist_ok=True)

# Equity provider config
EQUITY_PROVIDER = os.environ.get("EQUITY_PROVIDER", "twelvedata")
EQUITY_API_KEY = os.environ.get("EQUITY_API_KEY", "")

# BTC source
BINANCE_MONTHLY_URL = (
    "https://data.binance.vision/data/spot/monthly/klines/{symbol}/{interval}/"
    "{symbol}-{interval}-{year}-{month:02d}.zip"
)
BINANCE_DAILY_URL = (
    "https://data.binance.vision/data/spot/daily/klines/{symbol}/{interval}/"
    "{symbol}-{interval}-{date}.zip"
)
BINANCE_START_YEAR = 2017
BINANCE_START_MONTH = 8

# FRED keyless CSV
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

MACRO_SERIES = [
    ("M2SL",            "M2 Money Supply",                   "liquidity",  "fred", "M",  "Billions of Dollars"),
    ("WALCL",           "Fed Balance Sheet Total Assets",     "liquidity",  "fred", "W",  "Millions of Dollars"),
    ("DFF",             "Effective Fed Funds Rate",           "rates",      "fred", "D",  "Percent"),
    ("DGS10",           "10Y Treasury Yield",                 "rates",      "fred", "D",  "Percent"),
    ("DGS2",            "2Y Treasury Yield",                  "rates",      "fred", "D",  "Percent"),
    ("CPIAUCSL",        "CPI Headline",                       "inflation",  "fred", "M",  "Index 1982-84=100"),
    ("PCEPILFE",        "Core PCE",                           "inflation",  "fred", "M",  "Index 2017=100"),
    ("T5YIE",           "5Y Breakeven Inflation",             "inflation",  "fred", "D",  "Percent"),
    ("VIXCLS",          "VIX",                                "risk",       "fred", "D",  "Index"),
    ("BAMLH0A0HYM2",    "HY Credit Spread ICE BofA OAS",      "risk",       "fred", "D",  "Percent"),
    ("SP500",           "S&P 500",                            "equity",     "fred", "D",  "Index"),
    ("DTWEXBGS",        "Broad Trade-Weighted USD",           "fx",         "fred", "D",  "Index Jan 2006=100"),
    ("DCOILWTICO",      "WTI Crude Oil",                      "commodity",  "fred", "D",  "Dollars per Barrel"),
    ("DFII10",           "10Y TIPS Real Yield",                "rates",      "fred", "D",  "Percent"),
    ("UNRATE",          "Unemployment Rate",                  "labor",      "fred", "M",  "Percent"),
]

EQUITY_SYMBOLS = ["SPY", "MU", "NVDA", "SNDK"]
