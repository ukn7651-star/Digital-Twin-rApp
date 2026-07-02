"""End-to-end orchestration: scenario config -> per-UE/per-cell throughput.

The full digital-twin engine. Stages:
    1. build the 3D scene from OSM (no fallback)
    2. construct the (swappable) network data source (cells + UEs)
    3. ray-trace the channel frequency response (CFR) with Sionna RT
    4-5. KPIs: association + multi-cell SINR -> OAI-measured throughput mapping
         -> proportional-fair scheduling -> per-UE and per-cell throughput
    6. write the dataset (CSV/JSON) and export the CFR for OAI-in-the-loop runs

The throughput *mapping* (SINR -> MCS -> rate) is measured by OpenAirInterface's
real PHY, not a formula (see dtrapp/kpi/link_curve.py and oai/). The exported CFR
also lets OAI run over the exact ray-traced channel (see oai/README.md).
"""

from __future__ import annotations

from pathlib import Path

from dtrapp.config import SimulationConfig
from dtrapp.geometry import build_scene
from dtrapp.kpi import compute_kpis
from dtrapp.kpi.results import KpiResult
from dtrapp.network import CsvNetworkSource, NetworkDataSource, RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.runner.export import export_channel
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

    print(f"[1/4] Building scene from OSM bbox {config.bbox.as_overpass_bbox()} ...")
    artifacts = build_scene(config.bbox, out_dir / "scene", config)
    print(f"      {artifacts.num_buildings} buildings -> {artifacts.scene_xml}")

    print("[2/4] Generating network (cells + UEs) ...")
    if network_source is None:
        if config.cells_csv or config.ues_csv:
            network_source = CsvNetworkSource(config, artifacts.extent_m)
        else:
            network_source = RandomNetworkSource(config, artifacts.extent_m)
    network = network_source.generate()
    print(f"      {len(network.cells)} cells, {len(network.ues)} UEs")

    print("[3/4] Ray-tracing the channel (Sionna RT) ...")
    engine = SionnaPropagationEngine(artifacts.scene_xml, config)
    cfr = engine.compute_cfr(network)
    print(f"      CFR shape {tuple(cfr.shape)}")

    print("[4/4] KPIs (SINR -> OAI-measured throughput mapping) + outputs ...")
    result = compute_kpis(network, cfr, config)
    mean_tp = sum(u.throughput_mbps for u in result.ues) / len(result.ues) if result.ues else 0.0
    print(f"      {len(result.ues)} UEs, mean throughput {mean_tp:.2f} Mbps")
    for p in write_outputs(result, config):
        print(f"      wrote {p}")
    # Also export the raw channel so OAI can run over the exact RT channel.
    for p in export_channel(network, cfr, out_dir):
        print(f"      wrote {p}")
    return result
