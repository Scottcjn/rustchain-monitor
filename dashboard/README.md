# RustChain Multi-Node Health Dashboard

A single-page HTML dashboard monitoring the RustChain attestation fleet in real-time.

**Fleet reality (verified 2026-09-21): two live nodes.** Node 3 is listed but disabled (expected down, not probed, not counted). Node 4 (`38.76.217.189`) is retired: its host now serves an unrelated web app that answers `200` HTML on every path, so it is deliberately absent.

## Features

- **Real-time monitoring** of the live fleet (Node 1, Node 2), with disabled nodes shown but not counted
- **Body-validated liveness** — a node is Online only if `/health` is `200`, JSON content type, parses, and has `ok: true`; HTML/non-JSON bodies are shown Offline with the reason
- **Auto-refresh** every 30 seconds (or manual refresh)
- **Color-coded status** — 🟢 Online / 🔴 Offline / 🟡 Loading
- **Per-node metrics**: version, uptime, DB status, backup age, tip age, miners, epoch
- **Session uptime tracker** with historical percentage bars
- **Summary row**: nodes online count, total miners, network version
- **Mobile responsive** layout
- **Zero backend** — pure JavaScript fetching from node APIs

## Nodes Monitored

| Node | URL | Role | Probed |
|------|-----|------|--------|
| Node 1 | `https://50.28.86.131` | Primary | yes |
| Node 2 | `https://50.28.86.153` | Secondary (`:8099` is not reachable from outside the VPS) | yes |
| Node 3 | `http://100.88.109.32:8099` | External (Tailscale) — offline since ~May 2026 | no (disabled) |

Keep this list in sync with `DEFAULT_MULTI_NODE_TARGETS` in `rustchain_monitor.py`; `tests/test_fleet_config_consistency.py` fails if they drift.

## Usage

Simply open `dashboard/index.html` in any browser — no build step required.

Or deploy to GitHub Pages for a permanent URL.

## Grafana

This repo now also ships a Prometheus-backed Grafana example dashboard:

- Import `dashboard/grafana-rustchain-monitor.json`
- Run the monitor exporter with:

```bash
python3 rustchain_monitor.py --prometheus-listen 127.0.0.1:9108
```

- Point Prometheus at `http://127.0.0.1:9108/metrics`
- In Grafana, select your Prometheus datasource and import the dashboard JSON

For file-based JSON ingestion instead of Prometheus:

```bash
python3 rustchain_monitor.py --export-grafana-json /tmp/rustchain-monitor.json
```

That payload is shaped for Grafana JSON / Infinity-style datasources and includes `series`, `tables`, and the raw snapshot payload.

For the built-in fleet exporter, import `dashboard/grafana-rustchain-fleet.json` and run:

```bash
python3 rustchain_monitor.py --all-nodes --prometheus-listen 127.0.0.1:9108
```

## APIs Used

- `GET /health` — node status, version, uptime, DB, backup age, tip age
- `GET /api/miners` — active miner count
- `GET /epoch` — current epoch number

## Bounty

Built for [RustChain Bounty #752](https://github.com/Scottcjn/rustchain-bounties/issues/752).
**RTC wallet:** nox-ventures
