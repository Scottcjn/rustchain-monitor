#!/usr/bin/env python3
"""
RustChain Network Monitor
A real-time monitoring tool for RustChain nodes and miners

Features:
- Live epoch tracking
- Miner status monitoring
- Reward calculations
- Hardware multiplier validation
- Network health checks
- Alert system for epoch settlements

Usage:
    python3 rustchain_monitor.py --node https://50.28.86.131
    python3 rustchain_monitor.py --miner your-miner-id --watch
"""

import argparse
import csv
import json
import sys
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional

import requests
import urllib3


# RustChain nodes commonly use self-signed certs in operator setups.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


DEFAULT_HISTORY_DB = Path.home() / ".rustchain-monitor" / "history.db"


def _history_db_path(db_path: str | Path) -> Path:
    return Path(db_path).expanduser()


def history_db_exists(db_path: str | Path) -> bool:
    return _history_db_path(db_path).exists()


def init_history_db(db_path: str | Path) -> Path:
    """Create the history database if it does not exist."""
    db_file = _history_db_path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS miner_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner_id TEXT NOT NULL,
                observed_at REAL NOT NULL,
                epoch INTEGER,
                balance_rtc REAL NOT NULL,
                delta_rtc REAL DEFAULT 0,
                device_arch TEXT DEFAULT '',
                is_active INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_miner_history_miner_time
                ON miner_history(miner_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_miner_history_miner_epoch
                ON miner_history(miner_id, epoch DESC);
            """
        )
    return db_file


def _history_connection(db_path: str | Path) -> sqlite3.Connection:
    db_file = init_history_db(db_path)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn


def _coerce_float(value, default: Optional[float] = 0.0) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value, default: Optional[int] = 0) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _health_db_rw(health: dict) -> bool:
    if "db_rw" in health:
        return bool(health.get("db_rw"))
    db_value = str(health.get("db", "") or "").lower()
    return "rw" in db_value


def record_history_snapshot(
    db_path: str | Path,
    *,
    miner_id: str,
    epoch: Optional[int],
    balance_rtc: float,
    device_arch: str = "",
    is_active: bool = False,
    observed_at: Optional[float] = None,
) -> bool:
    """Persist a miner balance snapshot unless it duplicates the latest point."""
    observed_at = time.time() if observed_at is None else observed_at
    with _history_connection(db_path) as conn:
        last = conn.execute(
            """
            SELECT epoch, balance_rtc, is_active, device_arch
            FROM miner_history
            WHERE miner_id = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (miner_id,),
        ).fetchone()

        if last:
            if (
                last["epoch"] == epoch
                and abs(float(last["balance_rtc"]) - float(balance_rtc)) < 1e-12
                and int(last["is_active"] or 0) == int(bool(is_active))
                and (last["device_arch"] or "") == (device_arch or "")
            ):
                return False
            delta_rtc = float(balance_rtc) - float(last["balance_rtc"])
        else:
            delta_rtc = 0.0

        conn.execute(
            """
            INSERT INTO miner_history
                (miner_id, observed_at, epoch, balance_rtc, delta_rtc, device_arch, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                miner_id,
                float(observed_at),
                epoch,
                float(balance_rtc),
                float(delta_rtc),
                device_arch or "",
                1 if is_active else 0,
            ),
        )
        conn.commit()
    return True


def _nearest_balance_before_or_after(conn: sqlite3.Connection, miner_id: str, cutoff_ts: float):
    row = conn.execute(
        """
        SELECT observed_at, balance_rtc
        FROM miner_history
        WHERE miner_id = ? AND observed_at <= ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (miner_id, cutoff_ts),
    ).fetchone()
    if row:
        return row
    return conn.execute(
        """
        SELECT observed_at, balance_rtc
        FROM miner_history
        WHERE miner_id = ? AND observed_at >= ?
        ORDER BY observed_at ASC, id ASC
        LIMIT 1
        """,
        (miner_id, cutoff_ts),
    ).fetchone()


def _history_rows(
    conn: sqlite3.Connection,
    miner_id: str,
    *,
    since_ts: Optional[float] = None,
) -> list[sqlite3.Row]:
    if since_ts is None:
        return conn.execute(
            """
            SELECT *
            FROM miner_history
            WHERE miner_id = ?
            ORDER BY observed_at ASC, id ASC
            """,
            (miner_id,),
        ).fetchall()
    return conn.execute(
        """
        SELECT *
        FROM miner_history
        WHERE miner_id = ? AND observed_at >= ?
        ORDER BY observed_at ASC, id ASC
        """,
        (miner_id, since_ts),
    ).fetchall()


