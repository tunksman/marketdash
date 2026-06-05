#!/usr/bin/env python3
"""
Pull all 15 curated FRED macro series and store in macro_observation.
Usage: python scripts/seed_macro.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from marketdash.config import MACRO_SERIES
from marketdash.db import connect, init_db
from marketdash.sources.fred import FredSource


def seed_macro(verbose: bool = True) -> None:
    init_db()
    con = connect()
    src = FredSource()

    failed = []
    for series_id, name, *_ in MACRO_SERIES:
        if verbose:
            print(f"  pulling {series_id} ({name}) ...", end=" ", flush=True)
        try:
            obs = list(src.iter_observations(series_id))
        except Exception as e:
            if verbose:
                print(f"SKIP ({e})")
            failed.append(series_id)
            continue
        con.executemany("""
            INSERT INTO macro_observation (series_id, ts, value)
            VALUES (?, ?, ?)
            ON CONFLICT (series_id, ts) DO NOTHING
        """, obs)
        if verbose:
            print(f"{len(obs)} rows")

    con.close()
    if failed:
        print(f"Macro seed done (failed/skipped: {', '.join(failed)} — re-run to retry).")
    else:
        print("Macro seed complete.")


if __name__ == "__main__":
    seed_macro()
