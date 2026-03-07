# RustChain Backup Verification Script

Automated script to verify SQLite backup integrity and prevent silent data loss.

## Features

- ✅ SQLite integrity check (`PRAGMA integrity_check`)
- ✅ Verifies key tables exist and have data
- ✅ Compares row counts with live DB
- ✅ Checks for recent attestations
- ✅ Handles missing backups gracefully
- ✅ Colored output for easy reading
- ✅ Exit codes for cron alerting (0=PASS, 1=FAIL)
- ✅ Non-destructive (never modifies backups or live DB)

## Installation

```bash
# Copy script to RustChain directory
cp verify_backup.sh /root/rustchain/
chmod +x /root/rustchain/verify_backup.sh

# Test run
/root/rustchain/verify_backup.sh
```

## Usage

### Manual Run

```bash
# Verify latest backup
./verify_backup.sh

# Verify specific backup
./verify_backup.sh /path/to/backup.db
```

### Automated (Cron)

Add to crontab for daily verification:

```bash
# Run daily at 6 AM
0 6 * * * /root/rustchain/verify_backup.sh >> /var/log/backup_verify.log 2>&1

# Run every 6 hours
0 */6 * * * /root/rustchain/verify_backup.sh >> /var/log/backup_verify.log 2>&1
```

### With Email Alerts

```bash
# Install mailutils if not already installed
apt-get install mailutils

# Add to crontab with email on failure
0 6 * * * /root/rustchain/verify_backup.sh || echo "Backup verification failed!" | mail -s "RustChain Backup Alert" admin@example.com
```

## Configuration

Environment variables (optional):

```bash
# Backup directory (default: /root/rustchain/backups)
export BACKUP_DIR="/custom/backup/path"

# Live DB path (default: /root/rustchain/rustchain_v2.db)
export LIVE_DB="/custom/db/path/rustchain_v2.db"

# Run verification
./verify_backup.sh
```

## Output Example

```
=========================================
RustChain Backup Verification
=========================================

[2026-03-08 01:30:01] Backup: /root/rustchain/backups/rustchain_v2_20260308.db
[2026-03-08 01:30:01] Size: 45M
[2026-03-08 01:30:01] Copying backup to temp location...
[2026-03-08 01:30:02] Running integrity check...
[2026-03-08 01:30:03] ✅ Integrity check: PASS
[2026-03-08 01:30:03] Checking key tables...
[2026-03-08 01:30:03] ✅ Table 'balances': 282 rows
[2026-03-08 01:30:03] ✅ Table 'headers': 13680 rows
[2026-03-08 01:30:03] ✅ Table 'ledger': 5420 rows
[2026-03-08 01:30:03] ✅ Recent attestations: 18
[2026-03-08 01:30:03] Comparing with live DB...
[2026-03-08 01:30:04] ✅ Table 'balances': backup=282, live=282 (diff: 0) ✅
[2026-03-08 01:30:04] ✅ Table 'headers': backup=13680, live=13685 (diff: 5) ✅

[2026-03-08 01:30:04] ✅ RESULT: PASS - Backup is valid ✅
```

## Checks Performed

### 1. Integrity Check
- Runs `PRAGMA integrity_check` on backup
- Ensures no corruption

### 2. Table Verification
- `balances` - Must have rows with positive amounts
- `headers` - Must have block headers
- `ledger` - Must have transactions
- `miner_attest_recent` or `attestations` - Must have recent data

### 3. Row Count Comparison
- Compares backup vs live DB
- Allows up to 1000 rows difference (≈1 epoch)
- Alerts if backup is too far behind

### 4. Recent Data Check
- Verifies attestations within last 24 hours
- Ensures backup is not too old

## Exit Codes

- `0` - PASS: Backup is valid
- `1` - FAIL: One or more checks failed

## Error Handling

- Gracefully handles missing backup files
- Handles missing live DB (skips comparison)
- Handles missing tables (tries alternatives)
- Never modifies original files
- Cleans up temp files on exit

## Requirements

- Bash 4.0+
- SQLite3
- Ubuntu/Debian Linux
- Read access to backup directory
- Read access to live DB (optional, for comparison)

## Security

- Non-destructive: Never writes to backup or live DB
- Uses temporary directory for all operations
- Cleans up temp files automatically
- No network access required

## Troubleshooting

### "No backup files found"
- Check `BACKUP_DIR` path
- Ensure backups exist and are readable

### "Live DB not found"
- Set `LIVE_DB` environment variable
- Or run without comparison (still validates backup)

### "Table not found"
- Database schema may differ
- Script tries alternative table names
- Check SQLite schema: `sqlite3 backup.db ".schema"`

## License

MIT

## Author

Created for RustChain Bounty #755 (10 RTC)

**RTC Wallet**: RTCf4c3ff0e8443fb3c420fa7c23e7fef36cde61cab