def _period_gain(conn: sqlite3.Connection, miner_id: str, now_ts: float, days: int) -> float:
    cutoff_ts = now_ts - (days * 86400)
    latest = conn.execute(
        """
        SELECT observed_at, balance_rtc
        FROM miner_history
        WHERE miner_id = ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (miner_id,),
    ).fetchone()
    if not latest or float(latest["observed_at"]) < cutoff_ts:
        return 0.0

    start = _nearest_balance_before_or_after(conn, miner_id, cutoff_ts)
    if not start:
        return 0.0
    return float(latest["balance_rtc"]) - float(start["balance_rtc"])


def render_daily_gain_chart(day_rows: list[dict], width: int = 20) -> str:
    """Render a simple ASCII bar chart of daily gains."""
    if not day_rows:
        return "No daily history yet."
    max_gain = max(abs(float(row["gain"])) for row in day_rows) or 1.0
    lines = []
    for row in day_rows:
        gain = float(row["gain"])
        bar_len = int(round((abs(gain) / max_gain) * width))
        bar = ("#" * bar_len) or "."
        lines.append(f"{row['day']} | {bar:<{width}} {gain:+.6f} RTC")
    return "\n".join(lines)


def get_history_summary(
    db_path: str | Path,
    *,
    miner_id: str,
    now_ts: Optional[float] = None,
    days: int = 30,
) -> dict:
    """Return summary statistics for a miner's recorded history."""
    now_ts = time.time() if now_ts is None else now_ts
    with _history_connection(db_path) as conn:
        rows = _history_rows(conn, miner_id)
        if not rows:
            return {
                "miner_id": miner_id,
                "snapshots": 0,
                "latest_balance": 0.0,
                "latest_epoch": None,
                "first_seen": None,
                "last_seen": None,
                "total_gain": 0.0,
                "observed_daily_average": 0.0,
                "daily_gain_1d": 0.0,
                "daily_gain_7d": 0.0,
                "daily_gain_30d": 0.0,
                "daily_rows": [],
            }

        first = rows[0]
        latest = rows[-1]
        observed_seconds = max(0.0, float(latest["observed_at"]) - float(first["observed_at"]))
        observed_days = observed_seconds / 86400 if observed_seconds else 0.0
        total_gain = float(latest["balance_rtc"]) - float(first["balance_rtc"])

        since_ts = now_ts - (days * 86400)
        period_rows = _history_rows(conn, miner_id, since_ts=since_ts)
        baseline = _nearest_balance_before_or_after(conn, miner_id, since_ts)
        prior_balance = float(baseline["balance_rtc"]) if baseline else None
        day_closing = {}
        for row in period_rows:
            day_key = datetime.fromtimestamp(float(row["observed_at"]), timezone.utc).strftime("%Y-%m-%d")
            day_closing[day_key] = float(row["balance_rtc"])

        daily_rows = []
        for day_key in sorted(day_closing):
            closing_balance = day_closing[day_key]
            gain = 0.0 if prior_balance is None else closing_balance - prior_balance
            daily_rows.append({"day": day_key, "gain": round(gain, 6)})
            prior_balance = closing_balance

        return {
            "miner_id": miner_id,
            "snapshots": len(rows),
            "latest_balance": float(latest["balance_rtc"]),
            "latest_epoch": latest["epoch"],
            "latest_arch": latest["device_arch"] or "unknown",
            "latest_active": bool(latest["is_active"]),
            "first_seen": float(first["observed_at"]),
            "last_seen": float(latest["observed_at"]),
            "total_gain": total_gain,
            "observed_daily_average": (total_gain / observed_days) if observed_days else total_gain,
            "daily_gain_1d": _period_gain(conn, miner_id, now_ts, 1),
            "daily_gain_7d": _period_gain(conn, miner_id, now_ts, 7),
            "daily_gain_30d": _period_gain(conn, miner_id, now_ts, 30),
            "daily_rows": daily_rows,
        }


def compare_miner_history(
    db_path: str | Path,
    *,
    miner_ids: list[str],
    now_ts: Optional[float] = None,
    days: int = 7,
) -> list[dict]:
    """Compare miners by recent gain and current balance."""
    now_ts = time.time() if now_ts is None else now_ts
    rows = []
    for miner_id in miner_ids:
        summary = get_history_summary(db_path, miner_id=miner_id, now_ts=now_ts, days=max(days, 30))
        recent_gain = summary["daily_gain_7d"] if days == 7 else _period_value(summary, days)
        rows.append(
            {
                "miner_id": miner_id,
                "snapshots": summary["snapshots"],
                "latest_balance": summary["latest_balance"],
                "recent_gain": recent_gain,
                "daily_average": (recent_gain / days) if days else recent_gain,
                "latest_epoch": summary["latest_epoch"],
                "last_seen": summary["last_seen"],
            }
        )
    rows.sort(key=lambda row: (-row["recent_gain"], -row["latest_balance"], row["miner_id"]))
    return rows


def _period_value(summary: dict, days: int) -> float:
    if days <= 1:
        return summary["daily_gain_1d"]
    if days <= 7:
        return summary["daily_gain_7d"]
    return summary["daily_gain_30d"]


def export_history_csv(
    db_path: str | Path,
    *,
    miner_id: str,
    csv_path: str | Path,
    days: Optional[int] = None,
    now_ts: Optional[float] = None,
) -> int:
    """Export a miner's history rows to CSV."""
    now_ts = time.time() if now_ts is None else now_ts
    since_ts = None if days is None else now_ts - (days * 86400)
    with _history_connection(db_path) as conn:
        rows = _history_rows(conn, miner_id, since_ts=since_ts)

    out_path = Path(csv_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "observed_at_iso",
                "observed_at_ts",
                "miner_id",
                "epoch",
                "balance_rtc",
                "delta_rtc",
                "device_arch",
                "is_active",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    datetime.fromtimestamp(float(row["observed_at"]), timezone.utc).isoformat().replace("+00:00", "Z"),
                    float(row["observed_at"]),
                    row["miner_id"],
                    row["epoch"],
                    float(row["balance_rtc"]),
                    float(row["delta_rtc"]),
                    row["device_arch"] or "",
                    int(row["is_active"] or 0),
                ]
            )
    return len(rows)


