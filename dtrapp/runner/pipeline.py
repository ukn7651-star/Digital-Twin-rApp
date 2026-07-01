"""End-to-end orchestration: scenario config -> ray-traced channel for OAI.

Sionna RT half of the digital twin (there is no Sionna SYS here). Stages:
    1. build the 3D scene from OSM (no fallback)
    2. construct the (swappable) network data source (cells + UEs)
    3. ray-trace the channel frequency response (CFR) with Sionna RT
    4. export the CFR + network so the OAI stack can run over it (see oai/)

The throughput/KPIs are produced by OpenAirInterface (the real 5G-NR stack),
not by a model. See `oai/README.md` for the OAI side and the RT->OAI bridge.
"""

from __future__ import annotations

from pathlib import Path

from dtrapp.config import SimulationConfig
from dtrapp.geometry import build_scene
from dtrapp.network import NetworkDataSource, RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.runner.export import export_channel


def run_simulation(
    config: SimulationConfig,
    network_source: NetworkDataSource | None = None,
):
    """Build the scene, generate the network, ray-trace the channel, and export it.

    Returns ``(network, cfr)``. Pass `network_source` to swap the random generator
    for a real-data source; everything upstream is unchanged.
    """
    out_dir = Path(config.output_dir)

    print(f"[1/4] Building scene from OSM bbox {config.bbox.as_overpass_bbox()} ...")
    artifacts = build_scene(config.bbox, out_dir / "scene", config)
    print(f"      {artifacts.num_buildings} buildings -> {artifacts.scene_xml}")

    print("[2/4] Generating network (cells + UEs) ...")
    if network_source is None:
        network_source = RandomNetworkSource(config, artifacts.extent_m)
    network = network_source.generate()
    print(f"      {len(network.cells)} cells, {len(network.ues)} UEs")

    print("[3/4] Ray-tracing the channel (Sionna RT) ...")
    engine = SionnaPropagationEngine(artifacts.scene_xml, config)
    cfr = engine.compute_cfr(network)
    print(f"      CFR shape {tuple(cfr.shape)}  "
          f"[num_ues, num_ue_ant, num_cells, num_bs_ant, num_ofdm_symbols, num_sc]")

    print("[4/4] Exporting channel + network for OAI ...")
    for p in export_channel(network, cfr, out_dir):
        print(f"      wrote {p}")

    return network, cfr
