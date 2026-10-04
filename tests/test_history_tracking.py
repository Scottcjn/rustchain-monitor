import csv
import json
import sys
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rustchain_monitor


@pytest.mark.parametrize(
    "status_code,balance_payload,error_match",
    [
        (404, {"error": "balance unavailable"}, "HTTP 404"),
        (500, {"error": "balance unavailable"}, "HTTP 500"),
        (200, {}, "balance_rtc"),
        (200, {"error": "balance unavailable"}, "balance_rtc"),
        (200, {"balance_rtc": None}, "balance_rtc"),
        (200, {"balance_rtc": ""}, "balance_rtc"),
        (200, {"balance_rtc": "unavailable"}, "balance_rtc"),
        (200, {"balance_rtc": False}, "balance_rtc"),
        (200, {"balance_rtc": True}, "balance_rtc"),
        (200, {"balance_rtc": []}, "balance_rtc"),
        (200, {"balance_rtc": {}}, "balance_rtc"),
        (200, {"balance_rtc": float("nan")}, "balance_rtc"),
        (200, {"balance_rtc": float("inf")}, "balance_rtc"),
        (200, {"balance_rtc": float("-inf")}, "balance_rtc"),
        (200, {"balance_rtc": "NaN"}, "balance_rtc"),
        (200, {"balance_rtc": "1e309"}, "balance_rtc"),
        (200, {"balance_rtc": 10 ** 400}, "balance_rtc"),
    ],
)
def test_invalid_balance_does_not_record_false_history(
    tmp_path, monkeypatch, status_code, balance_payload, error_match
):
    db_path = tmp_path / "history.db"
    monitor = rustchain_monitor.RustChainMonitor(history_db_path=db_path)
    balances = iter([
        (200, {"balance_rtc": 12.5}),
        (status_code, balance_payload),
        (200, {"balance_rtc": 14.5}),
        (200, {"balance_rtc": 0.0}),
    ])

    def get_response(url, **kwargs):
        response = requests.Response()
        response.url = url
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        if "/wallet/balance?" in url:
            response.status_code, payload = next(balances)
        elif url.endswith("/epoch"):
            payload = {"epoch": 100}
        else:
            payload = {"miners": []}
        response._content = json.dumps(payload).encode("utf-8")
        return response

    monkeypatch.setattr(monitor.session, "get", get_response)

    def record_current_balance():
        snapshot = monitor.get_miner_snapshot("miner-a")
        monitor.record_history("miner-a", snapshot)

    record_current_balance()
    with pytest.raises(rustchain_monitor.NodeLivenessError, match=error_match):
        record_current_balance()
    record_current_balance()
    record_current_balance()

    with rustchain_monitor._history_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT balance_rtc, delta_rtc FROM miner_history ORDER BY id"
        ).fetchall()

    assert [tuple(row) for row in rows] == [(12.5, 0.0), (14.5, 2.0), (0.0, -14.5)]


@pytest.mark.parametrize(
    "raw_balance,expected",
    [(0, 0.0), (0.0, 0.0), (12.5, 12.5), (-1.5, -1.5),
     ("0", 0.0), ("12.5", 12.5), (" -1.5 ", -1.5), ("1e2", 100.0)],
)
def test_balance_preserves_finite_numeric_values(monkeypatch, raw_balance, expected):
    monitor = rustchain_monitor.RustChainMonitor()
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps({"balance_rtc": raw_balance}).encode("utf-8")
    monkeypatch.setattr(monitor.session, "get", lambda *args, **kwargs: response)

    assert monitor.get_miner_balance("miner-a") == expected


def test_record_history_snapshot_skips_duplicate_latest_point(tmp_path):
    db_path = tmp_path / "history.db"

    first = rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-a",
        epoch=10,
        balance_rtc=1.25,
        device_arch="g4",
        is_active=True,
        observed_at=1000.0,
    )
    duplicate = rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-a",
        epoch=10,
        balance_rtc=1.25,
        device_arch="g4",
        is_active=True,
        observed_at=1060.0,
    )
    changed = rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-a",
        epoch=11,
        balance_rtc=1.75,
        device_arch="g4",
        is_active=True,
        observed_at=1120.0,
    )

    assert first is True
    assert duplicate is False
    assert changed is True

    with rustchain_monitor._history_connection(db_path) as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM miner_history WHERE miner_id = ?", ("miner-a",)).fetchone()[0]

    assert row_count == 2


def test_history_summary_and_chart_show_recent_gains(tmp_path):
    db_path = tmp_path / "history.db"
    now_ts = 2_000_000_000.0

    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-b",
        epoch=100,
        balance_rtc=10.0,
        device_arch="power8",
        is_active=True,
        observed_at=now_ts - (10 * 86400),
    )
    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-b",
        epoch=104,
        balance_rtc=13.0,
        device_arch="power8",
        is_active=True,
        observed_at=now_ts - (6 * 86400),
    )
    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-b",
        epoch=109,
        balance_rtc=15.5,
        device_arch="power8",
        is_active=False,
        observed_at=now_ts - 3600,
    )

    summary = rustchain_monitor.get_history_summary(
        db_path,
        miner_id="miner-b",
        now_ts=now_ts,
        days=30,
    )
    chart = rustchain_monitor.render_daily_gain_chart(summary["daily_rows"])

    assert summary["snapshots"] == 3
    assert summary["latest_balance"] == 15.5
    assert summary["total_gain"] == 5.5
    assert summary["daily_gain_7d"] == 5.5
    assert summary["latest_active"] is False
    assert "RTC" in chart
    assert "#" in chart


def test_compare_miner_history_sorts_by_recent_gain(tmp_path):
    db_path = tmp_path / "history.db"
    now_ts = 2_100_000_000.0

    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-fast",
        epoch=200,
        balance_rtc=5.0,
        observed_at=now_ts - (7 * 86400),
    )
    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-fast",
        epoch=207,
        balance_rtc=9.5,
        observed_at=now_ts - 10,
    )
    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-slow",
        epoch=200,
        balance_rtc=7.0,
        observed_at=now_ts - (7 * 86400),
    )
    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-slow",
        epoch=207,
        balance_rtc=8.0,
        observed_at=now_ts - 10,
    )

    rows = rustchain_monitor.compare_miner_history(
        db_path,
        miner_ids=["miner-slow", "miner-fast"],
        now_ts=now_ts,
        days=7,
    )

    assert [row["miner_id"] for row in rows] == ["miner-fast", "miner-slow"]
    assert rows[0]["recent_gain"] == 4.5
    assert rows[1]["recent_gain"] == 1.0


def test_export_history_csv_writes_snapshot_rows(tmp_path):
    db_path = tmp_path / "history.db"
    csv_path = tmp_path / "export.csv"

    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-c",
        epoch=300,
        balance_rtc=2.0,
        observed_at=1234.0,
    )
    rustchain_monitor.record_history_snapshot(
        db_path,
        miner_id="miner-c",
        epoch=301,
        balance_rtc=2.5,
        observed_at=1334.0,
    )

    row_count = rustchain_monitor.export_history_csv(
        db_path,
        miner_id="miner-c",
        csv_path=csv_path,
    )

    assert row_count == 2
    with open(csv_path, newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0][0] == "observed_at_iso"
    assert rows[1][2] == "miner-c"
    assert rows[2][4] == "2.5"
