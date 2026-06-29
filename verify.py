#!/usr/bin/env python3
"""Manual, hand-checkable end-to-end verification of the dtrapp pipeline.

For every stage it prints:
    EXPECTED  <value>   <- where the number comes from (formula / code line)
    ACTUAL    <value>   <- what the code actually produced
    PASS/FAIL

It uses NO network (canned OSM JSON) and NO Sionna (the analytical engine),
so it is fully deterministic and you can re-run it any time:

    python3 verify.py

Every EXPECTED value is derived independently here (plain math), so this is a
genuine cross-check of the library code, not a copy of it.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

PASS, FAIL = "PASS", "FAIL"
_results: list[bool] = []


def check(label: str, expected, actual, tol: float = 1e-6, source: str = "") -> None:
    """Compare expected vs actual (numbers within tol, else equality)."""
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        ok = abs(float(expected) - float(actual)) <= tol
    else:
        ok = expected == actual
    _results.append(ok)
    print(f"  {label}")
    if source:
        print(f"     source : {source}")
    print(f"     EXPECTED: {expected}")
    print(f"     ACTUAL  : {actual}")
    print(f"     -> {PASS if ok else FAIL}\n")


def header(title: str) -> None:
    print("=" * 72)
    print(title)
    print("=" * 72)


# ===========================================================================
header("STAGE 1a - PROJECTION  (dtrapp/geometry/projection.py)")
# ===========================================================================
# Source formula (equirectangular tangent plane):
#   east  = R * radians(dlon) * cos(lat0)
#   north = R * radians(dlat)
#   R = 6_378_137 m (WGS84 equatorial radius, projection.py line 15)
from dtrapp.geometry.projection import LocalProjection

R = 6_378_137.0
proj = LocalProjection(52.5, 13.4)  # origin = scene center

# Point 0.0002 deg EAST of origin (same latitude) -> pure east offset.
e1, n1 = proj.to_local(52.5, 13.4002)
exp_e1 = R * math.radians(0.0002) * math.cos(math.radians(52.5))
check("east offset for +0.0002 deg lon", exp_e1, e1,
      source="R*radians(dlon)*cos(lat0) = 6378137*radians(0.0002)*cos(52.5deg)")
check("north offset is zero (same lat)", 0.0, n1)

# Point 0.0002 deg NORTH of origin -> pure north offset.
e2, n2 = proj.to_local(52.5002, 13.4)
exp_n2 = R * math.radians(0.0002)
check("north offset for +0.0002 deg lat", exp_n2, n2,
      source="R*radians(dlat) = 6378137*radians(0.0002)")

# Origin must map exactly to (0, 0).
check("origin -> (0,0)", (0.0, 0.0), proj.to_local(52.5, 13.4))

# Round-trip back to lat/lon.
check("round-trip lat", 52.5002, proj.to_latlon(e2, n2)[0], tol=1e-9,
      source="to_latlon(to_local(p)) == p")


# ===========================================================================
header("STAGE 1b - EXTRUSION + SCENE  (extrude.py, scene_builder.py)")
# ===========================================================================
from dtrapp.config import BoundingBox, GeometryConfig
from dtrapp.geometry import build_scene
from dtrapp.geometry.extrude import extrude_building
from dtrapp.geometry.overpass import Building

# A square footprint, 10 m tall.
b = Building(
    outline_latlon=[(52.5000, 13.4000), (52.5000, 13.4002),
                    (52.5002, 13.4002), (52.5002, 13.4000)],
    height_m=10.0, osm_id=100,
)
mesh = extrude_building(b, LocalProjection(52.5001, 13.4001))
# A box from a 4-corner footprint: 4 corners x (bottom+top) = 8 vertices;
# walls 4 edges x 2 tris = 8, + roof 2 + floor 2 = 12 faces. (extrude.py 53-78)
check("prism vertex count (4-corner square)", 8, len(mesh.vertices),
      source="extrude_building: n bottom + n top vertices, n=4")
check("prism face count", 12, len(mesh.faces),
      source="walls 4*2 + roof (n-2) + floor (n-2) = 8+2+2")
(_, _, minz), (_, _, maxz) = mesh.bounds()
check("mesh min z", 0.0, minz, source="floor at z=0")
check("mesh max z", 10.0, maxz, source="roof at building height = 10 m")

# Build the full scene from canned OSM (no network).
canned = {"elements": [
    {"type": "node", "id": 1, "lat": 52.5000, "lon": 13.4000},
    {"type": "node", "id": 2, "lat": 52.5000, "lon": 13.4002},
    {"type": "node", "id": 3, "lat": 52.5002, "lon": 13.4002},
    {"type": "node", "id": 4, "lat": 52.5002, "lon": 13.4000},
    {"type": "way", "id": 100, "nodes": [1, 2, 3, 4, 1],
     "tags": {"building": "yes", "height": "12"}},
]}
tmp = Path(tempfile.mkdtemp())
art = build_scene(BoundingBox(52.4999, 13.3999, 52.5003, 13.4003), tmp,
                  GeometryConfig(), overpass_json=canned)
check("buildings parsed", 1, art.num_buildings)
check("scene.xml written", True, art.scene_xml.exists())
check("building .ply written", True, (tmp / "meshes" / "bldg-100.ply").exists())
check("ground .ply written", True, (tmp / "meshes" / "ground.ply").exists())
xml = art.scene_xml.read_text()
check("scene.xml references building shape", True, 'id="bldg-100"' in xml)
check("scene.xml references concrete material", True, "mat-itu_concrete" in xml)


# ===========================================================================
header("STAGE 2 - NETWORK  (dtrapp/network/random_source.py)")
# ===========================================================================
from dtrapp.config import NetworkConfig
from dtrapp.network import RandomNetworkSource

extent = (-200.0, -200.0, 200.0, 200.0)
cfg = NetworkConfig(seed=42, num_sites=3, sectors_per_site=3, num_ues=30)
src = RandomNetworkSource(cfg, extent, num_snapshots=2)
snap = src.snapshot(0)
# Cells = num_sites * sectors_per_site; UEs = num_ues. (random_source 61-97)
check("cell count = sites*sectors", 9, len(snap.cells),
      source="3 sites * 3 sectors")
check("UE count", 30, len(snap.ues), source="num_ues")

# Sectors of one site are spaced 360/sectors = 120 deg apart. (line 70)
site0_az = sorted(c.azimuth_deg for c in snap.cells if c.site_id == 0)
gaps = [round((site0_az[i + 1] - site0_az[i]), 3) for i in range(len(site0_az) - 1)]
check("3 distinct sector azimuths on site 0", 3, len(set(site0_az)))
check("azimuth spacing = 120 deg", [120.0, 120.0], gaps,
      source="az = base + sector*360/3")

# Reproducibility: same seed -> identical cell + UE positions. (default_rng(seed))
src_b = RandomNetworkSource(NetworkConfig(seed=42, num_sites=3, sectors_per_site=3,
                                          num_ues=30), extent, num_snapshots=2)
same = ([c.position for c in snap.cells] ==
        [c.position for c in src_b.snapshot(0).cells])
check("same seed -> identical layout", True, same,
      source="np.random.default_rng(seed) is deterministic")


# ===========================================================================
header("STAGE 3 - PROPAGATION  (dtrapp/propagation/analytical.py)")
# ===========================================================================
# Controlled geometry: one cell at (0,0,25), boresight +x (az=0, tilt=0).
# UE at (100,0,25): exactly 100 m away, ON boresight (angle 0 -> 0 dB pattern loss).
# Analytical model (analytical.py 54-63), defaults n=3, max_gain=15 dBi, f=3.5 GHz:
#   wavelength = c/f
#   FSPL@1m    = 20*log10(4*pi/wavelength)
#   PL(d)      = FSPL@1m + 10*n*log10(d)
#   gain_dB    = antenna_gain(=15, on boresight) - PL(d)
from dtrapp.config import PropagationConfig
from dtrapp.network.models import Cell, NetworkSnapshot, UE
from dtrapp.propagation import AnalyticalPropagationEngine

cell = Cell("c0", 0, 0, (0.0, 0.0, 25.0), azimuth_deg=0.0, downtilt_deg=0.0,
            tx_power_dbm=46.0, carrier_freq_hz=3.5e9, bandwidth_hz=20e6)
ue = UE("ue0", (100.0, 0.0, 25.0), traffic_demand_mbps=50.0, noise_figure_db=7.0)
snap1 = NetworkSnapshot(0, [cell], [ue])

C = 299_792_458.0
wavelength = C / 3.5e9
fspl_1m = 20.0 * math.log10(4.0 * math.pi / wavelength)
pl_100 = fspl_1m + 10.0 * 3.0 * math.log10(100.0)
exp_gain = 15.0 - pl_100  # on boresight => antenna attenuation = 0

eng = AnalyticalPropagationEngine(config=PropagationConfig())
G = eng.compute_path_gain(snap1)
check("path-gain matrix shape (1 UE, 1 cell)", (1, 1), G.shape)
check("FSPL @ 1 m (3.5 GHz)", 43.32914, fspl_1m, tol=1e-4,
      source="20*log10(4*pi/(c/f)), c=2.99792458e8, f=3.5e9")
check("path gain at 100 m on boresight (dB)", exp_gain, float(G[0, 0]), tol=1e-4,
      source="15 dBi - (FSPL@1m + 30*log10(100))")


# ===========================================================================
header("STAGE 4 - SINR  (dtrapp/kpi/sinr.py)")
# ===========================================================================
from dtrapp.kpi.sinr import (associate_cells, compute_received_power_dbm,
                             compute_sinr_db, thermal_noise_dbm)

# Received power = Tx power + path gain. (sinr.py compute_received_power_dbm)
exp_rx = 46.0 + exp_gain
rx = compute_received_power_dbm(G, np.array([46.0]))
check("received power (dBm) = Ptx + gain", exp_rx, float(rx[0, 0]), tol=1e-4,
      source="Rx = 46 dBm + gain")

# Thermal noise = 10*log10(k*T*B*1e3) + NF.  (sinr.py thermal_noise_dbm)
k = 1.380649e-23
exp_noise = 10.0 * math.log10(k * 290.0 * 20e6 * 1e3) + 7.0
noise = float(thermal_noise_dbm(20e6, 7.0, 290.0))
check("thermal noise (dBm), B=20MHz NF=7", exp_noise, noise, tol=1e-6,
      source="10*log10(kTB/1mW)+NF, k=1.380649e-23, T=290")

# Single cell => no interference. SINR_lin = signal_mw / noise_mw.
signal_mw = 10 ** (exp_rx / 10.0)
noise_mw = 10 ** (exp_noise / 10.0)
exp_sinr = 10.0 * math.log10(signal_mw / noise_mw)
sinr = compute_sinr_db(rx, np.array([0]), np.array([exp_noise]),
                       sinr_min_db=-100.0, sinr_max_db=100.0)
check("SINR (dB), single cell, noise-limited", exp_sinr, float(sinr[0]), tol=1e-4,
      source="10*log10(signal_mw/noise_mw); interference=0")

# Association: the only cell is the serving cell, and it's above -140 dBm.
serving, covered = associate_cells(rx, min_rx_power_dbm=-140.0)
check("serving cell index", 0, int(serving[0]))
check("covered (rx > -140 dBm)", True, bool(covered[0]))


# ===========================================================================
header("STAGE 5 - THROUGHPUT  (dtrapp/kpi/throughput.py)")
# ===========================================================================
from dtrapp.kpi.throughput import shannon_throughput, spectral_efficiency

# SE = log2(1 + SINR_lin).  (throughput.py spectral_efficiency)
sinr_lin = 10 ** (exp_sinr / 10.0)
exp_se = math.log2(1.0 + sinr_lin)
se = float(spectral_efficiency(np.array([exp_sinr]), se_cap=1e3)[0])
check("spectral efficiency (bit/s/Hz)", exp_se, se, tol=1e-4,
      source="log2(1+SINR_lin)")

# One UE alone on the cell -> full bandwidth. R = B*SE.  (throughput 67-73)
exp_tput = 20e6 * exp_se / 1e6  # Mbps
ue_mbps, cell_mbps = shannon_throughput(np.array([exp_sinr]), np.array([0]),
                                        np.array([20e6]), num_cells=1,
                                        se_cap=1e3)
check("UE throughput (Mbps), alone on cell", exp_tput, float(ue_mbps[0]), tol=1e-3,
      source="(B / 1 UE) * SE / 1e6")

# Resource sharing: 2 UEs on cell0, 1 on cell1, all SINR=0 dB (SE=1).
# cell0 splits 20 MHz -> 10 Mbps each; cell1 UE gets full 20 MHz. (kpi test mirror)
ue2, cell2 = shannon_throughput(np.array([0.0, 0.0, 0.0]), np.array([0, 0, 1]),
                                np.array([20e6, 20e6]), num_cells=2)
check("shared cell: each of 2 UEs gets 10 Mbps", [10.0, 10.0],
      [round(float(ue2[0]), 6), round(float(ue2[1]), 6)],
      source="B/2 * log2(1+1) = 10e6*1 = 10 Mbps")
check("lone UE on other cell gets 20 Mbps", 20.0, float(ue2[2]), tol=1e-6)


# ===========================================================================
header("STAGE 6 - END-TO-END + OUTPUT  (kpi/engine.py, runner/output.py)")
# ===========================================================================
# Wire the real pipeline body offline: canned scene + random net + analytical
# engine + KPI + output writer (exactly what runner/pipeline.run_simulation does,
# minus the live Overpass fetch).
from dtrapp.config import KpiConfig, RunnerConfig
from dtrapp.kpi import compute_kpis
from dtrapp.runner.output import write_outputs

net = RandomNetworkSource(NetworkConfig(seed=7, num_sites=2, sectors_per_site=3,
                                        num_ues=12), art.extent_m, num_snapshots=1)
eng2 = AnalyticalPropagationEngine(config=PropagationConfig())
s0 = net.snapshot(0)
gains = eng2.compute_path_gain(s0)
kpi = compute_kpis(s0, gains, KpiConfig())
check("KPI per-UE rows == UE count", 12, len(kpi.ues))
check("KPI per-cell rows == cell count", 6, len(kpi.cells))
check("every covered UE has a serving cell", True,
      all(u.serving_cell != "" for u in kpi.ues if u.covered))
# Conservation: sum of per-UE throughput == sum of per-cell throughput. (engine.py)
sum_ue = round(sum(u.throughput_mbps for u in kpi.ues), 6)
sum_cell = round(sum(c.throughput_mbps for c in kpi.cells), 6)
check("sum(UE tput) == sum(cell tput)", sum_ue, sum_cell, tol=1e-6,
      source="per-cell tput is the sum of its UEs' tput")

out = Path(tempfile.mkdtemp())
written = write_outputs([kpi], RunnerConfig(output_dir=str(out), write_csv=True,
                                            write_json=True, write_heatmap=True))
names = {p.name for p in written}
check("ue_throughput.csv written", True, "ue_throughput.csv" in names)
check("cell_throughput.csv written", True, "cell_throughput.csv" in names)
check("throughput.json written", True, "throughput.json" in names)
check("heatmap PNG written", True, "heatmap_snapshot0.png" in names)


# ===========================================================================
header("PHYSICS SANITY - closer UE gets higher throughput")
# ===========================================================================
near = UE("near", (15.0, 0.0, 1.5), 50.0, 7.0)
far = UE("far", (150.0, 0.0, 1.5), 50.0, 7.0)
ssnap = NetworkSnapshot(0, [cell], [near, far])
g = AnalyticalPropagationEngine().compute_path_gain(ssnap)
res = compute_kpis(ssnap, g, KpiConfig(sinr_max_db=100.0,
                                       max_spectral_efficiency=1e3))
check("near UE SINR > far UE SINR", True, res.ues[0].sinr_db > res.ues[1].sinr_db,
      source="path loss grows with distance -> lower SINR far away")
check("near UE throughput > far UE throughput", True,
      res.ues[0].throughput_mbps > res.ues[1].throughput_mbps)


# ===========================================================================
print("=" * 72)
passed = sum(_results)
total = len(_results)
print(f"RESULT: {passed}/{total} checks PASSED")
print("=" * 72)
raise SystemExit(0 if passed == total else 1)
