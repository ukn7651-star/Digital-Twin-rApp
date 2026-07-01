"""The swappable network data-source interface.

The random generator and any future real-data source both implement
`NetworkDataSource`. The rest of the pipeline depends only on this interface,
so swapping in live network data requires no changes downstream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from dtrapp.network.models import Network


class NetworkDataSource(ABC):
    """Produces the `Network` (cells + UEs) to simulate."""

    @abstractmethod
    def generate(self) -> Network:
        """Return the network to simulate."""
