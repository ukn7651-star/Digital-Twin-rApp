"""Stage 2 - network: cells + UEs with radio config and traffic.

The data is randomly generated for now (a temporary stand-in for live network
data). All consumers go through the `NetworkDataSource` interface so a real
data source can replace the random generator without touching the rest of the
pipeline.
"""

from dtrapp.network.base import NetworkDataSource
from dtrapp.network.models import Cell, NetworkSnapshot, UE
from dtrapp.network.random_source import RandomNetworkSource

__all__ = [
    "Cell",
    "UE",
    "NetworkSnapshot",
    "NetworkDataSource",
    "RandomNetworkSource",
]
