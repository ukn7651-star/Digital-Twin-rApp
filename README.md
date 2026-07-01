# Digital-Twin-rApp — OAI engine

Standalone **OpenAirInterface (OAI)** toolkit: build the OAI 5G-NR stack, run a
gNB↔UE link in software (no radio hardware), and extract real PHY/MAC KPIs
(SINR, MCS, BLER, PRB, throughput) to CSV.

This branch is **OAI only** — it intentionally contains no other engine.

See **[`oai/README.md`](oai/README.md)** for the quickstart:

```bash
bash oai/setup_oai.sh                 # build OAI (gNB + UE)
bash oai/run_phytest.sh 30            # run a link, capture logs
python3 oai/collect_kpis.py oai_run/gnb.log oai_run/kpis.csv   # -> KPI CSV
```
