"""Command-line entry point.

    dtrapp configs/example.yaml

Builds the OSM scene, generates the network, ray-traces the channel with Sionna
RT, and exports it (output/channel/) for OpenAirInterface. Throughput/KPIs are
then produced by the OAI stack (see oai/).
"""

from __future__ import annotations

import argparse
import sys

from dtrapp.config import SimulationConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dtrapp",
        description="Sionna RT channel generator for the Digital Twin rApp (feeds OAI).",
    )
    parser.add_argument("config", help="Path to a YAML scenario config.")
    args = parser.parse_args(argv)

    config = SimulationConfig.from_yaml(args.config)

    from dtrapp.runner.pipeline import run_simulation

    network, cfr = run_simulation(config)
    print(f"done: {len(network.cells)} cells, {len(network.ues)} UEs, "
          f"CFR {tuple(cfr.shape)} -> {config.output_dir}/channel/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
