import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rustchain_monitor


def _sample_snapshot():
    return {
        "generated_at": "2026-03-10T04:00:00Z",
        "generated_at_ts": 1_777_116_000.0,
        "node_url": "https://node.example",
        "health": {
            "ok": True,
            "version": "2.2.1-rip200",
            "db_rw": True,
            "uptime_s": 1234,
            "backup_age_hours": 1.5,
            "tip_age_slots": 2,
        },
        "epoch": {
            "epoch": 321,
        },
        "miners": [
            {"miner": "miner-a", "device_arch": "g4"},
            {"miner": "miner-b", "device_arch": "modern"},
        ],
        "summary": {
            "node_ok": True,
            "version": "2.2.1-rip200",
            "db_rw": True,
            "epoch_current": 321,
            "active_miners": 2,
            "uptime_seconds": 1234.0,
            "backup_age_hours": 1.5,
            "tip_age_slots": 2.0,
        },
        "hardware_distribution": {
            "g4": 1,
            "modern": 1,
        },
    }


def _history_summaries(tmp_path):
    db_path = tmp_path / "history.db"
    now_ts = 2_200_000_000.0

    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-a",
        epoch=320,
        balance_rtc=5.0,
        device_arch="g4",
        is_active=True,
        observed_at=now_ts - (7 * 86400),
    )
    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-a",
        epoch=321,
        balance_rtc=7.5,
        device_arch="g4",
        is_active=True,
        observed_at=now_ts - 60,
    )
    return rustchain_monitor.get_recorded_history_summaries(db_path, days=30, now_ts=now_ts)


def test_build_grafana_export_contains_series_and_tables(tmp_path):
    export = rustchain_monitor.build_grafana_export(_sample_snapshot(), _history_summaries(tmp_path))

    targets = [series["target"] for series in export["series"]]

    assert export["datasource_format"] == "grafana-simple-json-timeseries"
    assert any(target.startswith("rustchain_node_health_ok{") for target in targets)
    assert any("rustchain_hardware_miners" in target for target in targets)
    assert any("rustchain_history_gain_7d_rtc" in target for target in targets)
    assert [table["name"] for table in export["tables"]] == ["network_summary", "history_summaries"]


def test_render_prometheus_metrics_emits_expected_lines(tmp_path):
    body = rustchain_monitor.render_prometheus_metrics(_sample_snapshot(), _history_summaries(tmp_path))

    assert "# HELP rustchain_node_health_ok" in body
    assert 'rustchain_node_health_ok{node_url="https://node.example",version="2.2.1-rip200"} 1' in body
    assert 'rustchain_hardware_miners{device_arch="g4",node_url="https://node.example",version="2.2.1-rip200"} 1' in body
    assert 'rustchain_history_gain_7d_rtc{device_arch="g4",miner_id="miner-a",node_url="https://node.example"} 2.5' in body


def test_export_grafana_json_writes_json_file(tmp_path):
    output_path = tmp_path / "grafana-export.json"
    series_count = rustchain_monitor.export_grafana_json(
        output_path,
        snapshot=_sample_snapshot(),
        history_summaries=_history_summaries(tmp_path),
    )

    data = json.loads(output_path.read_text())

    assert series_count == len(data["series"])
    assert data["node_url"] == "https://node.example"
    assert data["snapshot"]["summary"]["active_miners"] == 2


def test_example_dashboard_json_is_valid():
    dashboard_path = ROOT / "dashboard" / "grafana-rustchain-monitor.json"
    data = json.loads(dashboard_path.read_text())
    target_exprs = [target["expr"] for panel in data["panels"] for target in panel.get("targets", [])]

    assert data["title"] == "RustChain Monitor Overview"
    assert "rustchain_node_health_ok{node_url=\"$node_url\"}" in target_exprs
    assert "sum by (device_arch) (rustchain_hardware_miners{node_url=\"$node_url\"})" in target_exprs
