"""Keyless FRED CSV feed: fredgraph.csv?id=<SERIES_ID>"""

import csv
import io
import time
from typing import Iterator

import requests

from ..config import FRED_CSV_URL
from .base import MacroSource

_MAX_RETRIES = 3
_RETRY_DELAY = 5


class FredSource(MacroSource):

    def iter_observations(self, series_id: str) -> Iterator[tuple]:
        """Yield (series_id, date_str, value_or_None) for each row."""
        url = FRED_CSV_URL.format(series_id=series_id)
        last_err = None
        for attempt in range(_MAX_RETRIES):
            try:
                r = requests.get(url, timeout=60)
                r.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY)
        else:
            raise RuntimeError(f"FRED fetch failed for {series_id} after {_MAX_RETRIES} attempts: {last_err}")
        reader = csv.reader(io.StringIO(r.text))
        next(reader, None)  # skip header row (DATE,VALUE)
        for row in reader:
            if len(row) < 2:
                continue
            date_str = row[0].strip()
            raw_val = row[1].strip()
            value = None if raw_val == "." else float(raw_val)
            yield (series_id, date_str, value)
