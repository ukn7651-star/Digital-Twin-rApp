"""The swappable network data-source interface.

The random generator and any future real-data source both implement
`NetworkDataSource`. The rest of the pipeline depends only on this interface,
so swapping in live network data requires no changes downstream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from dtrapp.network.models import NetworkSnapshot


class NetworkDataSource(ABC):
    """Produces a `NetworkSnapshot` for each simulated time index."""

    @property
    @abstractmethod
    def num_snapshots(self) -> int:
        """Total number of snapshots this source can produce."""

    @abstractmethod
    def snapshot(self, index: int) -> NetworkSnapshot:
        """Return the network state at the given snapshot index."""

    def __iter__(self):
        for i in range(self.num_snapshots):
            yield self.snapshot(i)
