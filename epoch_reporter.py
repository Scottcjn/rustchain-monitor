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
    return {
        "last_epoch": None,
        "last_posted": None,
        "tracked_miners": {},
        "last_health_ok": None,
        "last_reward_alert_epoch": None,
    }


def normalize_state(state: dict | None) -> dict:
    merged = default_state()
    if isinstance(state, dict):
        merged.update(state)
    if not isinstance(merged.get("tracked_miners"), dict):
        merged["tracked_miners"] = {}
    return merged


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def first_non_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def load_state(state_file: str) -> dict:
    """Load the last reporter state from file."""
    path = Path(state_file)
    if path.exists():
        try:
            with open(path) as handle:
                return normalize_state(json.load(handle))
        except (json.JSONDecodeError, IOError):
            pass
    return default_state()


def save_state(state_file: str, state: dict) -> None:
    """Save the reporter state to file."""
    with open(state_file, "w") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def _fetch_json(node_url: str, path: str, label: str):
    try:
        response = requests.get(f"{node_url}{path}", timeout=10, verify=False)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        print(f"Error fetching {label}: {exc}", file=sys.stderr)
        return None


def fetch_epoch(node_url: str):
    return _fetch_json(node_url, "/epoch", "epoch")


def fetch_miners(node_url: str):
    return _fetch_json(node_url, "/api/miners", "miners")


def fetch_health(node_url: str):
    return _fetch_json(node_url, "/health", "health")


def _float_or_none(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _health_db_rw(health_data: dict) -> bool:
    if "db_rw" in health_data:
        return bool(health_data.get("db_rw"))
    db_value = str(health_data.get("db", "") or "").lower()
    return "rw" in db_value


def health_problems(health_data: dict | None, *, tip_age_max: int, backup_age_max_hours: float) -> list[str]:
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
    if not epoch_data:
        return None
    return _float_or_none(
        epoch_data.get("reward", epoch_data.get("epoch_pot", epoch_data.get("base_reward")))
    )


def format_epoch_message(epoch_data: dict, miners: list | None, node_url: str) -> str:
    """Format epoch data into a summary notification."""
    miners = miners or []
    epoch = epoch_data.get("epoch", "N/A")
    reward = epoch_data.get("reward", epoch_data.get("epoch_pot", epoch_data.get("base_reward", "N/A")))
    block_height = epoch_data.get("height", epoch_data.get("block_height", "N/A"))
    enrolled = epoch_data.get("enrolled_miners", len(miners))

    hardware_counts = {}
    for miner in miners:
        hw = (
            miner.get("device_family")
            or miner.get("hardware_type")
            or miner.get("device_arch")
            or "unknown"
        )
        hardware_counts[hw] = hardware_counts.get(hw, 0) + 1

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
    arch = info.get("device_arch", "unknown")
    missed = int(info.get("missed_polls", 0))
    return f"Miner offline alert\nMiner: {miner_id}\nArch: {arch}\nMissed polls: {missed}"


def format_recovery_alert(miner_id: str, miner: dict) -> str:
    arch = miner.get("device_arch", "unknown")
    last_attest = miner.get("last_attest")
    return f"Miner recovery alert\nMiner: {miner_id}\nArch: {arch}\nLast attest: {last_attest}"


def format_health_alert(node_url: str, problems: list[str], health_data: dict | None, *, recovered: bool = False) -> str:
    if recovered:
        version = (health_data or {}).get("version", "unknown")
        return f"Network health recovered\nNode: {node_url}\nVersion: {version}"

    lines = [
        "Network health alert",
        f"Node: {node_url}",
        f"Problems: {', '.join(problems)}",
    ]
    if health_data:
        lines.append(f"Version: {health_data.get('version', 'unknown')}")
        lines.append(f"Tip age: {health_data.get('tip_age_slots', 'n/a')}")
        lines.append(f"Backup age hours: {health_data.get('backup_age_hours', 'n/a')}")
        lines.append(f"DB RW: {health_data.get('db_rw', health_data.get('db', 'n/a'))}")
    return "\n".join(lines)


def format_reward_alert(epoch_data: dict, reward_value: float, reward_min: float | None, reward_max: float | None) -> str:
    epoch = epoch_data.get("epoch", "N/A")
    return (
        "Unexpected reward alert\n"
        f"Epoch: {epoch}\n"
        f"Observed reward: {reward_value} RTC\n"
        f"Configured min: {reward_min}\n"
        f"Configured max: {reward_max}"
    )


def post_to_discord(webhook_url: str, message: str) -> bool:
    if not webhook_url:
        return False
    try:
        response = requests.post(webhook_url, json={"content": message}, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"Error posting to Discord: {exc}", file=sys.stderr)
        return False


def post_to_slack(webhook_url: str, message: str) -> bool:
    if not webhook_url:
        return False
    try:
        response = requests.post(webhook_url, json={"text": message}, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"Error posting to Slack: {exc}", file=sys.stderr)
        return False


def post_to_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    if not bot_token or not chat_id:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"Error posting to Telegram: {exc}", file=sys.stderr)
        return False


