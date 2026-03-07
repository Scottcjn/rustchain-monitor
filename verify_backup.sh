#!/usr/bin/env bash
# verify_backup.sh — RustChain SQLite Backup Integrity Verifier
# Bounty #755 — 10 RTC
#
# Usage:
#   ./verify_backup.sh [backup_path] [live_db_path]
#
# Defaults:
#   backup: /root/rustchain/rustchain_v2.db.bak  (or latest .db in /root/rustchain/backups/)
#   live:   /root/rustchain/rustchain_v2.db
#
# Exit code: 0 = PASS, 1 = FAIL
#
# Cron example:
#   0 6 * * * /root/rustchain/verify_backup.sh >> /var/log/backup_verify.log 2>&1

set -euo pipefail

# ─── Configuration ─────────────────────────────────────────────────────────────
LIVE_DB="${2:-/root/rustchain/rustchain_v2.db}"
BACKUP_DB="${1:-}"
BACKUP_DIR="/root/rustchain/backups"
TEMP_DIR=$(mktemp -d)
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Minimum row counts to be considered valid
MIN_BALANCES=1
MIN_HEADERS=100
MIN_LEDGER=0          # may be empty early in chain life
MIN_EPOCH_REWARDS=1

# ─── Color output ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'; BOLD='\033[1m'
log()  { echo "[$TIMESTAMP] $*"; }
ok()   { echo -e "[$TIMESTAMP] ${GREEN}✅ $*${NC}"; }
fail() { echo -e "[$TIMESTAMP] ${RED}✗  $*${NC}"; echo "FAIL" >> "$FAIL_FILE"; }
warn() { echo -e "[$TIMESTAMP] ${YELLOW}⚠  $*${NC}"; }

FAIL_FILE="$TEMP_DIR/failures"
touch "$FAIL_FILE" 2>/dev/null || true
CLEANUP() { rm -rf "$TEMP_DIR"; }
trap CLEANUP EXIT

# ─── Find backup file ──────────────────────────────────────────────────────────
if [ -z "$BACKUP_DB" ]; then
  if [ -f "/root/rustchain/rustchain_v2.db.bak" ]; then
    BACKUP_DB="/root/rustchain/rustchain_v2.db.bak"
  elif [ -d "$BACKUP_DIR" ]; then
    BACKUP_DB=$(find "$BACKUP_DIR" -name "*.db" -o -name "*.db.bak" 2>/dev/null | sort | tail -1)
  fi
fi

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  RustChain Backup Verification Report${NC}"
echo -e "${BOLD}  $TIMESTAMP${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ─── Check backup exists ──────────────────────────────────────────────────────
if [ -z "$BACKUP_DB" ] || [ ! -f "$BACKUP_DB" ]; then
  fail "Backup file not found: ${BACKUP_DB:-no path resolved}"
  echo ""
  echo -e "[${TIMESTAMP}] ${RED}RESULT: FAIL — No backup file found${NC}"
  echo ""
  exit 1
fi

log "Backup:  $BACKUP_DB ($(du -sh "$BACKUP_DB" 2>/dev/null | cut -f1))"
log "Live DB: $LIVE_DB"
echo ""

# ─── Check sqlite3 available ─────────────────────────────────────────────────
if ! command -v sqlite3 &>/dev/null; then
  fail "sqlite3 not installed — please install: apt-get install sqlite3"
  exit 1
fi

# ─── Copy backup to temp location (non-destructive) ──────────────────────────
TEMP_BACKUP="$TEMP_DIR/backup_check.db"
cp "$BACKUP_DB" "$TEMP_BACKUP"
log "Copied backup to temp location for safe analysis"
echo ""

# ─── SQLite integrity check ───────────────────────────────────────────────────
log "Running SQLite integrity check..."
INTEGRITY=$(sqlite3 "$TEMP_BACKUP" "PRAGMA integrity_check;" 2>&1 || echo "ERROR")
if [ "$INTEGRITY" = "ok" ]; then
  ok "SQLite integrity: PASS"
else
  fail "SQLite integrity: FAIL — $INTEGRITY"
fi

# ─── Check required tables exist ─────────────────────────────────────────────
echo ""
log "Checking required tables..."
TABLES=$(sqlite3 "$TEMP_BACKUP" ".tables" 2>/dev/null || echo "")

