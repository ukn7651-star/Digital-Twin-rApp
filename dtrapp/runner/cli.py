"""Command-line entry point for the Digital Twin rApp throughput engine.

Examples
--------
Run from a YAML config:
    dtrapp --config configs/example.yaml

Run from a bounding box on the command line (random network):
    dtrapp --bbox 52.51 13.37 52.515 13.38 --snapshots 5 --engine sionna

Develop without Sionna RT (test-only analytical propagation):
    dtrapp --config configs/example.yaml --engine analytical
"""

from __future__ import annotations

import argparse
import sys

from dtrapp.config import BoundingBox, RunnerConfig, SimulationConfig


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dtrapp",
        description="Offline ray-traced downlink throughput engine (Digital Twin rApp v1).",
    )
    p.add_argument("--config", help="Path to a YAML scenario config.")
    p.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LAT", "MIN_LON", "MAX_LAT", "MAX_LON"),
        help="Bounding box (overrides config bbox if both given).",
    )
    p.add_argument("--snapshots", type=int, help="Number of snapshots to simulate.")
    p.add_argument("--seed", type=int, help="Random seed for the network generator.")
    p.add_argument("--output", help="Output directory.")
    p.add_argument(
        "--engine",
        choices=["sionna", "analytical"],
        default="sionna",
        help="Propagation engine: 'sionna' (ray tracing) or 'analytical' (test only).",
    )
    p.add_argument(
        "--write-config",
        metavar="PATH",
        help="Write the effective config to PATH (YAML) and exit.",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    return p


def _config_from_args(args: argparse.Namespace) -> SimulationConfig:
    if args.config:
        config = SimulationConfig.from_yaml(args.config)
    elif args.bbox:
        config = SimulationConfig(bbox=BoundingBox(*args.bbox))
    else:
        raise SystemExit("error: provide either --config or --bbox")

    if args.bbox and args.config:
        config.bbox = BoundingBox(*args.bbox)
    if args.snapshots is not None:
        config.runner.num_snapshots = args.snapshots
    if args.seed is not None:
        config.network.seed = args.seed
    if args.output is not None:
        config.runner.output_dir = args.output
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = _config_from_args(args)

    if args.write_config:
        config.to_yaml(args.write_config)
        print(f"wrote effective config to {args.write_config}")
        return 0

    # Local import so `--help` / `--write-config` work without heavy deps.
    from dtrapp.runner.pipeline import run_simulation

    results = run_simulation(
        config, engine_name=args.engine, progress=not args.quiet
    )

    total_ues = sum(len(s.ues) for s in results)
    if not args.quiet:
        print(f"done: {len(results)} snapshot(s), {total_ues} UE samples.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
