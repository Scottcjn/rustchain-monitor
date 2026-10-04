"""Comparison windows must match the number of days requested by the caller."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rustchain_monitor import compare_miner_history, record_history_snapshot
import rustchain_monitor


NOW = 2_100_000_000.0
DAY = 86400


def record(db_path, miner, age, balance, epoch):
    record_history_snapshot(
        db_path,
        miner_id=miner,
        epoch=epoch,
        balance_rtc=balance,
        observed_at=NOW - age * DAY,
    )


@pytest.mark.parametrize(
    "days,old_gain_age,expected_old_gain,first_miner",
    [
        (2, 4, 0.0, "recent"),
        (14, 20, 0.0, "recent"),
        (60, 50, 100.0, "old"),
        (1, 4, 0.0, "recent"),
        (7, 4, 100.0, "old"),
        (30, 20, 100.0, "old"),
    ],
)
def test_comparison_uses_exact_requested_window(
    tmp_path, days, old_gain_age, expected_old_gain, first_miner
):
    db_path = tmp_path / "history.db"
    for miner in ("old", "recent"):
        record(db_path, miner, 100, 0.0, 1)
    record(db_path, "old", old_gain_age, 100.0, 2)
    record(db_path, "old", 0, 100.0, 3)
    record(db_path, "recent", 0.5, 10.0, 2)

    rows = compare_miner_history(
        db_path, miner_ids=["old", "recent"], now_ts=NOW, days=days
    )

    assert rows[0]["miner_id"] == first_miner
    by_miner = {row["miner_id"]: row for row in rows}
    assert by_miner["old"]["recent_gain"] == expected_old_gain
    assert by_miner["recent"]["recent_gain"] == 10.0
    assert by_miner["old"]["daily_average"] == pytest.approx(expected_old_gain / days)
    assert by_miner["recent"]["daily_average"] == pytest.approx(10.0 / days)


def test_custom_window_preserves_empty_history(tmp_path):
    rows = compare_miner_history(
        tmp_path / "history.db", miner_ids=["missing"], now_ts=NOW, days=14
    )
    assert rows[0]["recent_gain"] == 0.0
    assert rows[0]["daily_average"] == 0.0
    assert rows[0]["snapshots"] == 0


def test_comparison_preserves_latest_tie_metadata_and_negative_gain(tmp_path):
    db_path = tmp_path / "history.db"
    record(db_path, "withdrawn", 30, 20.0, 1)
    record(db_path, "withdrawn", 0, 18.0, 2)
    record(db_path, "withdrawn", 0, 12.0, 3)
    record(db_path, "stale", 50, 4.0, 1)
    record(db_path, "stale", 40, 9.0, 2)

    rows = compare_miner_history(
        db_path,
        miner_ids=["withdrawn", "missing", "stale", "withdrawn"],
        now_ts=NOW,
        days=14,
    )

    assert [row["miner_id"] for row in rows] == [
        "stale", "missing", "withdrawn", "withdrawn"
    ]
    assert rows[0]["recent_gain"] == 0.0
    assert rows[0]["snapshots"] == 2
    assert rows[1] == {
        "miner_id": "missing", "snapshots": 0, "latest_balance": 0.0,
        "recent_gain": 0.0, "daily_average": 0.0,
        "latest_epoch": None, "last_seen": None,
    }
    assert rows[2] == rows[3] == {
        "miner_id": "withdrawn", "snapshots": 3, "latest_balance": 12.0,
        "recent_gain": -8.0, "daily_average": -8.0 / 14,
        "latest_epoch": 3, "last_seen": NOW,
    }


def test_empty_comparison_does_not_create_history_database(tmp_path):
    db_path = tmp_path / "absent" / "history.db"
    assert compare_miner_history(db_path, miner_ids=[], now_ts=NOW, days=14) == []
    assert not db_path.exists()


def test_comparison_keeps_one_snapshot_during_history_write(tmp_path, monkeypatch):
    db_path = tmp_path / "history.db"
    record(db_path, "miner", 2, 10.0, 1)
    record(db_path, "miner", 1, 12.0, 2)
    with sqlite3.connect(db_path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")

    original_connection = rustchain_monitor._history_connection
    published = False

    def connection_with_writer(path):
        conn = original_connection(path)
        reads = 0

        def write_between_reads(statement):
            nonlocal reads, published
            if statement.lstrip().upper().startswith("SELECT"):
                reads += 1
                if reads == 2 and not published:
                    with sqlite3.connect(path) as writer:
                        writer.execute(
                            "INSERT INTO miner_history "
                            "(miner_id, observed_at, epoch, balance_rtc) VALUES (?, ?, ?, ?)",
                            ("miner", NOW, 3, 100.0),
                        )
                    published = True

        conn.set_trace_callback(write_between_reads)
        return conn

    monkeypatch.setattr(rustchain_monitor, "_history_connection", connection_with_writer)
    current = compare_miner_history(db_path, miner_ids=["miner"], now_ts=NOW, days=7)[0]
    assert published
    assert (current["latest_balance"], current["snapshots"], current["recent_gain"]) == (12.0, 2, 2.0)

    refreshed = compare_miner_history(db_path, miner_ids=["miner"], now_ts=NOW, days=7)[0]
    assert (refreshed["latest_balance"], refreshed["snapshots"], refreshed["recent_gain"]) == (100.0, 3, 90.0)
