"""Digital Twin rApp - offline ray-traced downlink throughput engine (v1).

A standalone, offline simulation engine that builds a virtual replica of a
real-world cellular environment and computes downlink throughput per UE and
per cell using ray tracing for radio propagation.

Pipeline stages:
    1. geometry    - OSM bounding box -> Mitsuba scene.xml (no fallback geometry)
    2. network     - seeded generator for cells + UEs (swappable data layer)
    3. propagation - Sionna RT wrapper: place TX/RX, solve -> path gain
    4. kpi         - multi-cell SINR -> Shannon throughput with resource sharing
    5. runner      - snapshot loop + output writer + CLI
"""

__version__ = "0.1.0"

from dtrapp.config import (
    BoundingBox,
    GeometryConfig,
    KpiConfig,
    NetworkConfig,
    PropagationConfig,
    RunnerConfig,
    SimulationConfig,
)

__all__ = [
    "BoundingBox",
    "GeometryConfig",
    "NetworkConfig",
    "PropagationConfig",
    "KpiConfig",
    "RunnerConfig",
    "SimulationConfig",
    "__version__",
]
