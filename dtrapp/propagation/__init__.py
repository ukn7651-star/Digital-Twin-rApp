"""Stage 3 - propagation: Sionna RT ray tracing -> per-link path gain.

Ray tracing is the engine; `SionnaPropagationEngine` runs every time the twin
produces throughput. There is no surrogate or fallback model.
"""

from dtrapp.propagation.sionna_engine import SionnaPropagationEngine

__all__ = ["SionnaPropagationEngine"]
