#!/bin/bash
#
# RustChain Backup Verification Script
# Verifies SQLite backup integrity and data consistency
#
# Usage: ./verify_backup.sh [backup_file]
# Exit codes: 0 = PASS, 1 = FAIL
#

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/root/rustchain/backups}"
LIVE_DB="${LIVE_DB:-/root/rustchain/rustchain_v2.db}"
TEMP_DIR="/tmp/rustchain_backup_verify_$$"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo "$LOG_PREFIX $1"
}

log_success() {
    echo -e "$LOG_PREFIX ${GREEN}✅ $1${NC}"
}

log_error() {
    echo -e "$LOG_PREFIX ${RED}❌ $1${NC}"
}

log_warn() {
    echo -e "$LOG_PREFIX ${YELLOW}⚠️  $1${NC}"
}

# Cleanup function
cleanup() {
    if [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}

trap cleanup EXIT

# Find latest backup
find_latest_backup() {
    if [ -n "$1" ]; then
        echo "$1"
        return
    fi
    
    local latest=$(find "$BACKUP_DIR" -name "*.db*" -type f 2>/dev/null | sort -r | head -1)
    
    if [ -z "$latest" ]; then
        log_error "No backup files found in $BACKUP_DIR"
        exit 1
    fi
    
    echo "$latest"
}

# Check SQLite integrity
check_integrity() {
    local db_file="$1"
    
    log_info "Running integrity check..."
    
    local result=$(sqlite3 "$db_file" "PRAGMA integrity_check;" 2>&1)
    
    if [ "$result" = "ok" ]; then
        log_success "Integrity check: PASS"
        return 0
    else
        log_error "Integrity check: FAIL - $result"
        return 1
    fi
}

# Check table exists and has data
check_table() {
    local db_file="$1"
    local table_name="$2"
    local min_rows="${3:-1}"
    
    # Check if table exists
    local exists=$(sqlite3 "$db_file" "SELECT name FROM sqlite_master WHERE type='table' AND name='$table_name';" 2>/dev/null)
    
    if [ -z "$exists" ]; then
        log_error "Table '$table_name': NOT FOUND"
        return 1
    fi
    
    # Count rows
    local count=$(sqlite3 "$db_file" "SELECT COUNT(*) FROM $table_name;" 2>/dev/null)
    
    if [ -z "$count" ] || [ "$count" -lt "$min_rows" ]; then
        log_error "Table '$table_name': $count rows (expected >= $min_rows)"
        return 1
    fi
    
    log_success "Table '$table_name': $count rows"
    return 0
}

# Compare row counts between backup and live DB
compare_row_counts() {
    local backup_db="$1"
    local live_db="$2"
    local table_name="$3"
    local max_diff="${4:-1000}"  # Allow up to 1000 rows difference (1 epoch)
    
    if [ ! -f "$live_db" ]; then
        log_warn "Live DB not found, skipping comparison for $table_name"
        return 0
    fi
    
    local backup_count=$(sqlite3 "$backup_db" "SELECT COUNT(*) FROM $table_name;" 2>/dev/null || echo "0")
    local live_count=$(sqlite3 "$live_db" "SELECT COUNT(*) FROM $table_name;" 2>/dev/null || echo "0")
    
    local diff=$((live_count - backup_count))
    
    if [ $diff -lt 0 ]; then
        diff=$((-diff))
    fi
    
    if [ $diff -gt $max_diff ]; then
        log_error "Table '$table_name': backup has $backup_count rows, live has $live_count rows (diff: $diff > $max_diff)"
        return 1
    fi
    
    log_success "Table '$table_name': backup=$backup_count, live=$live_count (diff: $diff) ✅"
    return 0
}

# Check for recent attestations
check_recent_attestations() {
    local db_file="$1"
    
    # Check if miner_attest_recent table exists
    local table_exists=$(sqlite3 "$db_file" "SELECT name FROM sqlite_master WHERE type='table' AND name='miner_attest_recent';" 2>/dev/null)
    
    if [ -z "$table_exists" ]; then
        log_warn "Table 'miner_attest_recent' not found, checking alternative tables..."
        
        # Try attestations table
        table_exists=$(sqlite3 "$db_file" "SELECT name FROM sqlite_master WHERE type='table' AND name='attestations';" 2>/dev/null)
        
        if [ -n "$table_exists" ]; then
            local count=$(sqlite3 "$db_file" "SELECT COUNT(*) FROM attestations WHERE timestamp > strftime('%s', 'now') - 86400;" 2>/dev/null || echo "0")
            log_success "Recent attestations (24h): $count"
            return 0
        fi
        
        log_warn "No attestation tables found"
        return 0
    fi
    
    local count=$(sqlite3 "$db_file" "SELECT COUNT(*) FROM miner_attest_recent;" 2>/dev/null || echo "0")
    log_success "Recent attestations: $count"
    return 0
}

# Main verification function
verify_backup() {
    local backup_file="$1"
    local failed=0
    
    log_info "Backup: $backup_file"
    
    # Check if backup file exists
    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi
    
    # Get file size
    local size=$(du -h "$backup_file" | cut -f1)
    log_info "Size: $size"
    
    # Create temp directory
    mkdir -p "$TEMP_DIR"
    
    # Copy backup to temp location
    log_info "Copying backup to temp location..."
    cp "$backup_file" "$TEMP_DIR/backup.db" || {
        log_error "Failed to copy backup file"
        return 1
    }
    
    local temp_db="$TEMP_DIR/backup.db"
    
    # Run integrity check
    check_integrity "$temp_db" || ((failed++))
    
    # Check key tables
    log_info "Checking key tables..."
    
    check_table "$temp_db" "balances" 1 || ((failed++))
    check_table "$temp_db" "headers" 1 || ((failed++))
    check_table "$temp_db" "ledger" 0 || ((failed++))
    
    # Check recent attestations
    check_recent_attestations "$temp_db" || ((failed++))
    
    # Compare with live DB if available
    if [ -f "$LIVE_DB" ]; then
        log_info "Comparing with live DB..."
        compare_row_counts "$temp_db" "$LIVE_DB" "balances" 100 || ((failed++))
        compare_row_counts "$temp_db" "$LIVE_DB" "headers" 1000 || ((failed++))
    else
        log_warn "Live DB not found at $LIVE_DB, skipping comparison"
    fi
    
    # Final result
    echo ""
    if [ $failed -eq 0 ]; then
        log_success "RESULT: PASS - Backup is valid ✅"
        return 0
    else
        log_error "RESULT: FAIL - $failed check(s) failed ❌"
        return 1
    fi
}

# Main script
main() {
    echo "========================================="
    echo "RustChain Backup Verification"
    echo "========================================="
    echo ""
    
    # Find backup file
    BACKUP_FILE=$(find_latest_backup "$1")
    
    # Verify backup
    if verify_backup "$BACKUP_FILE"; then
        exit 0
    else
        exit 1
    fi
}

# Run main function
main "$@"
