#!/usr/bin/env python3
"""
RustChain Backup Verification Script
=====================================
Validates SQLite database backups for integrity and data consistency.

Bounty: #755 - 10 RTC
https://github.com/Scottcjn/rustchain-bounties/issues/755

Usage:
    python3 verify_backup.py [--backup PATH] [--live PATH] [--webhook URL]
    
    # Run as cron job daily
    0 6 * * * /usr/bin/python3 /root/rustchain/verify_backup.py >> /var/log/backup_verify.log 2>&1
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, List

# Configuration defaults
DEFAULT_BACKUP_DIR = "/root/rustchain/backups"
DEFAULT_LIVE_DB = "/root/rustchain/rustchain_v2.db"
BACKUP_PATTERNS = [
    "rustchain_v2*.db.bak",
    "rustchain_v2_*.db",
    "*.db.bak",
]

# Key tables to verify
REQUIRED_TABLES = {
    "balances": {"min_rows": 1, "check_positive": True},
    "miner_attest_recent": {"min_rows": 0, "check_positive": False},
    "headers": {"min_rows": 1, "check_positive": False},
    "ledger": {"min_rows": 0, "check_positive": False},
    "epoch_rewards": {"min_rows": 0, "check_positive": False},
}

# Max allowed row count difference (backup vs live)
MAX_ROW_DIFF_PERCENT = 10  # 10% tolerance


def log(message: str, level: str = "INFO") -> None:
    """Print timestamped log message."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def find_latest_backup(backup_dir: str) -> Optional[str]:
    """Find the most recent backup file in the backup directory."""
    backup_path = Path(backup_dir)
    
    if not backup_path.exists():
        log(f"Backup directory not found: {backup_dir}", "ERROR")
        return None
    
    # Try each pattern
    all_backups: List[Path] = []
    for pattern in BACKUP_PATTERNS:
        matches = list(backup_path.glob(pattern))
        all_backups.extend(matches)
    
    if not all_backups:
        log(f"No backup files found in {backup_dir}", "ERROR")
        return None
    
    # Sort by modification time, newest first
    all_backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest = all_backups[0]
    
    log(f"Found {len(all_backups)} backup(s), latest: {latest.name}")
    return str(latest)


def copy_to_temp(backup_path: str) -> Tuple[str, tempfile.TemporaryDirectory]:
    """Copy backup to temp location for safe testing."""
    temp_dir = tempfile.TemporaryDirectory(prefix="rustchain_verify_")
    temp_db = os.path.join(temp_dir.name, "backup_test.db")
    
    shutil.copy2(backup_path, temp_db)
    log(f"Copied backup to temp: {temp_db}")
    
    return temp_db, temp_dir