def list_recorded_miners(db_path: str | Path) -> list[str]:
    db_file = _history_db_path(db_path)
    if not db_file.exists():
        return []
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT miner_id
            FROM miner_history
            ORDER BY miner_id ASC
            """
        ).fetchall()
    return [str(row[0]) for row in rows]


def get_recorded_history_summaries(
    db_path: str | Path,
    *,
    days: int = 30,
    now_ts: Optional[float] = None,
) -> list[dict]:
    db_file = _history_db_path(db_path)
    if not db_file.exists():
        return []
    summaries = []
    for miner_id in list_recorded_miners(db_file):
        summary = get_history_summary(db_file, miner_id=miner_id, now_ts=now_ts, days=max(days, 30))
        if summary["snapshots"] > 0:
            summaries.append(summary)
    summaries.sort(key=lambda row: row["miner_id"])
    return summaries


def _prometheus_escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_target(name: str, labels: Optional[dict] = None) -> str:
    if not labels:
        return name
    parts = [f'{key}="{_prometheus_escape(value)}"' for key, value in sorted(labels.items()) if value is not None]
    return f"{name}{{{','.join(parts)}}}"


def _append_metric(metrics: list[dict], name: str, value, labels: Optional[dict] = None) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        value = 1 if value else 0
    metrics.append({"name": name, "value": value, "labels": labels or {}})


def build_export_metrics(snapshot: dict, history_summaries: Optional[list[dict]] = None) -> list[dict]:
    summary = snapshot["summary"]
    labels = {
        "node_url": snapshot["node_url"],
        "version": summary.get("version", "unknown") or "unknown",
    }
    metrics: list[dict] = []

    _append_metric(metrics, "rustchain_export_generated_timestamp", snapshot.get("generated_at_ts"), {"node_url": snapshot["node_url"]})
    _append_metric(metrics, "rustchain_node_health_ok", summary.get("node_ok"), labels)
    _append_metric(metrics, "rustchain_node_db_rw", summary.get("db_rw"), labels)
    _append_metric(metrics, "rustchain_epoch_current", summary.get("epoch_current"), labels)
    _append_metric(metrics, "rustchain_miners_active", summary.get("active_miners"), labels)
    _append_metric(metrics, "rustchain_node_uptime_seconds", summary.get("uptime_seconds"), labels)
    _append_metric(metrics, "rustchain_node_backup_age_hours", summary.get("backup_age_hours"), labels)
    _append_metric(metrics, "rustchain_node_tip_age_slots", summary.get("tip_age_slots"), labels)

    for arch, count in sorted(snapshot.get("hardware_distribution", {}).items()):
        _append_metric(
            metrics,
            "rustchain_hardware_miners",
            count,
            {
                "node_url": snapshot["node_url"],
                "device_arch": arch,
            },
        )

    for summary_row in history_summaries or []:
        history_labels = {
            "node_url": snapshot["node_url"],
            "miner_id": summary_row["miner_id"],
            "device_arch": summary_row.get("latest_arch", "unknown") or "unknown",
        }
        _append_metric(metrics, "rustchain_history_snapshots", summary_row.get("snapshots"), history_labels)
        _append_metric(metrics, "rustchain_history_balance_rtc", summary_row.get("latest_balance"), history_labels)
        _append_metric(metrics, "rustchain_history_gain_1d_rtc", summary_row.get("daily_gain_1d"), history_labels)
        _append_metric(metrics, "rustchain_history_gain_7d_rtc", summary_row.get("daily_gain_7d"), history_labels)
        _append_metric(metrics, "rustchain_history_gain_30d_rtc", summary_row.get("daily_gain_30d"), history_labels)
        _append_metric(metrics, "rustchain_history_active", summary_row.get("latest_active"), history_labels)
        _append_metric(metrics, "rustchain_history_last_seen_timestamp", summary_row.get("last_seen"), history_labels)

    return metrics


PROMETHEUS_HELP = {
    "rustchain_export_generated_timestamp": "Unix timestamp when the RustChain monitor export was generated.",
    "rustchain_node_health_ok": "RustChain node health status where 1 means ok.",
    "rustchain_node_db_rw": "RustChain node database read-write health where 1 means writable.",
    "rustchain_epoch_current": "Current epoch reported by the RustChain node.",
    "rustchain_miners_active": "Number of active miners currently returned by the node.",
    "rustchain_node_uptime_seconds": "Node uptime in seconds.",
    "rustchain_node_backup_age_hours": "Age of the latest backup in hours.",
    "rustchain_node_tip_age_slots": "Age of the node chain tip in slots.",
    "rustchain_hardware_miners": "Active miner count grouped by device architecture.",
    "rustchain_history_snapshots": "Number of locally recorded history snapshots for a miner.",
    "rustchain_history_balance_rtc": "Latest locally recorded miner balance in RTC.",
    "rustchain_history_gain_1d_rtc": "Locally recorded 1-day miner gain in RTC.",
    "rustchain_history_gain_7d_rtc": "Locally recorded 7-day miner gain in RTC.",
    "rustchain_history_gain_30d_rtc": "Locally recorded 30-day miner gain in RTC.",
    "rustchain_history_active": "Latest locally recorded miner activity state where 1 means active.",
    "rustchain_history_last_seen_timestamp": "Unix timestamp of the latest locally recorded miner snapshot.",
}


def render_prometheus_metrics(snapshot: dict, history_summaries: Optional[list[dict]] = None) -> str:
    metrics = build_export_metrics(snapshot, history_summaries)
    names_in_order = []
    seen_names = set()
    for metric in metrics:
        name = metric["name"]
        if name not in seen_names:
            seen_names.add(name)
            names_in_order.append(name)

    lines = []
    for name in names_in_order:
        lines.append(f"# HELP {name} {PROMETHEUS_HELP.get(name, name)}")
        lines.append(f"# TYPE {name} gauge")
    for metric in metrics:
        lines.append(f"{_metric_target(metric['name'], metric['labels'])} {metric['value']}")
    lines.append("")
    return "\n".join(lines)


def build_grafana_export(snapshot: dict, history_summaries: Optional[list[dict]] = None) -> dict:
    metrics = build_export_metrics(snapshot, history_summaries)
    ts_ms = int(float(snapshot["generated_at_ts"]) * 1000)

    series = [
        {
            "target": _metric_target(metric["name"], metric["labels"]),
            "datapoints": [[metric["value"], ts_ms]],
        }
        for metric in metrics
    ]

    network_rows = [
        [metric["name"], metric["value"], json.dumps(metric["labels"], sort_keys=True)]
        for metric in metrics
        if not metric["name"].startswith("rustchain_history_")
    ]

    history_rows = [
        [
            row["miner_id"],
            row["snapshots"],
            row["latest_balance"],
            row["latest_epoch"],
            row["latest_arch"],
            1 if row["latest_active"] else 0,
            row["daily_gain_1d"],
            row["daily_gain_7d"],
            row["daily_gain_30d"],
            row["last_seen"],
        ]
        for row in history_summaries or []
    ]

    tables = [
        {
            "type": "table",
            "name": "network_summary",
            "columns": [{"text": "metric"}, {"text": "value"}, {"text": "labels_json"}],
            "rows": network_rows,
        }
    ]
    if history_rows:
        tables.append(
            {
                "type": "table",
                "name": "history_summaries",
                "columns": [
                    {"text": "miner_id"},
                    {"text": "snapshots"},
                    {"text": "latest_balance"},
                    {"text": "latest_epoch"},
                    {"text": "latest_arch"},
                    {"text": "latest_active"},
                    {"text": "gain_1d_rtc"},
                    {"text": "gain_7d_rtc"},
                    {"text": "gain_30d_rtc"},
                    {"text": "last_seen_ts"},
                ],
                "rows": history_rows,
            }
        )

    return {
        "generated_at": snapshot["generated_at"],
        "generated_at_ts": snapshot["generated_at_ts"],
        "node_url": snapshot["node_url"],
        "datasource_format": "grafana-simple-json-timeseries",
        "series": series,
        "tables": tables,
        "snapshot": snapshot,
        "history_summaries": history_summaries or [],
    }


def export_grafana_json(
    output_path: str | Path,
    *,
    snapshot: dict,
    history_summaries: Optional[list[dict]] = None,
) -> int:
    export = build_grafana_export(snapshot, history_summaries)
    out_path = Path(output_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as handle:
        json.dump(export, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return len(export["series"])


def parse_listen_address(listen: str) -> tuple[str, int]:
    host, sep, port_text = listen.rpartition(":")
    if not sep or not port_text:
        raise ValueError("listen address must be in host:port format")
    host = host or "0.0.0.0"
    port = int(port_text)
    if port <= 0 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    return host, port

# ANSI color codes for terminal output
class Colors:
    """ANSI escape codes for colored terminal output"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright foreground colors
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    
    # Background colors
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'


