"""Liveness must be decided by the response BODY, never by the status code alone.

Background: a retired node's host (38.76.217.189) was reused for an unrelated
single-page app behind nginx. An SPA answers 200 with HTML on every unknown
path, so /health and /epoch both "succeed" forever if only the code is read.
The fixture in tests/fixtures/hijacked_host_spa.html is the real body that host
returned for GET /health on 2026-09-21.
"""

import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rustchain_monitor  # noqa: E402
from rustchain_monitor import (  # noqa: E402
    NON_JSON_200_REASON,
    NodeLivenessError,
    RustChainMonitor,
    assess_fleet_epoch_agreement,
    collect_multi_node_snapshots,
    parse_node_json,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SPA_HTML = (FIXTURES / "hijacked_host_spa.html").read_text()

# Real payloads captured from https://50.28.86.131 on 2026-09-21.
REAL_HEALTH = '{"backup_age_hours":13.73,"db_rw":true,"ok":true,"tip_age_slots":0,"uptime_s":153633,"version":"2.2.1-rip200"}'
REAL_EPOCH = '{"blocks_per_epoch":144,"enrolled_miners":14,"epoch":292,"epoch_pot":1.5,"slot":42172,"total_supply_rtc":8388608}'
REAL_MINERS = (
    '{"miners":[{"antiquity_multiplier":0.0005,"device_arch":"aarch64","miner":"pi4"},'
    '{"antiquity_multiplier":0.8,"device_arch":"modern","miner":"victus"},'
    '{"antiquity_multiplier":2.5,"device_arch":"g4","miner":"dual-g4-125"}]}'
)


class FakeResponse:
    def __init__(self, body: str, *, status_code: int = 200, content_type: str = "application/json"):
        self.text = body
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type is not None else {}


def _real_node_routes(health: str = REAL_HEALTH, epoch: str = REAL_EPOCH, miners: str = REAL_MINERS) -> dict:
    return {"/health": FakeResponse(health), "/epoch": FakeResponse(epoch), "/api/miners": FakeResponse(miners)}


def _install_fake_session(monkeypatch, routes_by_host: dict, calls: list | None = None):
    """Route session.get(url) -> FakeResponse by (host, path); a raised exception in the table is raised."""

    def fake_get(self, url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        for base, routes in routes_by_host.items():
            if url.startswith(base):
                path = url[len(base):]
                result = routes.get(path)
                if isinstance(result, Exception):
                    raise result
                if result is None:
                    return FakeResponse("<html>404</html>", status_code=404, content_type="text/html")
                return result
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(requests.Session, "get", fake_get)


def _target(url: str, node_id: str = "n", **extra) -> dict:
    return {"node_id": node_id, "name": node_id, "role": "test", "url": url, "enabled": True, **extra}


# --- parse_node_json ---------------------------------------------------------


def test_real_json_body_parses():
    data = parse_node_json(FakeResponse(REAL_HEALTH), "/health")
    assert data["ok"] is True and data["version"] == "2.2.1-rip200"


def test_html_spa_200_is_rejected_with_hijack_reason():
    with pytest.raises(NodeLivenessError) as excinfo:
        parse_node_json(FakeResponse(SPA_HTML, content_type="text/html; charset=utf-8"), "/health")
    assert NON_JSON_200_REASON in str(excinfo.value)
    assert "text/html" in str(excinfo.value)


def test_json_content_type_with_html_body_is_rejected():
    """A lying Content-Type header does not get past the parser."""
    with pytest.raises(NodeLivenessError) as excinfo:
        parse_node_json(FakeResponse(SPA_HTML, content_type="application/json"), "/epoch")
    assert NON_JSON_200_REASON in str(excinfo.value)


def test_json_array_is_not_a_node_payload():
    with pytest.raises(NodeLivenessError):
        parse_node_json(FakeResponse("[1, 2, 3]"), "/health")


def test_missing_content_type_is_rejected():
    with pytest.raises(NodeLivenessError) as excinfo:
        parse_node_json(FakeResponse(REAL_HEALTH, content_type=None), "/health")
    assert "missing" in str(excinfo.value)


def test_non_200_is_rejected_with_status():
    with pytest.raises(NodeLivenessError, match="HTTP 503"):
        parse_node_json(FakeResponse('{"ok":true}', status_code=503), "/health")


# --- payload key validation --------------------------------------------------


def test_health_without_ok_true_is_down(monkeypatch):
    _install_fake_session(monkeypatch, {"https://n1": _real_node_routes(health='{"ok": false, "version": "x"}')})
    with pytest.raises(NodeLivenessError, match="ok=False"):
        RustChainMonitor("https://n1").get_health()


def test_health_without_version_is_down(monkeypatch):
    _install_fake_session(monkeypatch, {"https://n1": _real_node_routes(health='{"ok": true}')})
    with pytest.raises(NodeLivenessError, match="version"):
        RustChainMonitor("https://n1").get_health()


def test_epoch_without_number_is_down(monkeypatch):
    _install_fake_session(monkeypatch, {"https://n1": _real_node_routes(epoch='{"status": "ok"}')})
    with pytest.raises(NodeLivenessError, match="epoch number"):
        RustChainMonitor("https://n1").get_epoch()


# --- collect_network_snapshot / collect_multi_node_snapshots -----------------


def test_real_node_is_online_and_miners_are_read_from_wrapped_list(monkeypatch):
    calls = []
    _install_fake_session(monkeypatch, {"https://n1": _real_node_routes()}, calls)

    [snapshot] = collect_multi_node_snapshots([_target("https://n1", "node1")])

    summary = snapshot["summary"]
    assert summary["liveness"] == "online"
    assert summary["node_ok"] is True and summary["scrape_ok"] is True
    assert summary["epoch_current"] == 292
    assert summary["active_miners"] == 3  # {"miners": [...]} shape, previously counted as 0
    assert snapshot["hardware_distribution"] == {"aarch64": 1, "modern": 1, "g4": 1}
    assert snapshot["error"] == ""
    assert all(kwargs.get("timeout") == rustchain_monitor.REQUEST_TIMEOUT_S for _, kwargs in calls)


def test_hijacked_host_is_down_not_online(monkeypatch):
    spa = FakeResponse(SPA_HTML, content_type="text/html; charset=utf-8")
    _install_fake_session(monkeypatch, {"https://retired": {"/health": spa, "/epoch": spa, "/api/miners": spa}})

    [snapshot] = collect_multi_node_snapshots([_target("https://retired", "node4")])

    assert snapshot["summary"]["liveness"] == "down"
    assert snapshot["summary"]["scrape_ok"] is False
    assert snapshot["summary"]["node_ok"] is False
    assert NON_JSON_200_REASON in snapshot["error"]


def test_timeout_is_down_with_timeout_reason(monkeypatch):
    routes = {"/health": requests.exceptions.ConnectTimeout("connect timed out")}
    _install_fake_session(monkeypatch, {"http://100.88.109.32:8099": routes})

    [snapshot] = collect_multi_node_snapshots([_target("http://100.88.109.32:8099", "node3")])

    assert snapshot["summary"]["liveness"] == "down"
    assert snapshot["summary"]["scrape_ok"] is False
    assert "timeout" in snapshot["error"]


def test_stale_tip_is_reported_stale_not_online(monkeypatch):
    stale_health = REAL_HEALTH.replace('"tip_age_slots":0', '"tip_age_slots":900')
    _install_fake_session(monkeypatch, {"https://n1": _real_node_routes(health=stale_health)})

    [snapshot] = collect_multi_node_snapshots([_target("https://n1", "node1")])

    assert snapshot["summary"]["liveness"] == "stale"
    assert snapshot["summary"]["node_ok"] is False
    assert snapshot["summary"]["scrape_ok"] is True  # data was collected; the node just is not keeping up
    assert "stale tip" in snapshot["error"]


def test_stale_epoch_relative_to_fleet_is_flagged(monkeypatch):
    behind = REAL_EPOCH.replace('"epoch":292', '"epoch":280')
    _install_fake_session(
        monkeypatch,
        {"https://n1": _real_node_routes(), "https://n2": _real_node_routes(epoch=behind)},
    )

    snapshots = collect_multi_node_snapshots([_target("https://n1", "node1"), _target("https://n2", "node2")])

    by_id = {snapshot["node_id"]: snapshot for snapshot in snapshots}
    assert by_id["node1"]["summary"]["liveness"] == "online"
    assert by_id["node2"]["summary"]["liveness"] == "stale"
    assert by_id["node2"]["summary"]["node_ok"] is False
    assert "stale epoch 280 (fleet max 292" in by_id["node2"]["error"]


def test_epoch_within_tolerance_is_still_online():
    def snap(epoch):
        return {"summary": {"liveness": "online", "node_ok": True, "epoch_current": epoch}, "error": ""}

    snapshots = assess_fleet_epoch_agreement([snap(292), snap(291)], tolerance=1)
    assert [s["summary"]["liveness"] for s in snapshots] == ["online", "online"]


def test_stale_node_does_not_drag_fleet_reference_down():
    """Only online nodes vote for the fleet epoch; a down node has no epoch and a stale one is ignored."""
    snapshots = [
        {"summary": {"liveness": "online", "node_ok": True, "epoch_current": 292}, "error": ""},
        {"summary": {"liveness": "down", "node_ok": False, "epoch_current": None}, "error": "timeout"},
    ]
    assess_fleet_epoch_agreement(snapshots)
    assert snapshots[0]["summary"]["liveness"] == "online"
    assert snapshots[1]["error"] == "timeout"


def test_disabled_target_is_not_probed(monkeypatch):
    calls = []
    _install_fake_session(monkeypatch, {}, calls)

    [snapshot] = collect_multi_node_snapshots(
        [_target("http://100.88.109.32:8099", "node3", enabled=False, note="expected down")]
    )

    assert calls == []
    assert snapshot["summary"]["liveness"] == "disabled"
    assert snapshot["summary"]["scrape_ok"] is False
    assert "expected down" in snapshot["error"]


# --- config hygiene ----------------------------------------------------------


def test_retired_host_in_config_warns(tmp_path, capsys):
    config = tmp_path / "nodes.json"
    config.write_text('{"nodes": [{"name": "Node 4", "url": "https://38.76.217.189"}]}')

    targets = rustchain_monitor.load_node_targets(config)

    assert targets[0]["enabled"] is True
    assert "retired host" in capsys.readouterr().err


def test_default_targets_do_not_include_retired_hosts():
    assert rustchain_monitor.retired_host_warnings(rustchain_monitor.default_multi_node_targets()) == []


def test_example_config_matches_default_fleet():
    example = rustchain_monitor.load_node_targets(ROOT / "nodes.example.json")
    defaults = rustchain_monitor.default_multi_node_targets()
    assert [(t["node_id"], t["url"], t["enabled"]) for t in example] == [
        (t["node_id"], t["url"], t["enabled"]) for t in defaults
    ]


def test_network_summary_reports_down_with_reason_instead_of_traceback(monkeypatch, capsys):
    spa = FakeResponse(SPA_HTML, content_type="text/html; charset=utf-8")
    _install_fake_session(monkeypatch, {"https://retired": {"/health": spa}})

    ok = RustChainMonitor("https://retired", use_color=False).network_summary()

    assert ok is False
    out = capsys.readouterr().out
    assert "DOWN" in out and NON_JSON_200_REASON in out
