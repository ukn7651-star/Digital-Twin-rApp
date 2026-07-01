"""Command-line entry point.

    dtrapp configs/example.yaml

Builds the OSM scene, generates the network, ray-traces the channel with Sionna
RT, maps SINR -> throughput via the OAI-measured link curve, and writes per-UE /
per-cell throughput. The raw channel is also exported (output/channel/) so OAI can
run over the exact ray-traced channel (see oai/).
"""

from __future__ import annotations

import argparse
import sys

from dtrapp.config import SimulationConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dtrapp",
        description="Offline ray-traced downlink throughput engine (Digital Twin rApp).",
    )
    parser.add_argument("config", help="Path to a YAML scenario config.")
    args = parser.parse_args(argv)

    config = SimulationConfig.from_yaml(args.config)

    from dtrapp.runner.pipeline import run_simulation

    result = run_simulation(config)
    print(f"done: {len(result.ues)} UEs, {len(result.cells)} cells.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