def check_integrity(db_path: str) -> Tuple[bool, str]:
    """Run PRAGMA integrity_check on the database."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()[0]
        conn.close()
        
        passed = result == "ok"
        return passed, result
    except sqlite3.Error as e:
        return False, str(e)


def get_table_info(db_path: str, table: str) -> Dict:
    """Get row count and basic stats for a table."""
    info = {"exists": False, "row_count": 0, "has_positive": False}
    
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        if not cursor.fetchone():
            conn.close()
            return info
        
        info["exists"] = True
        
        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        info["row_count"] = cursor.fetchone()[0]
        
        # For balances, check for positive amounts
        if table == "balances":
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM balances WHERE amount > 0 OR balance > 0"
                )
                info["has_positive"] = cursor.fetchone()[0] > 0
            except sqlite3.Error:
                # Column name might differ, try alternatives
                try:
                    cursor.execute("SELECT COUNT(*) FROM balances WHERE value > 0")
                    info["has_positive"] = cursor.fetchone()[0] > 0
                except sqlite3.Error:
                    info["has_positive"] = info["row_count"] > 0
        
        conn.close()
    except sqlite3.Error as e:
        log(f"Error checking table {table}: {e}", "WARN")
    
    return info


def verify_tables(backup_db: str, live_db: Optional[str]) -> Tuple[bool, List[str]]:
    """Verify required tables exist and have expected data."""
    results = []
    all_passed = True
    
    live_counts = {}
    if live_db and os.path.exists(live_db):
        for table in REQUIRED_TABLES:
            info = get_table_info(live_db, table)
            live_counts[table] = info.get("row_count", 0)
    
    for table, requirements in REQUIRED_TABLES.items():
        info = get_table_info(backup_db, table)
        
        if not info["exists"]:
            results.append(f"  {table}: NOT FOUND ❌")
            all_passed = False
            continue
        
        row_count = info["row_count"]
        live_count = live_counts.get(table, 0)
        
        # Build status line
        status_parts = [f"{row_count} rows"]
        if live_count > 0:
            status_parts.append(f"live: {live_count}")
            
            # Check if backup is too far behind
            if live_count > 0:
                diff_percent = abs(live_count - row_count) / live_count * 100
                if diff_percent > MAX_ROW_DIFF_PERCENT:
                    status_parts.append(f"⚠️ {diff_percent:.1f}% diff")
        
        # Check requirements
        passed = True
        if requirements["min_rows"] > 0 and row_count < requirements["min_rows"]:
            passed = False
        if requirements["check_positive"] and not info.get("has_positive", False):
            passed = False
        
        icon = "✅" if passed else "❌"
        if not passed:
            all_passed = False
        
        results.append(f"  {table}: {' ('.join(status_parts)}) {icon}")
    
    return all_passed, results


def send_webhook(webhook_url: str, success: bool, message: str) -> None:
    """Send alert to webhook on failure."""
    if not webhook_url:
        return
    
    try:
        import urllib.request
        
        payload = json.dumps({
            "text": f"🗄️ RustChain Backup Verification: {'✅ PASS' if success else '❌ FAIL'}\n{message}",
            "success": success,
        }).encode("utf-8")
        
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        log("Webhook notification sent")
    except Exception as e:
        log(f"Webhook failed: {e}", "WARN")


def main():
    parser = argparse.ArgumentParser(
        description="Verify RustChain SQLite backup integrity"
    )
    parser.add_argument(
        "--backup", "-b",
        help="Path to specific backup file (auto-detects if not provided)"
    )
    parser.add_argument(
        "--backup-dir", "-d",
        default=DEFAULT_BACKUP_DIR,
        help=f"Backup directory to search (default: {DEFAULT_BACKUP_DIR})"
    )
    parser.add_argument(
        "--live", "-l",
        default=DEFAULT_LIVE_DB,
        help=f"Path to live database for comparison (default: {DEFAULT_LIVE_DB})"
    )
    parser.add_argument(
        "--webhook", "-w",
        help="Webhook URL for failure alerts"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only output final result"
    )
    
    args = parser.parse_args()
    
    # Track overall result
    all_passed = True
    messages = []
    
    # Step 1: Find backup
    if args.backup:
        backup_path = args.backup
        if not os.path.exists(backup_path):
            log(f"Backup not found: {backup_path}", "ERROR")
            sys.exit(1)
    else:
        backup_path = find_latest_backup(args.backup_dir)
        if not backup_path:
            log("RESULT: FAIL (no backup found)", "ERROR")
            send_webhook(args.webhook, False, "No backup file found")
            sys.exit(1)
    
    log(f"Backup: {backup_path}")
    messages.append(f"Backup: {os.path.basename(backup_path)}")
    
    # Step 2: Copy to temp location
    try:
        temp_db, temp_dir = copy_to_temp(backup_path)
    except Exception as e:
        log(f"Failed to copy backup: {e}", "ERROR")
        send_webhook(args.webhook, False, f"Copy failed: {e}")
        sys.exit(1)
    
    try:
        # Step 3: Integrity check
        integrity_passed, integrity_result = check_integrity(temp_db)
        if integrity_passed:
            log("Integrity: PASS")
            messages.append("Integrity: PASS")
        else:
            log(f"Integrity: FAIL ({integrity_result})", "ERROR")
            messages.append(f"Integrity: FAIL ({integrity_result})")
            all_passed = False
        
        # Step 4: Table verification
        live_db = args.live if os.path.exists(args.live) else None
        if not live_db:
            log(f"Live DB not found at {args.live}, skipping comparison", "WARN")
        
        tables_passed, table_results = verify_tables(temp_db, live_db)
        if not tables_passed:
            all_passed = False
        
        log("Tables:")
        for result in table_results:
            log(result)
            messages.append(result)
        
    finally:
        # Cleanup temp directory
        temp_dir.cleanup()
    
    # Final result
    if all_passed:
        log("RESULT: PASS ✅")
        send_webhook(args.webhook, True, "\n".join(messages))
        sys.exit(0)
    else:
        log("RESULT: FAIL ❌")
        send_webhook(args.webhook, False, "\n".join(messages))
        sys.exit(1)


if __name__ == "__main__":
    main()
