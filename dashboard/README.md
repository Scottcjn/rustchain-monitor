# RustChain Multi-Node Health Dashboard

A single-page HTML dashboard monitoring all 3 RustChain attestation nodes in real-time.

## Features

- **Real-time monitoring** of all 3 nodes (Node 1, 2, 3)
- **Auto-refresh** every 30 seconds (or manual refresh)
- **Color-coded status** — 🟢 Online / 🔴 Offline / 🟡 Loading
- **Per-node metrics**: version, uptime, DB status, backup age, tip age, miners, epoch
- **Session uptime tracker** with historical percentage bars
- **Summary row**: nodes online count, total miners, network version
- **Mobile responsive** layout
- **Zero backend** — pure JavaScript fetching from node APIs

## Nodes Monitored

| Node | URL | Role |
|------|-----|------|
| Node 1 | `https://50.28.86.131` | Primary |
| Node 2 | `https://50.28.86.153` | Secondary |
| Node 3 | `http://100.88.109.32:8099` | External (Tailscale) |

## Usage

Simply open `dashboard/index.html` in any browser — no build step required.

Or deploy to GitHub Pages for a permanent URL.

## APIs Used

- `GET /health` — node status, version, uptime, DB, backup age, tip age
- `GET /api/miners` — active miner count
- `GET /epoch` — current epoch number

## Bounty

Built for [RustChain Bounty #752](https://github.com/Scottcjn/rustchain-bounties/issues/752).
**RTC wallet:** nox-ventures