def post_to_moltbook(api_key: str, api_url: str, message: str) -> bool:
    if not api_key:
        return False
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.post(
            f"{api_url}/posts",
            headers=headers,
            json={"content": message},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"Error posting to Moltbook: {exc}", file=sys.stderr)
        return False


def notify_channels(
    message: str,
    *,
    discord_webhook: str | None = None,
    slack_webhook: str | None = None,
    telegram_token: str | None = None,
    telegram_chat_id: str | None = None,
) -> bool:
    delivered = False
    delivered = post_to_discord(discord_webhook, message) or delivered
    delivered = post_to_slack(slack_webhook, message) or delivered
    delivered = post_to_telegram(telegram_token, telegram_chat_id, message) or delivered
    return delivered


def update_health_state(
    state: dict,
    health_data: dict | None,
    *,
    node_url: str,
    tip_age_max: int,
    backup_age_max_hours: float,
) -> list[str]:
    problems = health_problems(
        health_data,
        tip_age_max=tip_age_max,
        backup_age_max_hours=backup_age_max_hours,
    )
    is_healthy = not problems
    last_health_ok = state.get("last_health_ok")
    messages = []

    if not is_healthy and last_health_ok is not False:
        messages.append(format_health_alert(node_url, problems, health_data, recovered=False))
    elif is_healthy and last_health_ok is False:
        messages.append(format_health_alert(node_url, [], health_data, recovered=True))

    state["last_health_ok"] = is_healthy
    return messages


def update_miner_tracking(state: dict, miners: list[dict] | None, *, offline_polls: int) -> list[str]:
    if miners is None:
        return []

    tracked = state.setdefault("tracked_miners", {})
    messages = []
    active_miners = {}

    for miner in miners:
        miner_id = miner.get("miner") or miner.get("miner_id")
        if not miner_id:
            continue
        active_miners[miner_id] = miner
        existing = tracked.get(miner_id, {})
        if existing.get("offline_alerted"):
            messages.append(format_recovery_alert(miner_id, miner))
        tracked[miner_id] = {
            "device_arch": miner.get("device_arch", "unknown"),
            "last_attest": miner.get("last_attest"),
            "missed_polls": 0,
            "offline_alerted": False,
        }

    for miner_id, info in list(tracked.items()):
        if miner_id in active_miners:
            continue
        missed_polls = int(info.get("missed_polls", 0)) + 1
        info["missed_polls"] = missed_polls
        if missed_polls >= offline_polls and not info.get("offline_alerted"):
            messages.append(format_offline_alert(miner_id, info))
            info["offline_alerted"] = True
        tracked[miner_id] = info

    return messages


