"""
prometheus_metrics.py — RustChain Prometheus Metrics Exporter
Bounty #765: Prometheus Metrics Exporter — Observable RustChain

Add to rustchain Flask app:
    from prometheus_metrics import metrics_bp, start_metrics_collector
    app.register_blueprint(metrics_bp)
    start_metrics_collector()

Or run standalone:
    python3 prometheus_metrics.py --port 9101 --node https://50.28.86.131

Author: noxventures_rtc
Wallet: noxventures_rtc
"""

import time
import threading
import os
import ssl
import json
import urllib.request
import urllib.error
from flask import Blueprint, Response

# Try prometheus_client; graceful fallback to manual text format
try:
    from prometheus_client import (
        Gauge, Counter, Histogram, Info, generate_latest, CONTENT_TYPE_LATEST,
        CollectorRegistry, REGISTRY
    )
    HAVE_PROMETHEUS = True
except ImportError:
    HAVE_PROMETHEUS = False

# ─── Configuration ─────────────────────────────────────────────────────────── #
NODE_URL = os.environ.get("RUSTCHAIN_NODE_URL", "https://50.28.86.131")
SCRAPE_INTERVAL = int(os.environ.get("METRICS_SCRAPE_INTERVAL", "60"))  # seconds
CTX = ssl._create_unverified_context()
REQUEST_TIMEOUT = 8