check_table() {
  local tbl="$1"
  local min="$2"
  local desc="$3"
  local count=0
  if echo "$TABLES" | grep -qw "$tbl"; then
    count=$(sqlite3 "$TEMP_BACKUP" "SELECT COUNT(*) FROM $tbl;" 2>/dev/null || echo 0)
    if [ "$count" -ge "$min" ]; then
      ok "$tbl: $count rows — $desc" >&2
    else
      if [ "$min" -gt 0 ]; then
        fail "$tbl: $count rows (expected >= $min) — $desc" >&2
      else
        warn "$tbl: $count rows (empty but exists) — $desc" >&2
      fi
    fi
  else
    fail "Table missing: $tbl — $desc" >&2
    count=0
  fi
  echo "$count"
}

BAL_BACKUP=$(check_table "balances" "$MIN_BALANCES" "wallet balances")
HDR_BACKUP=$(check_table "headers" "$MIN_HEADERS" "block headers (chain height)")
LED_BACKUP=$(check_table "ledger" "$MIN_LEDGER" "transaction ledger")
EPO_BACKUP=$(check_table "epoch_rewards" "$MIN_EPOCH_REWARDS" "epoch reward records")
check_table "miner_attest_recent" 0 "recent attestations" 2>&1 >/dev/null

# ─── Compare with live DB (row count drift check) ────────────────────────────
if [ -f "$LIVE_DB" ]; then
  echo ""
  log "Comparing backup with live DB..."
  LIVE_BAL=$(sqlite3 "$LIVE_DB" "SELECT COUNT(*) FROM balances;" 2>/dev/null || echo 0)
  LIVE_HDR=$(sqlite3 "$LIVE_DB" "SELECT COUNT(*) FROM headers;" 2>/dev/null || echo 0)
  LIVE_LED=$(sqlite3 "$LIVE_DB" "SELECT COUNT(*) FROM ledger;" 2>/dev/null || echo 0)
  LIVE_EPO=$(sqlite3 "$LIVE_DB" "SELECT COUNT(*) FROM epoch_rewards;" 2>/dev/null || echo 0)

  compare_counts() {
    local table="$1" backup_cnt="$2" live_cnt="$3"
    local diff=$(( live_cnt - backup_cnt ))
    # Allow up to 1 epoch worth of lag (roughly 10 min of activity)
    # If backup is more than 2 epochs behind, warn; if ahead, that's an error
    if [ "$backup_cnt" -gt "$live_cnt" ]; then
      warn "$table: backup has more rows ($backup_cnt) than live ($live_cnt) — unusual"
    elif [ "$diff" -le 100 ]; then
      ok "$table: backup=$backup_cnt live=$live_cnt (diff: $diff rows) ✓ in sync"
    else
      warn "$table: backup=$backup_cnt live=$live_cnt (diff: $diff rows) — backup may be stale"
    fi
  }

  compare_counts "balances" "$BAL_BACKUP" "$LIVE_BAL"
  compare_counts "headers" "$HDR_BACKUP" "$LIVE_HDR"
  compare_counts "ledger" "$LED_BACKUP" "$LIVE_LED"
  compare_counts "epoch_rewards" "$EPO_BACKUP" "$LIVE_EPO"
else
  warn "Live DB not found at $LIVE_DB — skipping row count comparison"
fi

# ─── Check backup file age ────────────────────────────────────────────────────
echo ""
log "Checking backup file age..."
BACKUP_AGE_SEC=$(( $(date +%s) - $(stat -c %Y "$BACKUP_DB" 2>/dev/null || date +%s) ))
BACKUP_AGE_HRS=$(( BACKUP_AGE_SEC / 3600 ))

if [ "$BACKUP_AGE_HRS" -le 25 ]; then
  ok "Backup age: ${BACKUP_AGE_HRS}h (within 25h threshold)"
elif [ "$BACKUP_AGE_HRS" -le 48 ]; then
  warn "Backup age: ${BACKUP_AGE_HRS}h (between 25-48h — consider more frequent backups)"
else
  fail "Backup age: ${BACKUP_AGE_HRS}h (over 48h — backup is too old!)"
fi

# ─── Final result ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
FAILURES=$(wc -l < "$FAIL_FILE" 2>/dev/null || echo 0)
if [ "$FAILURES" -eq 0 ]; then
  echo -e "[$TIMESTAMP] ${GREEN}${BOLD}RESULT: PASS ✅${NC}"
  echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
  echo ""
  exit 0
else
  echo -e "[$TIMESTAMP] ${RED}${BOLD}RESULT: FAIL ✗ ($FAILURES failure(s) detected)${NC}"
  echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
  echo ""
  exit 1
fi