def check_reward_alert(
    state: dict,
    epoch_data: dict | None,
    *,
    reward_min: float | None,
    reward_max: float | None,
) -> str | None:
    if reward_min is None and reward_max is None:
        return None
    if not epoch_data:
        return None

    reward_value = extract_reward_value(epoch_data)
    current_epoch = epoch_data.get("epoch")
    if reward_value is None or current_epoch is None:
        return None

    out_of_range = (
        (reward_min is not None and reward_value < reward_min)
        or (reward_max is not None and reward_value > reward_max)
    )
    if not out_of_range:
        return None
    if state.get("last_reward_alert_epoch") == current_epoch:
        return None

    state["last_reward_alert_epoch"] = current_epoch
    return format_reward_alert(epoch_data, reward_value, reward_min, reward_max)


def run_once(
    node_url: str,
    state: dict,
    *,
    discord_webhook: str | None = None,
    slack_webhook: str | None = None,
    telegram_token: str | None = None,
    telegram_chat_id: str | None = None,
    moltbook_key: str | None = None,
    moltbook_url: str = DEFAULT_MOLTBOOK_URL,
    offline_polls: int = DEFAULT_OFFLINE_POLLS,
    reward_min: float | None = None,
    reward_max: float | None = None,
    tip_age_max: int = DEFAULT_TIP_AGE_MAX,
    backup_age_max_hours: float = DEFAULT_BACKUP_AGE_MAX_HOURS,
) -> dict:
    """Run one poll cycle and return updated state."""
    state = normalize_state(state)

    health_data = fetch_health(node_url)
    epoch_data = fetch_epoch(node_url)
    miners = fetch_miners(node_url)

    messages = []
    messages.extend(
        update_health_state(
            state,
            health_data,
            node_url=node_url,
            tip_age_max=tip_age_max,
            backup_age_max_hours=backup_age_max_hours,
        )
    )
    messages.extend(update_miner_tracking(state, miners, offline_polls=offline_polls))

    reward_message = check_reward_alert(
        state,
        epoch_data,
        reward_min=reward_min,
        reward_max=reward_max,
    )
    if reward_message:
        messages.append(reward_message)

    for message in messages:
        delivered = notify_channels(
            message,
            discord_webhook=discord_webhook,
            slack_webhook=slack_webhook,
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
        )
        status = "sent" if delivered else "suppressed"
        print(f"Alert {status}: {message.splitlines()[0]}")

    if epoch_data:
        current_epoch = epoch_data.get("epoch")
        if current_epoch is not None and current_epoch != state.get("last_epoch"):
            epoch_message = format_epoch_message(epoch_data, miners or [], node_url)
            delivered = notify_channels(
                epoch_message,
                discord_webhook=discord_webhook,
                slack_webhook=slack_webhook,
                telegram_token=telegram_token,
                telegram_chat_id=telegram_chat_id,
            )
            if moltbook_key:
                delivered = post_to_moltbook(moltbook_key, moltbook_url, epoch_message) or delivered
            state["last_epoch"] = current_epoch
            if delivered:
                state["last_posted"] = now_iso()
            print(f"Observed new epoch {current_epoch}")

    return state


