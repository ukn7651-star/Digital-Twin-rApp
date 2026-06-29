"""End-to-end orchestration: scenario config -> throughput dataset.

Wires the six stages together:
    1. build the 3D scene from OSM (no fallback)
    2. construct the (swappable) network data source
    3. build the propagation engine (Sionna RT by default)
    4-5. per snapshot: path gain -> SINR -> throughput
    6. write the dataset and return the per-snapshot KPIs
"""

from __future__ import annotations

from pathlib import Path

from dtrapp.config import SimulationConfig
from dtrapp.geometry import build_scene
from dtrapp.kpi import compute_kpis
from dtrapp.kpi.results import SnapshotKpi
from dtrapp.network import NetworkDataSource, RandomNetworkSource
from dtrapp.propagation import make_engine
from dtrapp.runner.output import write_outputs


def run_simulation(
    config: SimulationConfig,
    engine_name: str = "sionna",
    network_source: NetworkDataSource | None = None,
    progress: bool = True,
) -> list[SnapshotKpi]:
    """Run the full pipeline and return per-snapshot KPIs.

    Parameters
    ----------
    config: the scenario configuration.
    engine_name: propagation engine ('sionna' for ray tracing, 'analytical' for
        the test-only log-distance model).
    network_source: optional pre-built data source. Defaults to the seeded
        random generator. Pass a real-data source here to swap the data layer.
    progress: print per-snapshot progress to stdout.
    """
    out_dir = Path(config.runner.output_dir)
    scene_dir = out_dir / "scene"

    # Stage 1 - geometry (raises SceneBuildError and stops if OSM fails).
    if progress:
        print(f"[1/6] Building scene from OSM bbox {config.bbox.as_overpass_bbox()} ...")
    artifacts = build_scene(config.bbox, scene_dir, config.geometry)
    if progress:
        print(
            f"      {artifacts.num_buildings} buildings -> {artifacts.scene_xml} "
            f"(extent {artifacts.extent_m})"
        )

    # Stage 2 - network data source (swappable).
    if network_source is None:
        network_source = RandomNetworkSource(
            config.network,
            extent_m=artifacts.extent_m,
            num_snapshots=config.runner.num_snapshots,
        )

    # Stage 3 - propagation engine.
    if progress:
        print(f"[3/6] Initializing '{engine_name}' propagation engine ...")
    engine = make_engine(engine_name, artifacts.scene_xml, config.propagation)

    # Stages 4-6 - snapshot loop.
    results: list[SnapshotKpi] = []
    n = config.runner.num_snapshots
    for i in range(n):
        snapshot = network_source.snapshot(i)
        path_gain_db = engine.compute_path_gain(snapshot)
        kpi = compute_kpis(snapshot, path_gain_db, config.kpi)
        results.append(kpi)
        if progress:
            mean_tp = (
                sum(u.throughput_mbps for u in kpi.ues) / len(kpi.ues)
                if kpi.ues
                else 0.0
            )
            print(f"[4/6] snapshot {i + 1}/{n}: mean UE throughput {mean_tp:.2f} Mbps")

    if progress:
        print("[6/6] Writing outputs ...")
    written = write_outputs(results, config.runner)
    if progress:
        for p in written:
            print(f"      wrote {p}")

    return results
