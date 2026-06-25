"""End-to-end orchestration: scenario config -> throughput result.

Wires the six stages together:
    1. build the 3D scene from OSM (no fallback)
    2. construct the (swappable) network data source
    3. ray-trace the channel (CFR) with Sionna RT
    4-5. Sionna SYS link-level chain: post-eq SINR -> link adaptation -> throughput
    6. write the dataset and return the KPIs
"""

from __future__ import annotations

from pathlib import Path

from dtrapp.config import SimulationConfig
from dtrapp.geometry import build_scene
from dtrapp.kpi import compute_kpis
from dtrapp.kpi.results import KpiResult
from dtrapp.network import NetworkDataSource, RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.runner.output import write_outputs


def run_simulation(
    config: SimulationConfig,
    network_source: NetworkDataSource | None = None,
) -> KpiResult:
    """Run the full pipeline and return the KPIs.

    Pass `network_source` to swap the random generator for a real-data source;
    everything downstream is unchanged.
    """
    out_dir = Path(config.output_dir)

    print(f"[1/3] Building scene from OSM bbox {config.bbox.as_overpass_bbox()} ...")
    artifacts = build_scene(config.bbox, out_dir / "scene", config)
    print(f"      {artifacts.num_buildings} buildings -> {artifacts.scene_xml}")

    if network_source is None:
        network_source = RandomNetworkSource(config, artifacts.extent_m)
    network = network_source.generate()

    print("[2/3] Ray-tracing the channel (Sionna RT) ...")
    engine = SionnaPropagationEngine(artifacts.scene_xml, config)
    cfr = engine.compute_cfr(network)

    print("      Computing link-level throughput (Sionna SYS) ...")
    result = compute_kpis(network, cfr, config)
    mean_tp = sum(u.throughput_mbps for u in result.ues) / len(result.ues) if result.ues else 0.0
    print(f"      {len(result.ues)} UEs, mean throughput {mean_tp:.2f} Mbps")

    print("[3/3] Writing outputs ...")
    for p in write_outputs(result, config):
        print(f"      wrote {p}")
    return result
