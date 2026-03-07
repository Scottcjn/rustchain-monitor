#!/usr/bin/env python3
"""
Automated Backup Verification Script for RustChain
Validates SQLite database backups
Bounty: 10 RTC
"""

import os
import sys
import sqlite3
import glob
import argparse
from datetime import datetime

BACKUP_DIR = "/root/rustchain/backups"
LIVE_DB = "/root/rustchain/rustchain_v2.db"
LOG_FILE = "/var/log/backup_verify.log"

KEY_TABLES = [
    "balances",
    "miner_attest_recent", 
    "headers",
    "ledger",
    "epoch_rewards"
]

def log(msg):
    """Log to file and stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except:
            pass

def find_latest_backup():
    """Find the most recent backup file."""
    patterns = [
        os.path.join(BACKUP_DIR, "rustchain_v2.db.bak"),
        os.path.join(BACKUP_DIR, "rustchain_v2_*.db"),
        os.path.join(BACKUP_DIR, "*.bak"),
    ]
    
    for pattern in patterns:
        files = glob.glob(pattern)
        if files:
            return max(files, key=os.path.getmtime)
    
    return None

def check_integrity(db_path):
    """Run SQLite integrity check."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        conn.close()
        return result[0] == "ok", result[0]
    except Exception as e:
        return False, str(e)

def check_tables(db_path):
    """Verify key tables exist and have data."""
    results = {}
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        for table in KEY_TABLES:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                results[table] = count
            except:
                results[table] = -1  # Table doesn't exist
        
        conn.close()
    except Exception as e:
        log(f"Error checking tables: {e}")
        return None
    
    return results

def compare_row_counts(backup_counts, live_counts):
    """Compare row counts between backup and live DB."""
    comparison = {}
    for table in KEY_TABLES:
        backup_count = backup_counts.get(table, 0)
        live_count = live_counts.get(table, 0)
        
        if backup_count < 0 or live_count < 0:
            comparison[table] = "N/A"
        elif backup_count >= live_count:
            comparison[table] = f"{backup_count} rows (live: {live_count}) ✅"
        else:
            diff = live_count - backup_count
            comparison[table] = f"{backup_count} rows (live: {live_count}, diff: {diff}) ⚠️"
    
    return comparison

def verify_backup(backup_path):
    """Verify a single backup file."""
    log(f"Backup: {backup_path}")
    
    # Check integrity
    ok, result = check_integrity(backup_path)
    log(f"Integrity: {'PASS' if ok else 'FAIL'} - {result}")
    
    if not ok:
        log("RESULT: FAIL - Integrity check failed")
        return False
    
    # Check tables in backup
    backup_counts = check_tables(backup_path)
    
    # Check tables in live DB
    if os.path.exists(LIVE_DB):
        live_counts = check_tables(LIVE_DB)
    else:
        log("Warning: Live DB not found, skipping comparison")
        live_counts = None
    
    # Compare
    if live_counts:
        comparison = compare_row_counts(backup_counts, live_counts)
        for table, status in comparison.items():
            log(f"{table}: {status}")
    
    log("RESULT: PASS")
    return True

def main():
    parser = argparse.ArgumentParser(description="Verify RustChain database backups")
    parser.add_argument("--backup", help="Specific backup file to verify")
    parser.add_argument("--backup-dir", default=BACKUP_DIR, help="Backup directory")
    args = parser.parse_args()
    
    global BACKUP_DIR
    BACKUP_DIR = args.backup_dir
    
    # Find backup
    if args.backup:
        backup_path = args.backup
    else:
        backup_path = find_latest_backup()
    
    if not backup_path:
        log("ERROR: No backup file found")
        sys.exit(1)
    
    # Verify
    success = verify_backup(backup_path)
    
    if success:
        log("Verification PASSED")
        sys.exit(0)
    else:
        log("Verification FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