# ─── Prometheus Metrics ─────────────────────────────────────────────────────── #
if HAVE_PROMETHEUS:
    # Node health
    RC_UP                  = Gauge("rustchain_node_up", "1 if node is up and responding")
    RC_UPTIME              = Gauge("rustchain_node_uptime_seconds", "Node uptime in seconds")
    RC_VERSION             = Info("rustchain_node_version", "RustChain node version info")

    # Epoch state
    RC_EPOCH               = Gauge("rustchain_epoch_current", "Current epoch number")
    RC_EPOCH_SLOT          = Gauge("rustchain_epoch_slot", "Current slot within epoch")
    RC_EPOCH_MINERS        = Gauge("rustchain_epoch_enrolled_miners", "Miners enrolled in current epoch")
    RC_EPOCH_POT           = Gauge("rustchain_epoch_pot_rtc", "RTC in epoch reward pot")

    # Miners
    RC_MINERS_ACTIVE       = Gauge("rustchain_miners_active", "Active miners count")
    RC_MINERS_TOTAL        = Gauge("rustchain_miners_total", "Total miners registered")
    RC_ATTEST_AGE          = Gauge(
        "rustchain_attestation_age_seconds",
        "Seconds since last attestation per miner",
        ["miner"]
    )

    # Balances
    RC_TOTAL_SUPPLY        = Gauge("rustchain_total_supply_rtc", "Total RTC in circulation")
    RC_WALLET_BALANCE      = Gauge(
        "rustchain_wallet_balance_rtc",
        "Balance of tracked wallets",
        ["wallet"]
    )

    # Database
    RC_DB_SIZE             = Gauge("rustchain_db_size_bytes", "Database size in bytes")
    RC_BACKUP_AGE          = Gauge("rustchain_backup_age_hours", "Hours since last backup")

    # API performance
    RC_API_LATENCY         = Histogram(
        "rustchain_api_request_duration_seconds",
        "API endpoint latency",
        ["endpoint"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    )
    RC_SCRAPE_ERRORS       = Counter(
        "rustchain_metrics_scrape_errors_total",
        "Total scrape errors by endpoint",
        ["endpoint"]
    )

# ─── Helpers ────────────────────────────────────────────────────────────────── #
_metrics_cache = {}

def _fetch(path, timeout=REQUEST_TIMEOUT):
    """Fetch JSON from node. Returns (dict|list|None, elapsed_seconds)."""
    url = f"{NODE_URL.rstrip('/')}{path}"
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "rustchain-metrics/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
            data = json.loads(resp.read().decode())
            return data, time.time() - t0
    except Exception:
        return None, time.time() - t0


def _scrape():
    """Main scrape function — fetches all endpoints and updates Prometheus metrics."""
    # /health
    data, elapsed = _fetch("/health")
    if HAVE_PROMETHEUS:
        RC_API_LATENCY.labels(endpoint="/health").observe(elapsed)
    if data:
        RC_UP.set(1) if HAVE_PROMETHEUS else None
        uptime = data.get("uptime_seconds") or data.get("uptime") or 0
        version = data.get("version", "unknown")
        if HAVE_PROMETHEUS:
            RC_UPTIME.set(float(uptime))
            RC_VERSION.info({"version": version, "node_url": NODE_URL})
        _metrics_cache.update({
            "up": 1, "uptime_seconds": float(uptime), "version": version
        })
    else:
        if HAVE_PROMETHEUS:
            RC_UP.set(0)
            RC_SCRAPE_ERRORS.labels(endpoint="/health").inc()
        _metrics_cache["up"] = 0

    # /epoch
    data, elapsed = _fetch("/epoch")
    if HAVE_PROMETHEUS:
        RC_API_LATENCY.labels(endpoint="/epoch").observe(elapsed)
    if data:
        epoch = float(data.get("epoch", 0) or 0)
        slot = float(data.get("slot", data.get("epoch_slot", 0)) or 0)
        enrolled = float(data.get("enrolled_miners", data.get("miners_enrolled", 0)) or 0)
        pot = float(data.get("pot_rtc", data.get("reward_pot", 0)) or 0)
        if HAVE_PROMETHEUS:
            RC_EPOCH.set(epoch)
            RC_EPOCH_SLOT.set(slot)
            RC_EPOCH_MINERS.set(enrolled)
            RC_EPOCH_POT.set(pot)
        _metrics_cache.update({
            "epoch": epoch, "epoch_slot": slot,
            "epoch_enrolled_miners": enrolled, "epoch_pot_rtc": pot
        })
    else:
        if HAVE_PROMETHEUS:
            RC_SCRAPE_ERRORS.labels(endpoint="/epoch").inc()

    # /api/miners
    data, elapsed = _fetch("/api/miners")
    if HAVE_PROMETHEUS:
        RC_API_LATENCY.labels(endpoint="/api/miners").observe(elapsed)
    if data:
        miners = data if isinstance(data, list) else data.get("miners", [])
        active = [m for m in miners if m.get("status") == "active" or m.get("active")]
        if HAVE_PROMETHEUS:
            RC_MINERS_TOTAL.set(len(miners))
            RC_MINERS_ACTIVE.set(len(active))
            # Per-miner attestation age
            now = time.time()
            for m in miners[:50]:  # cap at 50 to avoid label explosion
                wallet = m.get("wallet_name", m.get("wallet", "unknown"))
                last_attest = m.get("last_attestation_time", m.get("last_attest", None))
                if last_attest:
                    age = now - float(last_attest)
                    RC_ATTEST_AGE.labels(miner=wallet).set(age)
        _metrics_cache.update({
            "miners_total": len(miners), "miners_active": len(active)
        })
    else:
        if HAVE_PROMETHEUS:
            RC_SCRAPE_ERRORS.labels(endpoint="/api/miners").inc()


def _background_scraper():
    """Run scrape loop in background thread."""
    while True:
        try:
            _scrape()
        except Exception:
            pass
        time.sleep(SCRAPE_INTERVAL)


def start_metrics_collector():
    """Start background scrape thread. Call once at app startup."""
    t = threading.Thread(target=_background_scraper, daemon=True)
    t.start()
    # Initial scrape immediately
    threading.Thread(target=_scrape, daemon=True).start()


# ─── Fallback text format (no prometheus_client) ────────────────────────────── #
def _manual_metrics_text():
    """Generate Prometheus text format manually when prometheus_client not available."""
    lines = []
    c = _metrics_cache
    now = time.time()

    def gauge(name, value, labels=None, help_text=""):
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
        lbl = ""
        if labels:
            lbl = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
        lines.append(f"{name}{lbl} {value}")

    gauge("rustchain_node_up", c.get("up", 0), help_text="1 if node is responding")
    gauge("rustchain_node_uptime_seconds", c.get("uptime_seconds", 0), help_text="Node uptime in seconds")
    gauge("rustchain_epoch_current", c.get("epoch", 0), help_text="Current epoch number")
    gauge("rustchain_epoch_slot", c.get("epoch_slot", 0), help_text="Current slot in epoch")
    gauge("rustchain_epoch_enrolled_miners", c.get("epoch_enrolled_miners", 0))
    gauge("rustchain_epoch_pot_rtc", c.get("epoch_pot_rtc", 0), help_text="RTC in reward pot")
    gauge("rustchain_miners_active", c.get("miners_active", 0), help_text="Active miners")
    gauge("rustchain_miners_total", c.get("miners_total", 0), help_text="Total miners registered")

    lines.append(f"# HELP rustchain_metrics_generated_at Unix timestamp of last scrape")
    lines.append(f"# TYPE rustchain_metrics_generated_at gauge")
    lines.append(f"rustchain_metrics_generated_at {now}")

    return "\n".join(lines) + "\n"


# ─── Flask Blueprint ─────────────────────────────────────────────────────────── #
metrics_bp = Blueprint("metrics", __name__)

@metrics_bp.route("/metrics")
def metrics_endpoint():
    """Prometheus-compatible /metrics endpoint."""
    if HAVE_PROMETHEUS:
        data = generate_latest(REGISTRY)
        return Response(data, mimetype=CONTENT_TYPE_LATEST)
    else:
        _scrape()  # synchronous scrape if no background thread
        return Response(_manual_metrics_text(), mimetype="text/plain; version=0.0.4; charset=utf-8")


# ─── Standalone mode ──────────────────────────────────────────────────────────── #
if __name__ == "__main__":
    import argparse
    from flask import Flask

    parser = argparse.ArgumentParser(description="RustChain Prometheus Metrics Exporter")
    parser.add_argument("--port", type=int, default=9101)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--node", default=NODE_URL)
    parser.add_argument("--interval", type=int, default=SCRAPE_INTERVAL)
    args = parser.parse_args()

    NODE_URL = args.node
    SCRAPE_INTERVAL = args.interval

    app = Flask(__name__)
    app.register_blueprint(metrics_bp)
    start_metrics_collector()

    print(f"RustChain Metrics Exporter")
    print(f"  Node:     {NODE_URL}")
    print(f"  Port:     {args.port}")
    print(f"  Interval: {SCRAPE_INTERVAL}s")
    print(f"  Metrics:  http://{args.host}:{args.port}/metrics")
    print(f"")
    print(f"  prometheus.yml scrape config:")
    print(f"    scrape_configs:")
    print(f"      - job_name: rustchain")
    print(f"        static_configs:")
    print(f"          - targets: ['localhost:{args.port}']")
    print(f"        scrape_interval: {SCRAPE_INTERVAL}s")
    print()

    app.run(host=args.host, port=args.port, debug=False)
