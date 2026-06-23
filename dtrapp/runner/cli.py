"""Command-line entry point.

    dtrapp configs/example.yaml

Runs the full ray-traced pipeline described by a YAML scenario file.
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

    results = run_simulation(config)
    total_ues = sum(len(s.ues) for s in results)
    print(f"done: {len(results)} snapshot(s), {total_ues} UE samples.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
