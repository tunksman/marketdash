"""Keyless FRED CSV feed: fredgraph.csv?id=<SERIES_ID>"""

import csv
import io
import time
from typing import Iterator

import requests

from ..config import FRED_CSV_URL
from .base import MacroSource

_MAX_RETRIES = 3
_RETRY_DELAY = 8
_CONNECT_TIMEOUT = 15
_READ_TIMEOUT = 120

# Daily FRED series have 20-70 years of history → large CSVs → FRED 504.
# Limit to post-2010 for daily series to keep download under ~5 KB.
# Monthly series are small enough to fetch in full.
_DAILY_START = "2010-01-01"


class FredSource(MacroSource):

    def iter_observations(self, series_id: str, frequency: str = "D") -> Iterator[tuple]:
        """Yield (series_id, date_str, value_or_None) for each row.

        frequency: 'D' (daily) or 'M'/'W' (monthly/weekly).
        Daily series are capped at _DAILY_START via the cosd param.
        """
        base_url = FRED_CSV_URL.format(series_id=series_id)
        if frequency == "D":
            url = base_url + f"&cosd={_DAILY_START}"
        else:
            url = base_url

        last_err = None
        for attempt in range(_MAX_RETRIES):
            try:
                r = requests.get(url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
                if r.status_code == 404:
                    raise RuntimeError(f"FRED series {series_id} not found (404)")
                r.raise_for_status()
                break
            except RuntimeError:
                raise  # non-retryable (e.g. 404)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY)
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (429, 500, 502, 503, 504):  # transient: retry
                    last_err = e
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(_RETRY_DELAY * 2)
                else:
                    raise RuntimeError(f"FRED HTTP error for {series_id}: {e}") from e
        else:
            raise RuntimeError(
                f"FRED fetch failed for {series_id} after {_MAX_RETRIES} attempts: {last_err}"
            )

        reader = csv.reader(io.StringIO(r.text))
        next(reader, None)  # skip header row
        for row in reader:
            if len(row) < 2:
                continue
            date_str = row[0].strip()
            raw_val = row[1].strip()
            if not date_str:
                continue
            value = None if raw_val in (".", "") else float(raw_val)
            yield (series_id, date_str, value)
