"""End-to-end orchestration: scenario config -> throughput dataset.

Wires the six stages together:
    1. build the 3D scene from OSM (no fallback)
    2. construct the (swappable) network data source
    3. build the Sionna RT propagation engine
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
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.runner.output import write_outputs


def run_simulation(
    config: SimulationConfig,
    network_source: NetworkDataSource | None = None,
) -> list[SnapshotKpi]:
    """Run the full pipeline and return per-snapshot KPIs.

    Pass `network_source` to swap the random generator for a real-data source;
    everything downstream is unchanged.
    """
    out_dir = Path(config.output_dir)

    print(f"[1/3] Building scene from OSM bbox {config.bbox.as_overpass_bbox()} ...")
    artifacts = build_scene(config.bbox, out_dir / "scene", config)
    print(f"      {artifacts.num_buildings} buildings -> {artifacts.scene_xml}")

    if network_source is None:
        network_source = RandomNetworkSource(config, artifacts.extent_m)

    print("[2/3] Initializing Sionna RT engine ...")
    engine = SionnaPropagationEngine(artifacts.scene_xml, config)

    results: list[SnapshotKpi] = []
    for i in range(config.num_snapshots):
        snapshot = network_source.snapshot(i)
        path_gain_db = engine.compute_path_gain(snapshot)
        kpi = compute_kpis(snapshot, path_gain_db, config)
        results.append(kpi)
        mean_tp = sum(u.throughput_mbps for u in kpi.ues) / len(kpi.ues) if kpi.ues else 0.0
        print(f"      snapshot {i + 1}/{config.num_snapshots}: mean UE {mean_tp:.2f} Mbps")

    print("[3/3] Writing outputs ...")
    for p in write_outputs(results, config):
        print(f"      wrote {p}")
    return results
