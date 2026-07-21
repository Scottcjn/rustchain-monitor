import os
import sqlite3
import time

import verify_backup


def _create_required_schema(db_path, *, balances_amount=1, headers_rows=1):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE balances (amount REAL)")
    conn.execute("CREATE TABLE miner_attest_recent (id INTEGER)")
    conn.execute("CREATE TABLE headers (id INTEGER)")
    conn.execute("CREATE TABLE ledger (id INTEGER)")
    conn.execute("CREATE TABLE epoch_rewards (id INTEGER)")
    if balances_amount is not None:
        conn.execute("INSERT INTO balances (amount) VALUES (?)", (balances_amount,))
    for value in range(headers_rows):
        conn.execute("INSERT INTO headers (id) VALUES (?)", (value,))
    conn.commit()
    conn.close()


def test_find_latest_backup_prefers_newest_matching_pattern(tmp_path):
    ignored = tmp_path / "notes.txt"
    older = tmp_path / "rustchain_v2_old.db.bak"
    newer = tmp_path / "rustchain_v2_20260511.db"

    ignored.write_text("not a backup")
    older.write_text("old")
    newer.write_text("new")

    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(newer, (now, now))

    assert verify_backup.find_latest_backup(str(tmp_path)) == str(newer)


def test_find_latest_backup_returns_none_for_missing_or_empty_directory(tmp_path):
    assert verify_backup.find_latest_backup(str(tmp_path / "missing")) is None
    assert verify_backup.find_latest_backup(str(tmp_path)) is None


def test_check_integrity_reports_valid_and_invalid_sqlite_files(tmp_path):
    valid_db = tmp_path / "valid.db"
    invalid_db = tmp_path / "invalid.db"

    sqlite3.connect(valid_db).close()
    invalid_db.write_text("not sqlite")

    assert verify_backup.check_integrity(str(valid_db)) == (True, "ok")
    passed, error = verify_backup.check_integrity(str(invalid_db))

    assert passed is False
    assert error


def test_get_table_info_detects_positive_balances_with_amount_and_value_columns(tmp_path):
    amount_db = tmp_path / "amount.db"
    value_db = tmp_path / "value.db"

    conn = sqlite3.connect(amount_db)
    conn.execute("CREATE TABLE balances (amount REAL)")
    conn.execute("INSERT INTO balances (amount) VALUES (2.5)")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(value_db)
    conn.execute("CREATE TABLE balances (value REAL)")
    conn.execute("INSERT INTO balances (value) VALUES (3.0)")
    conn.commit()
    conn.close()

    amount_info = verify_backup.get_table_info(str(amount_db), "balances")
    value_info = verify_backup.get_table_info(str(value_db), "balances")

    assert amount_info == {"exists": True, "row_count": 1, "has_positive": True}
    assert value_info == {"exists": True, "row_count": 1, "has_positive": True}


def test_get_table_info_rejects_all_zero_balances(tmp_path):
    # Regression: canonical schema is balances(amount). A backup whose balances
    # are all zero (or negative) must report has_positive=False, otherwise
    # verify_tables' check_positive requirement is defeated and a wiped backup
    # passes verification.
    zero_db = tmp_path / "zero.db"
    conn = sqlite3.connect(zero_db)
    conn.execute("CREATE TABLE balances (amount REAL)")
    conn.execute("INSERT INTO balances (amount) VALUES (0)")
    conn.execute("INSERT INTO balances (amount) VALUES (0)")
    conn.commit()
    conn.close()

    info = verify_backup.get_table_info(str(zero_db), "balances")

    assert info == {"exists": True, "row_count": 2, "has_positive": False}


def test_verify_tables_passes_minimal_valid_backup_without_live_db(tmp_path):
    backup_db = tmp_path / "backup.db"
    _create_required_schema(backup_db)

    passed, results = verify_backup.verify_tables(str(backup_db), None)

    assert passed is True
    assert any("balances: 1 rows" in result for result in results)
    assert any("headers: 1 rows" in result for result in results)


def test_verify_tables_fails_missing_tables_and_empty_required_rows(tmp_path):
    backup_db = tmp_path / "backup.db"
    conn = sqlite3.connect(backup_db)
    conn.execute("CREATE TABLE balances (amount REAL)")
    conn.execute("INSERT INTO balances (amount) VALUES (0)")
    conn.commit()
    conn.close()

    passed, results = verify_backup.verify_tables(str(backup_db), None)

    assert passed is False
    assert any("headers: NOT FOUND" in result for result in results)
    assert any("balances: 1 rows" in result for result in results)


def test_verify_tables_flags_large_live_row_count_difference(tmp_path):
    backup_db = tmp_path / "backup.db"
    live_db = tmp_path / "live.db"
    _create_required_schema(backup_db, headers_rows=1)
    _create_required_schema(live_db, headers_rows=20)

    passed, results = verify_backup.verify_tables(str(backup_db), str(live_db))

    assert passed is True
    assert any("headers: 1 rows (live: 20" in result for result in results)
    assert any("95.0% diff" in result for result in results)
