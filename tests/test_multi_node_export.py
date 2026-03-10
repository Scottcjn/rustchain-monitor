import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rustchain_monitor


def _sample_snapshot(node_id, node_name, node_role, node_url, *, epoch, miners, version="2.2.1-rip200", scrape_ok=True, node_ok=True):
    return {
        "generated_at": "2026-03-10T16:00:00Z",
        "generated_at_ts": 1_777_160_000.0,
        "node_id": node_id,
        "node_name": node_name,
        "node_role": node_role,
        "node_url": node_url,
        "health": {"ok": node_ok, "version": version},
        "epoch": {"epoch": epoch},
        "miners": [],
        "summary": {
            "node_ok": node_ok,
            "scrape_ok": scrape_ok,
            "version": version,
            "epoch_current": epoch if scrape_ok else None,
            "active_miners": miners if scrape_ok else None,
            "uptime_seconds": 1000.0 if scrape_ok else None,
            "backup_age_hours": 1.5 if scrape_ok else None,
            "tip_age_slots": 2.0 if scrape_ok else None,
            "db_rw": True if scrape_ok else False,
        },
        "hardware_distribution": {"g4": 2} if scrape_ok else {},
        "error": "" if scrape_ok else "boom",
    }


def test_default_multi_node_targets_use_live_endpoints():
    targets = rustchain_monitor.default_multi_node_targets()

    assert [target["node_id"] for target in targets] == ["node1", "node2", "node3"]
    assert targets[0]["url"] == "https://50.28.86.131"
    assert targets[1]["url"] == "http://50.28.86.153:8099"
    assert targets[2]["url"] == "http://100.88.109.32:8099"


def test_build_multi_node_export_metrics_includes_aggregate_and_history_labels():
    snapshots = [
        _sample_snapshot("node1", "Node 1", "Primary", "https://node1.example", epoch=101, miners=18),
        _sample_snapshot("node2", "Node 2", "Secondary", "https://node2.example", epoch=100, miners=17),
        _sample_snapshot("node3", "Node 3", "External", "https://node3.example", epoch=0, miners=0, scrape_ok=False, node_ok=False, version="unreachable"),
    ]
    history_summaries = [
        {
            "miner_id": "miner-a",
            "snapshots": 5,
            "latest_balance": 9.5,
            "latest_epoch": 101,
            "latest_arch": "g4",
            "latest_active": True,
            "daily_gain_1d": 0.5,
            "daily_gain_7d": 2.0,
            "daily_gain_30d": 3.0,
            "last_seen": 1_777_160_000.0,
        }
    ]

    metrics = rustchain_monitor.build_multi_node_export_metrics(snapshots, history_summaries)

    def find_metric(name, **labels):
        for metric in metrics:
            if metric["name"] == name and all(metric["labels"].get(key) == value for key, value in labels.items()):
                return metric
        raise AssertionError(f"missing metric {name} with labels {labels}")

    assert find_metric("rustchain_nodes_configured_total", export_scope="multi_node")["value"] == 3
    assert find_metric("rustchain_nodes_scrape_ok_total", export_scope="multi_node")["value"] == 2
    assert find_metric("rustchain_network_epoch_disagreement", export_scope="multi_node")["value"] == 1
    assert find_metric("rustchain_network_active_miners_disagreement", export_scope="multi_node")["value"] == 1
    assert find_metric("rustchain_node_scrape_ok", node_id="node3", node_url="https://node3.example")["value"] == 0
    assert find_metric("rustchain_history_gain_7d_rtc", history_scope="local", miner_id="miner-a", device_arch="g4")["value"] == 2.0


def test_build_multi_node_grafana_export_has_node_snapshot_table():
    snapshots = [
        _sample_snapshot("node1", "Node 1", "Primary", "https://node1.example", epoch=101, miners=18),
        _sample_snapshot("node2", "Node 2", "Secondary", "https://node2.example", epoch=101, miners=18),
    ]

    export = rustchain_monitor.build_multi_node_grafana_export(snapshots, history_summaries=[])
    table_names = [table["name"] for table in export["tables"]]

    assert export["node_urls"] == ["https://node1.example", "https://node2.example"]
    assert "aggregate_summary" in table_names
    assert "node_metrics" in table_names
    assert "node_snapshots" in table_names


def test_collect_multi_node_snapshots_keeps_going_on_node_failure(monkeypatch):
    targets = [
        {"node_id": "node1", "name": "Node 1", "role": "Primary", "url": "https://node1.example"},
        {"node_id": "node2", "name": "Node 2", "role": "Secondary", "url": "https://node2.example"},
    ]

    def fake_collect(self):
        if self.node_url == "https://node2.example":
            raise RuntimeError("offline")
        return _sample_snapshot("node1", "Node 1", "Primary", self.node_url, epoch=101, miners=18)

    monkeypatch.setattr(rustchain_monitor.RustChainMonitor, "collect_network_snapshot", fake_collect)

    snapshots = rustchain_monitor.collect_multi_node_snapshots(targets)

    assert len(snapshots) == 2
    assert snapshots[0]["summary"]["scrape_ok"] is True
    assert snapshots[1]["summary"]["scrape_ok"] is False
    assert snapshots[1]["error"] == "offline"


def test_load_node_targets_accepts_dict_with_nodes_list(tmp_path):
    config_path = tmp_path / "nodes.json"
    config_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {"name": "Primary", "role": "Main", "url": "https://primary.example"},
                    {"name": "Backup", "url": "https://backup.example"},
                ]
            }
        )
    )

    targets = rustchain_monitor.load_node_targets(config_path)

    assert targets[0]["node_id"] == "primary"
    assert targets[1]["node_id"] == "backup"


def test_fleet_dashboard_json_is_valid():
    dashboard_path = ROOT / "dashboard" / "grafana-rustchain-fleet.json"
    data = json.loads(dashboard_path.read_text())
    target_exprs = [target["expr"] for panel in data["panels"] for target in panel.get("targets", [])]

    assert data["title"] == "RustChain Fleet Overview"
    assert "rustchain_nodes_scrape_ok_total{export_scope=\"multi_node\"}" in target_exprs
    assert "rustchain_epoch_current" in target_exprs
