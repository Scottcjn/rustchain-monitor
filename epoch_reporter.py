#!/usr/bin/env python3
"""
RustChain Epoch Reporter Bot

Posts epoch summaries and alert notifications to chat/webhook platforms.

Usage:
    ./epoch_reporter.py [--config config.json]

Environment variables:
    DISCORD_WEBHOOK_URL       - Discord webhook URL
    SLACK_WEBHOOK_URL         - Slack incoming webhook URL
    TELEGRAM_BOT_TOKEN        - Telegram bot token
    TELEGRAM_CHAT_ID          - Telegram chat ID
    MOLTBOOK_API_KEY          - Moltbook API key
    MOLTBOOK_API_URL          - Moltbook API URL (default: https://moltbook.ai/api/v1)
    API_NODE                  - RustChain node URL (default: https://50.28.86.131)
    POLL_INTERVAL             - Seconds between polls (default: 60)
    STATE_FILE                - Path to track alert state (default: .epoch_state.json)
    OFFLINE_POLLS             - Consecutive missed polls before offline alert (default: 2)
    REWARD_MIN                - Optional minimum accepted epoch reward
    REWARD_MAX                - Optional maximum accepted epoch reward
    HEALTH_TIP_AGE_MAX        - Max tip age in slots before health alert (default: 100)
    HEALTH_BACKUP_AGE_MAX     - Max backup age in hours before health alert (default: 6)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3


DEFAULT_NODE = "https://50.28.86.131"
DEFAULT_INTERVAL = 60
DEFAULT_STATE_FILE = ".epoch_state.json"
DEFAULT_MOLTBOOK_URL = "https://moltbook.ai/api/v1"
DEFAULT_OFFLINE_POLLS = 2
DEFAULT_TIP_AGE_MAX = 100
DEFAULT_BACKUP_AGE_MAX_HOURS = 6.0


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def default_state() -> dict:
    """
    Initialize default reporter state.
    
    Returns a dictionary with all required state fields:
    - last_epoch: Track last processed epoch to avoid duplicate posts
    - last_posted: Timestamp of last notification
    - tracked_miners: Dict of miner states for offline detection
    - last_health_ok: Timestamp of last healthy node check
    - last_reward_alert_epoch: Track reward anomaly alerts
    
    This state persists between runs to maintain alert continuity.
    """
    return {
        "last_epoch": None,
        "last_posted": None,
        "tracked_miners": {},
        "last_health_ok": None,
        "last_reward_alert_epoch": None,
    }


def normalize_state(state: dict | None) -> dict:
    """
    Normalize state dictionary to ensure all required fields exist.
    
    When loading state from file, older versions may be missing new fields.
    This function merges loaded state with defaults to prevent KeyError exceptions.
    Also validates that tracked_miners is always a dict (not None or other type).
    
    Args:
        state: Previously saved state (may be incomplete or None)
    
    Returns:
        Complete state dictionary with all required fields
    """
    merged = default_state()
    if isinstance(state, dict):
        merged.update(state)
    if not isinstance(merged.get("tracked_miners"), dict):
        merged["tracked_miners"] = {}
    return merged


def now_iso() -> str:
    """
    Get current UTC timestamp in ISO 8601 format.
    
    Returns timezone-aware UTC time with 'Z' suffix for consistency
    across different systems and log parsing tools.
    
    Example: '2026-03-13T04:10:51Z'
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def first_non_none(*values):
    """
    Return first non-None value from arguments.
    
    Utility function for handling optional config values with fallbacks.
    More readable than nested ternary operators.
    
    Example:
        reward = first_non_none(config.get('reward'), epoch.get('reward'), 0)
    """
    for value in values:
        if value is not None:
            return value
    return None


def load_state(state_file: str) -> dict:
    """
    Load the last reporter state from file.
    
    Handles missing files, corrupted JSON, and IO errors gracefully.
    Returns default state if file doesn't exist or is unreadable.
    
    The state file tracks:
    - Last processed epoch (prevents duplicate epoch posts)
    - Tracked miners (enables offline detection across restarts)
    - Last health check timestamp
    
    Args:
        state_file: Path to JSON state file
    
    Returns:
        Normalized state dictionary (never fails, returns default on error)
    """
    path = Path(state_file)
    if path.exists():
        try:
            with open(path) as handle:
                return normalize_state(json.load(handle))
        except (json.JSONDecodeError, IOError):
            # File corrupted or unreadable - start fresh
            # This is intentional: better to miss an alert than crash
            pass
    return default_state()


