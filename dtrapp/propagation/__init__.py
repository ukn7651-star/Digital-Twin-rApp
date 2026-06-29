"""Stage 3 - propagation: place TX/RX in the scene, solve -> path gain.

Sionna RT is the propagation engine (`SionnaPropagationEngine`): it runs every
time the twin produces throughput. The engine sits behind the
`PropagationEngine` interface, mirroring the swappable network-data layer.

An `AnalyticalPropagationEngine` (log-distance path loss) is provided ONLY for
developing and testing the rest of the pipeline on machines without Sionna RT /
a GPU. It is NOT ray tracing and must be selected explicitly; it is never used
as a silent fallback for the Sionna engine.
"""

from dtrapp.propagation.base import PropagationEngine
from dtrapp.propagation.analytical import AnalyticalPropagationEngine

__all__ = [
    "PropagationEngine",
    "AnalyticalPropagationEngine",
    "make_engine",
]


def make_engine(name: str, scene_xml, config):
    """Factory: build a propagation engine by name ('sionna' or 'analytical')."""
    name = (name or "sionna").lower()
    if name == "sionna":
        from dtrapp.propagation.sionna_engine import SionnaPropagationEngine

        return SionnaPropagationEngine(scene_xml, config)
    if name == "analytical":
        return AnalyticalPropagationEngine(scene_xml, config)
    raise ValueError(f"unknown propagation engine: {name!r}")