class RustChainMonitor:
    def __init__(
        self,
        node_url: str = "https://50.28.86.131",
        use_color: bool = True,
        history_db_path: Optional[str | Path] = None,
    ):
        self.node_url = node_url.rstrip('/')
        self.session = requests.Session()
        self.session.verify = False  # For self-signed certs
        self.use_color = use_color and sys.stdout.isatty()
        self.history_db_path = _history_db_path(history_db_path or DEFAULT_HISTORY_DB)
    
    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled"""
        if not self.use_color:
            return text
        return f"{color}{text}{Colors.RESET}"
    
    def _status(self, text: str) -> str:
        """Green for good status"""
        return self._colorize(text, Colors.BRIGHT_GREEN)
    
    def _warning(self, text: str) -> str:
        """Yellow for warnings"""
        return self._colorize(text, Colors.BRIGHT_YELLOW)
    
    def _error(self, text: str) -> str:
        """Red for errors"""
        return self._colorize(text, Colors.BRIGHT_RED)
    
    def _info(self, text: str) -> str:
        """Blue for info"""
        return self._colorize(text, Colors.BRIGHT_BLUE)
    
    def _accent(self, text: str) -> str:
        """Cyan for accent/highlight"""
        return self._colorize(text, Colors.BRIGHT_CYAN)
        
    def get_health(self) -> Dict:
        """Check node health"""
        response = self.session.get(f"{self.node_url}/health")
        return response.json()
    
    def get_epoch(self) -> Dict:
        """Get current epoch info"""
        response = self.session.get(f"{self.node_url}/epoch")
        return response.json()
    
    def get_miners(self) -> List[Dict]:
        """Get all active miners"""
        response = self.session.get(f"{self.node_url}/api/miners")
        return response.json()
    
    def get_miner_balance(self, miner_id: str) -> float:
        """Get specific miner's RTC balance"""
        response = self.session.get(f"{self.node_url}/wallet/balance?miner_id={miner_id}")
        return response.json().get("balance_rtc", 0.0)

    def collect_network_snapshot(self) -> dict:
        """Collect a single network snapshot for export surfaces."""
        health = self.get_health()
        epoch = self.get_epoch()
        miners = self.get_miners()
        generated_at_ts = time.time()

        hardware_distribution = {}
        for miner in miners if isinstance(miners, list) else []:
            arch = str(miner.get("device_arch") or "unknown").strip() or "unknown"
            hardware_distribution[arch] = hardware_distribution.get(arch, 0) + 1

        epoch_current = epoch.get("current_epoch", epoch.get("epoch"))
        summary = {
            "node_ok": bool(health.get("ok")),
            "version": health.get("version", "unknown") or "unknown",
            "epoch_current": _coerce_int(epoch_current, None),
            "active_miners": len(miners) if isinstance(miners, list) else _coerce_int((miners or {}).get("count"), 0),
            "uptime_seconds": _coerce_float(health.get("uptime_s", health.get("uptime")), None),
            "backup_age_hours": _coerce_float(health.get("backup_age_hours"), None),
            "tip_age_slots": _coerce_float(health.get("tip_age_slots"), None),
            "db_rw": _health_db_rw(health),
        }

        return {
            "generated_at": datetime.fromtimestamp(generated_at_ts, timezone.utc).isoformat().replace("+00:00", "Z"),
            "generated_at_ts": generated_at_ts,
            "node_url": self.node_url,
            "health": health,
            "epoch": epoch,
            "miners": miners,
            "summary": summary,
            "hardware_distribution": hardware_distribution,
        }
    
    def calculate_expected_reward(self, device_arch: str) -> float:
        """Calculate expected reward per epoch based on hardware"""
        multipliers = {
            "g4": 2.5,
            "g5": 2.0,
            "g3": 1.8,
            "power8": 1.5,
            "retro": 1.4,
            "apple_silicon": 1.2,
            "modern": 1.0
        }
        
        base_reward = 1.5  # RTC per epoch
        multiplier = multipliers.get(device_arch.lower(), 1.0)
        
        # This is simplified - actual calculation includes all miners
        return base_reward * multiplier

    def get_miner_snapshot(self, miner_id: str) -> dict:
        """Fetch a miner's current balance, epoch, and live status."""
        epoch_data = self.get_epoch()
        miners = self.get_miners()
        balance = self.get_miner_balance(miner_id)

        our_miner = None
        for miner in miners:
            if miner.get("miner") == miner_id or miner.get("miner_id") == miner_id:
                our_miner = miner
                break

        current_epoch = epoch_data.get("current_epoch", epoch_data.get("epoch"))
        device_arch = (our_miner or {}).get("device_arch", "unknown")
        last_attest = (our_miner or {}).get("last_attestation_time", 0) or 0
        is_active = bool(our_miner) and (time.time() - float(last_attest)) < 3600
        return {
            "epoch": current_epoch,
            "balance_rtc": balance,
            "miner": our_miner,
            "device_arch": device_arch,
            "is_active": is_active,
        }

    def record_history(self, miner_id: str, snapshot: dict) -> bool:
        return record_history_snapshot(
            self.history_db_path,
            miner_id=miner_id,
            epoch=snapshot.get("epoch"),
            balance_rtc=float(snapshot.get("balance_rtc", 0.0)),
            device_arch=snapshot.get("device_arch", "unknown"),
            is_active=bool(snapshot.get("is_active")),
        )

    def print_history_summary(self, miner_id: str, days: int = 30) -> None:
        summary = get_history_summary(self.history_db_path, miner_id=miner_id, days=days)
        if summary["snapshots"] == 0:
            print(f"No history recorded yet for miner {miner_id}.")
            return

        active_text = self._status("active") if summary["latest_active"] else self._warning("inactive")
        print(f"{self._accent('Historical Reward Summary')}")
        print(f"Miner:        {miner_id}")
        print(f"Snapshots:    {summary['snapshots']}")
        print(f"Latest epoch: {summary['latest_epoch']}")
        print(f"Latest arch:  {summary['latest_arch']}")
        print(f"Latest state: {active_text}")
        print(f"Latest bal:   {summary['latest_balance']:.6f} RTC")
        print(f"First seen:   {datetime.fromtimestamp(summary['first_seen'], timezone.utc).isoformat().replace('+00:00', 'Z')}")
        print(f"Last seen:    {datetime.fromtimestamp(summary['last_seen'], timezone.utc).isoformat().replace('+00:00', 'Z')}")
        print(f"Total gain:   {summary['total_gain']:+.6f} RTC")
        print(f"Observed avg: {summary['observed_daily_average']:+.6f} RTC/day")
        print(f"1d gain:      {summary['daily_gain_1d']:+.6f} RTC")
        print(f"7d gain:      {summary['daily_gain_7d']:+.6f} RTC")
        print(f"30d gain:     {summary['daily_gain_30d']:+.6f} RTC")
        print("\nDaily trend:")
        print(render_daily_gain_chart(summary["daily_rows"]))

    def compare_miners(self, miner_ids: list[str], days: int = 7) -> None:
        rows = compare_miner_history(self.history_db_path, miner_ids=miner_ids, days=days)
        if not rows:
            print("No history available for the requested miners.")
            return
        print(f"{self._accent(f'{days}-day historical comparison')}")
        print("miner_id                          balance_rtc    gain_rtc      daily_avg    snapshots")
        for row in rows:
            print(
                f"{row['miner_id'][:32]:32}  "
                f"{row['latest_balance']:11.6f}  "
                f"{row['recent_gain']:+11.6f}  "
                f"{row['daily_average']:+11.6f}  "
                f"{row['snapshots']:9}"
            )

    def export_history(self, miner_id: str, csv_path: str, days: Optional[int] = None) -> None:
        row_count = export_history_csv(
            self.history_db_path,
            miner_id=miner_id,
            csv_path=csv_path,
            days=days,
        )
        print(f"Exported {row_count} history rows to {csv_path}")

    def get_recorded_history_summaries(self, days: int = 30) -> list[dict]:
        return get_recorded_history_summaries(self.history_db_path, days=days)

    def export_grafana_json(self, output_path: str, days: int = 30) -> None:
        snapshot = self.collect_network_snapshot()
        history_summaries = self.get_recorded_history_summaries(days=days)
        series_count = export_grafana_json(
            output_path,
            snapshot=snapshot,
            history_summaries=history_summaries,
        )
        print(f"Exported {series_count} Grafana series to {output_path}")

    def serve_prometheus_metrics(self, listen: str, days: int = 30) -> None:
        host, port = parse_listen_address(listen)
        monitor = self

        class PrometheusHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                route = self.path.split("?", 1)[0]
                if route == "/healthz":
                    body = "ok\n".encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if route != "/metrics":
                    self.send_response(404)
                    self.end_headers()
                    return

                try:
                    snapshot = monitor.collect_network_snapshot()
                    history_summaries = monitor.get_recorded_history_summaries(days=days)
                    body = render_prometheus_metrics(snapshot, history_summaries).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as exc:
                    error_body = f"error collecting metrics: {exc}\n".encode()
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(error_body)))
                    self.end_headers()
                    self.wfile.write(error_body)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer((host, port), PrometheusHandler)
        endpoint = f"http://{host}:{port}/metrics"
        print(f"Serving Prometheus metrics on {endpoint}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping Prometheus metrics server.")
        finally:
            server.server_close()
    
    def watch_miner(self, miner_id: str, interval: int = 60, record_history_enabled: bool = False):
        """Watch a specific miner's status"""
        print(f"{self._accent('🔍')} Watching miner: {miner_id}")
        print(f"{self._info(f'Refresh interval: {interval} seconds')}\n")
        
        last_balance = 0.0
        last_epoch = 0
        
        while True:
            try:
                snapshot = self.get_miner_snapshot(miner_id)
                balance = float(snapshot["balance_rtc"])
                our_miner = snapshot["miner"]
                current_epoch = snapshot["epoch"] or 0
                
                # Clear screen
                print("\033[2J\033[H")
                
                # Color-coded status
                is_active = bool(snapshot["is_active"])
                status_color = Colors.BRIGHT_GREEN if is_active else Colors.BRIGHT_YELLOW
                status_text = "Active" if is_active else "Inactive"
                status_emoji = "🟢" if is_active else "🟡"
                
                # Display status with colors
                print(f"{self._accent('╔' + '═' * 58 + '╗')}")
                print(f"{self._accent('║')}  {self._accent('RustChain Miner Monitor')} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {self._accent('║')}")
                print(f"{self._accent('╠' + '═' * 58 + '╣')}")
                print(f"{self._accent('║')}  Miner ID: {miner_id[:40]:<40}  {self._accent('║')}")
                print(f"{self._accent('║')}  Balance:  {self._status(f'{balance:.6f} RTC'):<48} {self._accent('║')}")
                print(f"{self._accent('║')}  Epoch:    {self._info(str(current_epoch)):<48} {self._accent('║')}")
                print(f"{self._accent('╠' + '═' * 58 + '╣')}")
                
                if our_miner:
                    arch = snapshot["device_arch"]
                    expected = self.calculate_expected_reward(arch)
                    
                    print(f"{self._accent('║')}  Hardware: {arch:<48} {self._accent('║')}")
                    print(f"{self._accent('║')}  Expected: ~{expected:.6f} RTC/epoch{' ' * 19} {self._accent('║')}")
                    print(f"{self._accent('║')}  Status:   {self._colorize(f'{status_emoji} {status_text}', status_color):<48} {self._accent('║')}")
                else:
                    print(f"{self._accent('║')}  Status:   {self._warning('⚠️  Not found in active miners'):<48} {self._accent('║')}")
                
                print(f"{self._accent('╚' + '═' * 58 + '╝')}")
                
                # Check for new epoch
                if current_epoch > last_epoch and last_epoch > 0:
                    reward = balance - last_balance
                    print(f"\n{self._status('🎉 NEW EPOCH!')} {self._accent('Earned:')} {self._status(f'{reward:.6f} RTC')}")

                if record_history_enabled:
                    saved = self.record_history(miner_id, snapshot)
                    history_note = "saved" if saved else "unchanged"
                    print(f"\n{self._info(f'History snapshot: {history_note}')} -> {self.history_db_path}")
                
                last_balance = balance
                last_epoch = current_epoch
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print(f"\n\n{self._info('👋 Monitoring stopped')}")
                break
            except Exception as e:
                print(f"\n{self._error(f'❌ Error: {e}')}")
                time.sleep(interval)
    
    def network_summary(self):
        """Display network summary"""
        health = self.get_health()
        epoch = self.get_epoch()
        miners = self.get_miners()
        
        is_healthy = health.get('ok', False)
        node_status = self._status("✅ Healthy") if is_healthy else self._error("❌ Down")
        
        print(f"{self._accent('╔' + '═' * 44 + '╗')}")
        print(f"{self._accent('║')}      {self._accent('RustChain Network Summary')}         {self._accent('║')}")
        print(f"{self._accent('╠' + '═' * 44 + '╣')}")
        print(f"{self._accent('║')}  Node:    {node_status:<30} {self._accent('║')}")
        print(f"{self._accent('║')}  Epoch:   {self._info(str(epoch.get('current_epoch', 'N/A'))):<30} {self._accent('║')}")
        print(f"{self._accent('║')}  Miners:  {self._status(str(len(miners)))} active{' ' * 17} {self._accent('║')}")
        print(f"{self._accent('╚' + '═' * 44 + '╝')}\n")
        
        # Group by hardware
        by_arch = {}
        for m in miners:
            arch = m.get("device_arch", "unknown")
            by_arch[arch] = by_arch.get(arch, 0) + 1
        
        print(f"{self._accent('Hardware Distribution:')}")
        for arch, count in sorted(by_arch.items(), key=lambda x: -x[1]):
            # Color-code based on multiplier
            multipliers = {"g4": 2.5, "g5": 2.0, "g3": 1.8, "power8": 1.5, "retro": 1.4}
            if arch.lower() in multipliers:
                arch_str = self._colorize(arch, Colors.BRIGHT_GREEN)
            elif arch.lower() == "apple_silicon":
                arch_str = self._colorize(arch, Colors.BRIGHT_CYAN)
            else:
                arch_str = self._colorize(arch, Colors.WHITE)
            print(f"  {arch_str:15} : {self._status(str(count))} miners")