def save_state(state_file: str, state: dict) -> None:
    """
    Save the reporter state to file.
    
    Uses sorted keys for consistent diff-friendly output.
    Indent=2 for human readability during debugging.
    
    Args:
        state_file: Path to JSON state file
        state: State dictionary to persist
    """
    with open(state_file, "w") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def _fetch_json(node_url: str, path: str, label: str):
    """
    Fetch JSON from RustChain node API endpoint.
    
    Handles network errors, timeouts, and HTTP errors uniformly.
    Returns None on any failure (caller handles None gracefully).
    
    Why verify=False? RustChain nodes use self-signed certs by default.
    In production, deploy proper certs and set verify=True.
    
    Args:
        node_url: Base URL of RustChain node (e.g., https://50.28.86.131)
        path: API endpoint path (e.g., '/epoch', '/api/miners')
        label: Human-readable label for error messages
    
    Returns:
        Parsed JSON response or None on error
    """
    try:
        response = requests.get(f"{node_url}{path}", timeout=10, verify=False)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        print(f"Error fetching {label}: {exc}", file=sys.stderr)
        return None


def fetch_epoch(node_url: str):
    """
    Fetch current epoch data from node.
    
    Epoch data includes:
    - epoch: Current epoch number
    - reward/epoch_pot/base_reward: RTC reward for this epoch
    - height/block_height: Current block height
    - enrolled_miners: Number of miners enrolled in this epoch
    
    Returns None if node is unreachable or returns invalid JSON.
    """
    return _fetch_json(node_url, "/epoch", "epoch")


def fetch_miners(node_url: str):
    """
    Fetch list of active miners from node.
    
    Each miner entry includes:
    - miner_id: Unique identifier
    - device_arch: Hardware architecture (ppc64, x86_64, etc.)
    - device_family: Hardware family name
    - last_attest: Timestamp of last attestation
    - Various hardware and performance metrics
    
    Returns None if node is unreachable.
    """
    return _fetch_json(node_url, "/api/miners", "miners")


def fetch_health(node_url: str):
    """
    Fetch node health status.
    
    Health endpoint returns:
    - ok: Overall health boolean
    - db: Database mode ('rw' for read-write, 'ro' for read-only)
    - tip_age_slots: How far behind chain tip (in slots)
    - backup_age_hours: Age of last backup
    - version: Node software version
    
    Used to detect node degradation before it affects mining.
    Returns None if health endpoint is unavailable.
    """
    return _fetch_json(node_url, "/health", "health")


def _float_or_none(value):
    """
    Safely convert value to float, returning None on failure.
    
    Handles None, empty strings, and invalid numeric formats.
    Used for parsing API responses that may have inconsistent types.
    
    Args:
        value: Any value (string, int, float, None)
    
    Returns:
        Float value or None if conversion fails
    """
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _health_db_rw(health_data: dict) -> bool:
    """
    Check if database is in read-write mode.
    
    Some nodes report 'db' field, others report 'db_rw' boolean.
    This function handles both formats for backward compatibility.
    
    Database must be read-write for normal mining operations.
    Read-only mode indicates a problem (disk full, corruption, etc.).
    
    Args:
        health_data: Health endpoint response
    
    Returns:
        True if database is read-write, False otherwise
    """
    if "db_rw" in health_data:
        return bool(health_data.get("db_rw"))
    db_value = str(health_data.get("db", "") or "").lower()
    return "rw" in db_value


def health_problems(health_data: dict | None, *, tip_age_max: int, backup_age_max_hours: float) -> list[str]:
    """
    Analyze health data and return list of detected problems.
    
    Checks for:
    1. Node health check failure (ok=false)
    2. Database not in read-write mode
    3. Tip age exceeding threshold (node falling behind chain)
    4. Backup age exceeding threshold (backup system failing)
    
    All checks use thresholds to avoid false positives from transient issues.
    Empty list means node is healthy.
    
    Args:
        health_data: Health endpoint response (None if unavailable)
        tip_age_max: Maximum acceptable tip age in slots
        backup_age_max_hours: Maximum acceptable backup age in hours
    
    Returns:
        List of problem descriptions (empty if healthy)
    """
    if not health_data:
        return ["health endpoint unavailable"]

    problems = []
    if not health_data.get("ok"):
        problems.append("node health check returned not-ok")
    if not _health_db_rw(health_data):
        problems.append("database is not read-write")

    tip_age = _float_or_none(health_data.get("tip_age_slots"))
    if tip_age is not None and tip_age > float(tip_age_max):
        problems.append(f"tip age {tip_age:.0f} slots exceeds {tip_age_max}")

    backup_age = _float_or_none(health_data.get("backup_age_hours"))
    if backup_age is not None and backup_age > float(backup_age_max_hours):
        problems.append(f"backup age {backup_age:.2f}h exceeds {backup_age_max_hours:.2f}h")

    return problems


