import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rustchain_monitor


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
