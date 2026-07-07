"""Digital Twin rApp - ray-traced downlink throughput engine (OAI-backed).

Builds a virtual replica of a real-world cellular environment, ray-traces the
radio channel with Sionna RT, and computes per-UE / per-cell downlink throughput.
The SINR->throughput *mapping* is measured by OpenAirInterface's real 5G-NR PHY
(no Sionna SYS formula); the raw channel is also exported so OAI can run over the
exact ray-traced channel.

Pipeline stages:
    1. geometry    - OSM bounding box -> Mitsuba scene.xml (no fallback geometry)
    2. network     - seeded generator for cells + UEs (swappable data layer)
    3. propagation - Sionna RT: place TX/RX, ray-trace -> channel (CFR)
    4-5. kpi       - association + multi-cell SINR -> OAI-measured throughput map
                     -> proportional-fair scheduling -> per-UE/per-cell throughput
    6. runner      - write CSV/JSON, export CFR for OAI-in-the-loop; CLI. See oai/.
"""

__version__ = "0.1.0"

from dtrapp.config import BoundingBox, SimulationConfig

__all__ = ["BoundingBox", "SimulationConfig", "__version__"]
