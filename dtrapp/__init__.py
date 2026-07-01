"""Digital Twin rApp - Sionna RT channel generator (feeds OpenAirInterface).

Builds a virtual replica of a real-world cellular environment and ray-traces the
radio channel with Sionna RT. The channel is exported for OpenAirInterface (a real
5G-NR stack), which produces the throughput/KPIs. There is no link-level model
(no Sionna SYS) here.

Pipeline stages:
    1. geometry    - OSM bounding box -> Mitsuba scene.xml (no fallback geometry)
    2. network     - seeded generator for cells + UEs (swappable data layer)
    3. propagation - Sionna RT: place TX/RX, ray-trace -> channel (CFR)
    4. runner      - export CFR + network for OAI; CLI. See oai/ for the OAI stack.
"""

__version__ = "0.1.0"

from dtrapp.config import BoundingBox, SimulationConfig

__all__ = ["BoundingBox", "SimulationConfig", "__version__"]