def extract_reward_value(epoch_data: dict | None):
    """
    Extract numeric reward value from epoch data.
    
    Different node versions use different field names:
    - 'reward': Current standard
    - 'epoch_pot': Legacy name
    - 'base_reward': Alternative name
    
    Returns None if epoch_data is None or reward is not numeric.
    """
    if not epoch_data:
        return None
    return _float_or_none(
        epoch_data.get("reward", epoch_data.get("epoch_pot", epoch_data.get("base_reward")))
    )


def format_epoch_message(epoch_data: dict, miners: list | None, node_url: str) -> str:
    """
    Format epoch data into human-readable summary notification.
    
    Creates multi-line message suitable for Discord/Slack/Telegram:
    - Epoch number and reward pot
    - Active miner count and hardware distribution
    - Block height and estimated RTC distribution
    
    Hardware mix helps identify centralization trends (e.g., too many x86 vs PPC).
    
    Args:
        epoch_data: Epoch endpoint response
        miners: List of active miners (may be None)
        node_url: Node URL for attribution
    
    Returns:
        Formatted multi-line message string
    """
    miners = miners or []
    epoch = epoch_data.get("epoch", "N/A")
    reward = epoch_data.get("reward", epoch_data.get("epoch_pot", epoch_data.get("base_reward", "N/A")))
    block_height = epoch_data.get("height", epoch_data.get("block_height", "N/A"))
    enrolled = epoch_data.get("enrolled_miners", len(miners))

    # Count miners by hardware type to detect centralization trends
    hardware_counts = {}
    for miner in miners:
        hw = (
            miner.get("device_family")
            or miner.get("hardware_type")
            or miner.get("device_arch")
            or "unknown"
        )
        hardware_counts[hw] = hardware_counts.get(hw, 0) + 1

    # Sort by count descending, then alphabetically for consistent output
    hw_parts = [f"{hw}: {count}" for hw, count in sorted(hardware_counts.items(), key=lambda item: (-item[1], item[0]))]
    total_rtc = float(reward) * enrolled if isinstance(reward, (int, float)) else "N/A"

    message = [
        f"Epoch {epoch} settled",
        f"Reward pot: {reward} RTC",
        f"Enrolled miners: {enrolled}",
        f"Currently active miners: {len(miners)}",
    ]
    if hw_parts:
        message.append(f"Hardware mix: {', '.join(hw_parts)}")
    message.append(f"Block height: {block_height}")
    message.append(f"Estimated RTC distributed: {total_rtc}")
    message.append(f"Node: {node_url}")
    return "\n".join(str(part) for part in message)


def format_offline_alert(miner_id: str, info: dict) -> str:
    """
    Format miner offline alert message.
    
    Triggered when miner misses consecutive polls (default: 2).
    Includes miner ID, architecture, and miss count for debugging.
    
    Args:
        miner_id: Unique miner identifier
        info: Tracked miner state (arch, missed_polls, etc.)
    
    Returns:
        Formatted alert message
    """
    arch = info.get("device_arch", "unknown")
    missed = int(info.get("missed_polls", 0))
    return f"Miner offline alert\nMiner: {miner_id}\nArch: {arch}\nMissed polls: {missed}"


def format_recovery_alert(miner_id: str, miner: dict) -> str:
    """
    Format miner recovery alert message.
    
    Triggered when previously offline miner comes back online.
    Includes last attestation timestamp to assess downtime duration.
    
    Args:
        miner_id: Unique miner identifier
        miner: Miner data from API (includes last_attest timestamp)
    
    Returns:
        Formatted recovery message
    """
    arch = miner.get("device_arch", "unknown")
    last_attest = miner.get("last_attest")
    return f"Miner recovery alert\nMiner: {miner_id}\nArch: {arch}\nLast attest: {last_attest}"


def format_health_alert(node_url: str, problems: list[str], health_data: dict | None, *, recovered: bool = False) -> str:
    """
    Format node health alert message.
    
    Reports detected problems or recovery status.
    Problems are listed line-by-line for readability.
    
    Args:
        node_url: Node URL for attribution
        problems: List of detected problems from health_problems()
        health_data: Health endpoint response (for version info)
        recovered: True if this is a recovery notification
    
    Returns:
        Formatted health alert message
    """
    if recovered:
        version = (health_data or {}).get("version", "unknown")
        return f"Network health recovered\nNode: {node_url}\nVersion: {version}"

    lines = [
