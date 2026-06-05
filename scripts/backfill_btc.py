#!/usr/bin/env python3
"""
Backfill BTCUSDT 1m bars from Binance bulk dumps (Aug 2017 → now).
Usage:
  python scripts/backfill_btc.py           # full backfill
  python scripts/backfill_btc.py --smoke   # 2017-08 only (verify pipeline)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from marketdash.ingest import backfill_btc

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                        help="Download only 2017-08 to verify the pipeline")
    args = parser.parse_args()
    backfill_btc(max_months=1 if args.smoke else None)
