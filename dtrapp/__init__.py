"""Digital Twin rApp - offline ray-traced downlink throughput engine.

A standalone, offline simulation engine that builds a virtual replica of a
real-world cellular environment and computes downlink throughput per UE and
per cell using Sionna RT ray tracing for radio propagation.

Pipeline stages:
    1. geometry    - OSM bounding box -> Mitsuba scene.xml (no fallback geometry)
    2. network     - seeded generator for cells + UEs (swappable data layer)
    3. propagation - Sionna RT: place TX/RX, solve -> path gain
    4-5. kpi       - multi-cell SINR -> Shannon throughput with resource sharing
    6. runner      - snapshot loop + output writer + CLI
"""

__version__ = "0.1.0"

from dtrapp.config import BoundingBox, SimulationConfig

__all__ = ["BoundingBox", "SimulationConfig", "__version__"]