def main():
    parser = argparse.ArgumentParser(description="RustChain Network Monitor")
    parser.add_argument("--node", default="https://50.28.86.131", help="Node URL")
    parser.add_argument("--miner", help="Miner ID to watch")
    parser.add_argument("--watch", action="store_true", help="Watch mode (live updates)")
    parser.add_argument("--interval", type=int, default=60, help="Update interval (seconds)")
    parser.add_argument("--record-history", action="store_true", help="Record miner balance snapshots to a local SQLite history DB")
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB), help="SQLite path for historical reward tracking")
    parser.add_argument("--history-summary", action="store_true", help="Show stored reward history for --miner")
    parser.add_argument("--history-days", type=int, default=30, help="History window in days for summaries/exports")
    parser.add_argument("--export-csv", help="Export --miner history to CSV")
    parser.add_argument("--export-grafana-json", help="Export a Grafana-friendly JSON snapshot for the current node and recorded miner history")
    parser.add_argument("--prometheus-listen", help="Serve Prometheus metrics on host:port (example: 127.0.0.1:9108)")
    parser.add_argument("--compare", help="Comma-separated miner IDs to compare using stored history")
    parser.add_argument("--color", dest="color", action="store_true", default=True, help="Enable colored output (default: auto-detect)")
    parser.add_argument("--no-color", dest="color", action="store_false", help="Disable colored output")
    
    args = parser.parse_args()

    needs_history = bool(
        args.record_history
        or args.history_summary
        or args.export_csv
        or args.compare
        or args.export_grafana_json
        or args.prometheus_listen
    )
    monitor = RustChainMonitor(
        args.node,
        use_color=args.color,
        history_db_path=args.history_db if needs_history else None,
    )

    if args.prometheus_listen:
        monitor.serve_prometheus_metrics(args.prometheus_listen, days=args.history_days)
    elif args.export_grafana_json:
        monitor.export_grafana_json(args.export_grafana_json, days=args.history_days)
    elif args.compare:
        miner_ids = [miner_id.strip() for miner_id in args.compare.split(",") if miner_id.strip()]
        if not miner_ids:
            parser.error("--compare requires at least one miner ID")
        monitor.compare_miners(miner_ids, days=args.history_days)
    elif args.history_summary:
        if not args.miner:
            parser.error("--history-summary requires --miner")
        monitor.print_history_summary(args.miner, days=args.history_days)
    elif args.export_csv:
        if not args.miner:
            parser.error("--export-csv requires --miner")
        monitor.export_history(args.miner, args.export_csv, days=args.history_days)
    elif args.miner and args.watch:
        monitor.watch_miner(args.miner, args.interval, record_history_enabled=args.record_history)
    elif args.miner:
        snapshot = monitor.get_miner_snapshot(args.miner)
        balance = float(snapshot["balance_rtc"])
        print(f"Miner: {args.miner}")
        print(f"Balance: {balance:.6f} RTC")
        print(f"Epoch: {snapshot['epoch']}")
        print(f"Active: {'yes' if snapshot['is_active'] else 'no'}")
        print(f"Hardware: {snapshot['device_arch']}")
        if args.record_history:
            saved = monitor.record_history(args.miner, snapshot)
            print(f"History snapshot: {'saved' if saved else 'unchanged'} -> {monitor.history_db_path}")
    else:
        monitor.network_summary()

if __name__ == "__main__":
    main()
