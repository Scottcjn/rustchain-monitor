import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rustchain_monitor import NodeLivenessError, RustChainMonitor, _history_connection


def response(status, body):
    result = requests.Response()
    result.status_code = status
    result.url = "https://node.example.test/endpoint"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode("utf-8")
    return result


CALLS = [
    ("get_health", (), {"ok": True, "version": "1.0.0"}),
    ("get_epoch", (), {"epoch": 8}),
    ("get_miners", (), {"miners": [{"miner_id": "miner-a"}]}),
    ("get_miner_balance", ("miner-a",), {"balance_rtc": 0.0}),
]


@pytest.mark.parametrize("method,args,body", CALLS)
@pytest.mark.parametrize("status", [404, 503])
def test_failed_http_responses_do_not_become_monitor_data(method, args, body, status):
    monitor = RustChainMonitor(node_url="https://node.example.test")
    monitor.session.get = Mock(return_value=response(status, {"error": "unavailable"}))
    with pytest.raises(NodeLivenessError, match=f"HTTP {status}"):
        getattr(monitor, method)(*args)


@pytest.mark.parametrize("method,args,body", CALLS)
def test_successful_responses_keep_existing_return_values(method, args, body):
    monitor = RustChainMonitor(node_url="https://node.example.test")
    monitor.session.get = Mock(return_value=response(200, body))
    if method == "get_miner_balance":
        expected = body["balance_rtc"]
    elif method == "get_miners":
        expected = body["miners"]
    else:
        expected = body
    assert getattr(monitor, method)(*args) == expected


def test_failed_balance_poll_preserves_history_and_next_delta(tmp_path):
    database = tmp_path / "history.db"
    monitor = RustChainMonitor(node_url="https://node.example.test", history_db_path=database)
    monitor.get_epoch = Mock(return_value={"epoch": 7})
    monitor.get_miners = Mock(return_value=[])
    monitor.session.get = Mock(return_value=response(200, {"balance_rtc": 5.0}))
    monitor.record_history("miner-a", monitor.get_miner_snapshot("miner-a"))

    monitor.session.get.return_value = response(503, {"error": "maintenance"})
    with pytest.raises(NodeLivenessError, match="HTTP 503"):
        monitor.record_history("miner-a", monitor.get_miner_snapshot("miner-a"))

    monitor.get_epoch.return_value = {"epoch": 8}
    monitor.session.get.return_value = response(200, {"balance_rtc": 5.25})
    monitor.record_history("miner-a", monitor.get_miner_snapshot("miner-a"))
    with _history_connection(database) as connection:
        rows = connection.execute(
            "SELECT balance_rtc, delta_rtc FROM miner_history ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in rows] == [(5.0, 0.0), (5.25, 0.25)]