def load_config(config_path: str | None) -> dict:
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path) as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description="RustChain Epoch Reporter Bot")
    parser.add_argument("--config", help="Config file path (JSON)")
    parser.add_argument("--node", help="RustChain node URL")
    parser.add_argument("--interval", type=int, help="Poll interval in seconds")
    parser.add_argument("--state-file", help="State file path")
    parser.add_argument("--discord", help="Discord webhook URL")
    parser.add_argument("--slack", help="Slack incoming webhook URL")
    parser.add_argument("--telegram-token", help="Telegram bot token")
    parser.add_argument("--telegram-chat-id", help="Telegram chat ID")
    parser.add_argument("--moltbook-key", help="Moltbook API key")
    parser.add_argument("--moltbook-url", help="Moltbook API URL")
    parser.add_argument("--offline-polls", type=int, help="Consecutive missed polls before offline alert")
    parser.add_argument("--reward-min", type=float, help="Optional minimum accepted epoch reward")
    parser.add_argument("--reward-max", type=float, help="Optional maximum accepted epoch reward")
    parser.add_argument("--tip-age-max", type=int, help="Max tip age in slots before health alert")
    parser.add_argument("--backup-age-max-hours", type=float, help="Max backup age in hours before health alert")
    parser.add_argument("--once", action="store_true", help="Run once instead of continuous loop")

    args = parser.parse_args()
    config = load_config(args.config)

    node_url = first_non_none(args.node, os.environ.get("API_NODE"), config.get("node"), DEFAULT_NODE)
    discord_webhook = first_non_none(args.discord, os.environ.get("DISCORD_WEBHOOK_URL"), config.get("discord_webhook"))
    slack_webhook = first_non_none(args.slack, os.environ.get("SLACK_WEBHOOK_URL"), config.get("slack_webhook"))
    telegram_token = first_non_none(args.telegram_token, os.environ.get("TELEGRAM_BOT_TOKEN"), config.get("telegram_bot_token"))
    telegram_chat_id = first_non_none(args.telegram_chat_id, os.environ.get("TELEGRAM_CHAT_ID"), config.get("telegram_chat_id"))
    moltbook_key = first_non_none(args.moltbook_key, os.environ.get("MOLTBOOK_API_KEY"), config.get("moltbook_api_key"))
    moltbook_url = first_non_none(args.moltbook_url, os.environ.get("MOLTBOOK_API_URL"), config.get("moltbook_api_url"), DEFAULT_MOLTBOOK_URL)
    poll_interval = int(first_non_none(args.interval, _float_or_none(os.environ.get("POLL_INTERVAL")), config.get("poll_interval"), DEFAULT_INTERVAL))
    state_file = first_non_none(args.state_file, os.environ.get("STATE_FILE"), config.get("state_file"), DEFAULT_STATE_FILE)
    offline_polls = int(first_non_none(args.offline_polls, _float_or_none(os.environ.get("OFFLINE_POLLS")), config.get("offline_polls"), DEFAULT_OFFLINE_POLLS))
    reward_min = first_non_none(args.reward_min, _float_or_none(os.environ.get("REWARD_MIN")), _float_or_none(config.get("reward_min")))
    reward_max = first_non_none(args.reward_max, _float_or_none(os.environ.get("REWARD_MAX")), _float_or_none(config.get("reward_max")))
    tip_age_max = int(first_non_none(args.tip_age_max, _float_or_none(os.environ.get("HEALTH_TIP_AGE_MAX")), config.get("tip_age_max"), DEFAULT_TIP_AGE_MAX))
    backup_age_max_hours = float(first_non_none(args.backup_age_max_hours, _float_or_none(os.environ.get("HEALTH_BACKUP_AGE_MAX")), config.get("backup_age_max_hours"), DEFAULT_BACKUP_AGE_MAX_HOURS))

    print("RustChain Epoch Reporter starting...")
    print(f"Node: {node_url}")
    print(f"Poll interval: {poll_interval}s")
    print(f"Discord: {'configured' if discord_webhook else 'not configured'}")
    print(f"Slack: {'configured' if slack_webhook else 'not configured'}")
    print(f"Telegram: {'configured' if telegram_token and telegram_chat_id else 'not configured'}")
    print(f"Moltbook: {'configured' if moltbook_key else 'not configured'}")
    print(f"Offline polls: {offline_polls}")
    print(f"Reward thresholds: min={reward_min} max={reward_max}")
    print(f"Health thresholds: tip_age<={tip_age_max}, backup_age<={backup_age_max_hours}h")

    state = load_state(state_file)
    print(f"Last epoch: {state.get('last_epoch')}")

    def run_cycle(current_state: dict) -> dict:
        return run_once(
            node_url,
            current_state,
            discord_webhook=discord_webhook,
            slack_webhook=slack_webhook,
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
            moltbook_key=moltbook_key,
            moltbook_url=moltbook_url,
            offline_polls=offline_polls,
            reward_min=reward_min,
            reward_max=reward_max,
            tip_age_max=tip_age_max,
            backup_age_max_hours=backup_age_max_hours,
        )

    if args.once:
        state = run_cycle(state)
        save_state(state_file, state)
    else:
        try:
            while True:
                state = run_cycle(state)
                save_state(state_file, state)
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\nShutting down...")


if __name__ == "__main__":
    main()
