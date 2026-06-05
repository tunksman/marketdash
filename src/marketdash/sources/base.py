from abc import ABC, abstractmethod
from typing import Iterator


class Source(ABC):
    """Extension seam: implement iter_bars() to add a new price feed."""

    @abstractmethod
    def iter_bars(self, symbol: str, start, end) -> Iterator[tuple]:
        """Yield normalized bar tuples matching bar_1m schema columns:
        (instrument_id, ts, open, high, low, close, volume, quote_volume, trades)
        """
        ...


class MacroSource(ABC):

    @abstractmethod
    def iter_observations(self, series_id: str) -> Iterator[tuple]:
        """Yield (series_id, date, value) tuples."""
        ...
