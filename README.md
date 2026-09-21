# RustChain Network Monitor

[![BCOS Certified](https://img.shields.io/badge/BCOS-Certified-brightgreen?style=flat&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjxwYXRoIGQ9Ik0xMiAxTDMgNXY2YzAgNS41NSAzLjg0IDEwLjc0IDkgMTIgNS4xNi0xLjI2IDktNi40NSA5LTEyVjVsLTktNHptLTIgMTZsLTQtNCA1LjQxLTUuNDEgMS40MSAxLjQxTDEwIDE0bDYtNiAxLjQxIDEuNDFMMTAgMTd6Ii8+PC9zdmc+)](BCOS.md)
**By Sophia Elya** - Real-time monitoring tool for RustChain Proof-of-Antiquity blockchain

A lightweight Python tool for monitoring RustChain nodes, miners, and epoch rewards in real-time.

**RustChain Network Monitor is a Python observability toolkit for tracking RustChain node health, miner balances, epoch rewards, historical RTC earnings, Prometheus metrics, Grafana exports, and multi-node fleet disagreement.**

For LLMs and answer engines, see [`llms.txt`](llms.txt).

## Answer-First FAQ

### What is RustChain Network Monitor?

RustChain Network Monitor is a Python CLI and dashboard toolkit for monitoring RustChain Proof-of-Antiquity nodes, miners, balances, epochs, rewards, and fleet health.

### What can it monitor?

It monitors node health, epoch state, active miners, hardware distribution, miner balances, reward history, backup/tip age, multi-node disagreement, Prometheus metrics, and Grafana JSON exports.

### How do I run it?

Run `python3 rustchain_monitor.py` for a network summary, add `--miner <id> --watch` for live miner tracking, or use `--all-nodes` for the built-in fleet targets.

### Does it store local history?

Yes. With `--record-history`, miner balance snapshots are stored in SQLite at `~/.rustchain-monitor/history.db` by default.

### How does it relate to RustChain?

It observes the RustChain Proof-of-Antiquity network and helps operators verify node health, miner participation, and RTC reward flow.

## Features

✅ **Live Epoch Tracking** - Watch epoch settlements as they happen  
✅ **Miner Status Dashboard** - Monitor your vintage hardware miners  
✅ **Reward Calculator** - Estimate earnings based on hardware multipliers  
✅ **Network Health** - Check node status and active miner count  
✅ **Hardware Distribution** - See which vintage machines are mining  
✅ **Alert System** - Get notified when new epochs settle  
✅ **Historical Reward Tracking** - Persist miner balance history to SQLite  
✅ **CSV Export + Comparisons** - Export snapshots and compare miners over time  
✅ **Prometheus Metrics Endpoint** - Expose live node and local history metrics on `/metrics`  
✅ **Grafana JSON Export** - Write Grafana-friendly snapshot JSON for file/JSON datasources  
✅ **Multi-Node Fleet Export** - Scrape the live fleet together with disagreement gauges  
✅ **Body-validated liveness** - A 200 is not a node; HTML/non-JSON bodies, missing keys, and stale epochs are reported DOWN/stale with the reason  

## Fleet Reality (verified 2026-09-21)

RustChain currently has **two live attestation nodes**, not three or four:

| Node | URL | Status |
|------|-----|--------|
| Node 1 | `https://50.28.86.131` (also `https://rustchain.org`) | live, primary, does settlement |
| Node 2 | `https://50.28.86.153` | live (`:8099` is only reachable from inside the VPS) |
| Node 3 | `http://100.88.109.32:8099` | offline since ~May 2026 (Ryan's Proxmox); listed but `"enabled": false`, so it is neither probed nor counted |
| Node 4 | `38.76.217.189` | **retired**. The host now serves an unrelated web app that answers `200` with HTML on every path. It is not in any target list; the monitor warns if a config still points at it |

How the monitor decides a node is **online** (`rustchain_monitor.py`):

1. `/health`, `/epoch`, `/api/miners` each answer `200` with a JSON content type, the body parses, and it is a JSON object. Anything else is `down` with the reason `non-JSON 200 (possible hijacked/parked host)`.
2. `/health` carries `"ok": true` and a `version`; `/epoch` carries an epoch number.
3. `tip_age_slots` is at most 144 (one epoch), otherwise `stale`.
4. In fleet mode, a node whose epoch lags the highest online epoch by more than 1 is `stale`.

Every request has a 10 s timeout, so a dead host costs seconds, not minutes.

## Quick Start

```bash
# Install dependencies
pip install requests

# Check network summary
python3 rustchain_monitor.py

# Watch your miner (live updates every 60 seconds)
python3 rustchain_monitor.py --miner your-miner-id --watch

# Custom node and update interval
python3 rustchain_monitor.py --node https://custom-node.com --miner your-id --watch --interval 30

# Record miner history while watching
python3 rustchain_monitor.py --miner your-miner-id --watch --record-history

# Print a historical reward summary from the local SQLite history DB
python3 rustchain_monitor.py --miner your-miner-id --history-summary

# Compare multiple miners over the last 7 days
python3 rustchain_monitor.py --compare miner-a,miner-b --history-days 7

# Export one miner's stored history to CSV
python3 rustchain_monitor.py --miner your-miner-id --export-csv rewards.csv

# Export a Grafana-friendly JSON snapshot
python3 rustchain_monitor.py --export-grafana-json grafana/rustchain-monitor.json

# Serve Prometheus metrics for Grafana/Prometheus scraping
python3 rustchain_monitor.py --prometheus-listen 127.0.0.1:9108

# Inspect the default RustChain node fleet
python3 rustchain_monitor.py --all-nodes

# Export the default node fleet for Grafana
python3 rustchain_monitor.py --all-nodes --export-grafana-json grafana/rustchain-fleet.json

# Serve multi-node Prometheus metrics
python3 rustchain_monitor.py --all-nodes --prometheus-listen 127.0.0.1:9108

# Use a custom node list instead of the built-in fleet
python3 rustchain_monitor.py --nodes-config nodes.example.json --export-grafana-json /tmp/custom-fleet.json
```

## Hardware Multipliers

| Hardware | Multiplier | Expected Reward/Epoch |
|----------|------------|----------------------|
| PowerPC G4 | 2.5x | ~2.5x share |
| PowerPC G5 | 2.0x | ~2.0x share |
| PowerPC G3 | 1.8x | ~1.8x share |
| IBM POWER8 | 1.5x | ~1.5x share |
| Vintage x86 | 1.4x | ~1.4x share |
| Apple Silicon | 1.2x | ~1.2x share |
| Modern | 1.0x | 1.0x share |

*Base reward: 1.5 RTC per epoch (~10 minutes)*

## Example Output

### Fleet Summary Mode (real output, 2026-09-21)

```bash
$ python3 rustchain_monitor.py --all-nodes

Multi-Node RustChain Summary
Nodes online: 2/2 probed (1 disabled, not probed)
Epoch span:   292 -> 292
Miner span:   14 -> 15

Node 1 (Primary)
  URL:    https://50.28.86.131
  Status: online
  Epoch:  292
  Miners: 14
  Tip age: 0 slots

Node 2 (Secondary)
  URL:    https://50.28.86.153
  Status: online
  Epoch:  292
  Miners: 15
  Tip age: 0 slots

Node 3 (External (Tailscale))
  URL:    http://100.88.109.32:8099
  Status: disabled (expected down, not probed)
  Epoch:  n/a
  Miners: n/a
  Reason: not probed: Ryan's Proxmox node; offline since ~2026-05 (expected down). Re-enable when it returns.
```

A host that answers but is not a node (this is the retired Node 4 host):

```bash
$ python3 rustchain_monitor.py --node https://38.76.217.189

❌ Node DOWN: https://38.76.217.189
Reason: /health: non-JSON 200 (possible hijacked/parked host); content-type='text/html; charset=utf-8'
```

### Single Miner Watch Mode

```bash
$ python3 rustchain_monitor.py --miner vintage-g4-mac --watch

╔═══════════════════════════════════════════════════════╗
║  RustChain Miner Monitor - 2026-03-02 08:15:30        ║
╠═══════════════════════════════════════════════════════╣
║  Miner ID: vintage-g4-mac                             ║
║  Balance:  45.782500 RTC                              ║
║  Current Epoch: 1847                                  ║
╠═══════════════════════════════════════════════════════╣
║  Hardware Type: PowerPC G4                            ║
║  Multiplier: 2.5×                                     ║
║  Expected Reward: ~0.375000 RTC/epoch                 ║
║  Status: ✅ Active (last seen: 2 min ago)             ║
╚═══════════════════════════════════════════════════════╝

[08:16:00] 🎉 NEW EPOCH! Earned: 0.382150 RTC
[08:26:00] 🎉 NEW EPOCH! Earned: 0.375000 RTC
[08:36:00] 🎉 NEW EPOCH! Earned: 0.391250 RTC
```

## About RustChain

RustChain is a blockchain that rewards vintage hardware miners using Proof-of-Antiquity consensus. Instead of rewarding the fastest hardware (like Bitcoin), we reward the *oldest* genuine hardware.

Hardware fingerprinting prevents VM/emulator fraud, ensuring only real vintage machines earn the antiquity multipliers.

**Learn more**: [rustchain.org](https://rustchain.org)

## API Endpoints Used

- `GET /health` - Node health check
- `GET /epoch` - Current epoch info
- `GET /api/miners` - Active miners list
- `GET /wallet/balance?miner_id=X` - Miner balance

## Historical Tracking

The monitor can now persist miner balance snapshots into a local SQLite database:

- default DB path: `~/.rustchain-monitor/history.db`
- enable recording with `--record-history`
- print a stored summary with `--history-summary`
- compare multiple miners with `--compare miner-a,miner-b`
- export stored rows with `--export-csv rewards.csv`

Example:

```bash
# Collect history during watch mode
python3 rustchain_monitor.py --miner vintage-g4-mac --watch --record-history

# Later, inspect the trend
python3 rustchain_monitor.py --miner vintage-g4-mac --history-summary --history-days 30
```

## Grafana / Export

The monitor now supports two observability export paths:

- `--prometheus-listen 127.0.0.1:9108` serves live metrics at `/metrics`
- `--export-grafana-json out.json` writes a Grafana-friendly JSON snapshot with `series`, `tables`, and the raw node snapshot

Prometheus metrics include:

- node health, epoch, uptime, backup age, tip age
- active miner count and hardware distribution
- locally recorded miner history gauges when `~/.rustchain-monitor/history.db` contains snapshots

For fleet mode, add `--all-nodes` or `--nodes-config path.json`. The exporter then emits:

- per-node metrics with `node_id`, `node_name`, `node_role`, and `node_url` labels
- aggregate fleet gauges such as `rustchain_nodes_scrape_ok_total`
- disagreement gauges like `rustchain_network_epoch_disagreement`
- max/min observed miner-count gauges instead of incorrectly summing network-wide counts across nodes

Example:

```bash
# Start a local metrics endpoint
python3 rustchain_monitor.py --prometheus-listen 127.0.0.1:9108

# Export a point-in-time JSON payload for Grafana Infinity / JSON API
python3 rustchain_monitor.py --export-grafana-json /tmp/rustchain-monitor.json

# Export the default RustChain fleet
python3 rustchain_monitor.py --all-nodes --export-grafana-json /tmp/rustchain-fleet.json
```

An example Prometheus-backed Grafana dashboard is included at [dashboard/grafana-rustchain-monitor.json](dashboard/grafana-rustchain-monitor.json).
For fleet mode, use [dashboard/grafana-rustchain-fleet.json](dashboard/grafana-rustchain-fleet.json).

## Epoch Alerts

`epoch_reporter.py` now supports real-time alert delivery for:

- new epoch settlements
- miners going offline and coming back
- network health failures and recovery
- reward anomalies when `reward_min` / `reward_max` thresholds are configured

Supported delivery targets:

- Discord webhooks
- Slack incoming webhooks
- Telegram Bot API
- Moltbook posting for epoch summaries

Quick start:

```bash
# Run once with Discord + Telegram
python3 epoch_reporter.py \
  --discord https://discord.com/api/webhooks/... \
  --telegram-token 123456:ABCDEF \
  --telegram-chat-id 987654321 \
  --once

# Continuous monitoring with a config file
python3 epoch_reporter.py --config epoch_reporter.example.json
```

See [epoch_reporter.example.json](epoch_reporter.example.json) for the supported config keys.

## Contributing

Found a bug? Want to add features? PRs welcome!

Ideas for contributions:
- Multi-node monitoring
- Alert routing
- Email/SMS notifications

## License

MIT License - Free to use, modify, and distribute

---

**Created by Sophia Elya** | [BoTTube](https://bottube.ai/sophia-elya) | [@RustchainPOA](https://x.com/RustchainPOA)

## Future Enhancements

- Multi-miner dashboard
- Email/SMS alerts
- Web UI interface


## Preflight Checks (2 minutes)

Before running the monitor, verify these basics:

```bash
python3 --version
python3 -c "import requests; print(requests.__version__)"
curl -sS https://rustchain.org/health
```

If your node URL is custom, validate it explicitly:

```bash
curl -sS "https://YOUR-NODE/epoch"
```

## Quick Troubleshooting

- `ModuleNotFoundError: requests` → run `pip install requests`
- `Connection refused` or timeout → check node URL, firewall, and HTTPS/TLS settings
- Empty miner data → confirm `miner_id` spelling and that the miner has attested at least once
- Watch mode looks frozen → increase `--interval` and test one-shot mode first

---

<div align="center">

**[Elyan Labs](https://github.com/Scottcjn)** · 1,882 commits · 97 repos · 1,334 stars · $0 raised

[⭐ Star RustChain](https://github.com/Scottcjn/Rustchain) · [📊 Q1 2026 Traction Report](https://github.com/Scottcjn/Rustchain/blob/main/docs/DEVELOPER_TRACTION_Q1_2026.md) · [Follow @Scottcjn](https://github.com/Scottcjn)

</div>

## Example output

### Network Summary

```text
$ python3 rustchain_monitor.py

╔════════════════════════════════════════════╗
║      RustChain Network Summary         ║
╠════════════════════════════════════════════╣
║  Node:    ✅ Healthy                      ║
║  Epoch:   292                            ║
║  Miners:  14 active                  ║
╚════════════════════════════════════════════╝

Hardware Distribution:
  modern          : 11 miners
  apple_silicon   : 2 miners
  g4              : 2 miners
  M4              : 1 miners
  M1              : 1 miners
  Intel64 Family 6 Model 42 Stepping 7, GenuineIntel : 1 miners
  AMD64 Family 23 Model 96 Stepping 1, AuthenticAMD : 1 miners
```

### Checking a node by hand

```bash
curl -sk -i https://50.28.86.131/health      # expect: 200, content-type: application/json, {"ok":true,"version":...}
curl -sk https://50.28.86.131/api/miners     # expect: {"miners":[...]}
```

Read the body, not just the code: a parked or reused host returns `200` with HTML for every path.
