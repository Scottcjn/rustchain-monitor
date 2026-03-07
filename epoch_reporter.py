#!/usr/bin/env python3
"""
RustChain Epoch Reporter Bot

Automatically posts epoch summaries to Discord after each epoch settlement.
Keeps the community engaged without manual effort.

Usage:
    ./epoch_reporter.py [--config config.json]

Environment variables:
    DISCORD_WEBHOOK_URL - Discord webhook URL
    MOLTBOOK_API_KEY   - Moltbook API key
    MOLTBOOK_API_URL   - Moltbook API URL (default: https://moltbook.ai/api/v1)
    API_NODE           - RustChain node URL (default: https://50.28.86.131)
    POLL_INTERVAL      - Seconds between polls (default: 60)
    STATE_FILE         - Path to track last epoch (default: .epoch_state.json)

Payout: 10-15 RTC (bounty #749)
Wallet: Include your wallet address when claiming
"""

import argparse
import json
import os
import sys
import time
import requests
from datetime import datetime
from pathlib import Path

# Defaults
DEFAULT_NODE = "https://50.28.86.131"
DEFAULT_INTERVAL = 60
DEFAULT_STATE_FILE = ".epoch_state.json"


def load_state(state_file: str) -> dict:
    """Load the last epoch state from file."""
    path = Path(state_file)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"last_epoch": None, "last_posted": None}


def save_state(state_file: str, state: dict) -> None:
    """Save the epoch state to file."""
    with open(state_file, "w") as f:
        json.dump(state, f)


def fetch_epoch(node_url: str) -> dict:
    """Fetch current epoch data from the RustChain node."""
    try:
        resp = requests.get(f"{node_url}/epoch", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"Error fetching epoch: {e}", file=sys.stderr)
        return None


def fetch_miners(node_url: str) -> list:
    """Fetch active miners from the RustChain node."""
    try:
        resp = requests.get(f"{node_url}/api/miners", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"Error fetching miners: {e}", file=sys.stderr)
        return []


def format_epoch_message(epoch_data: dict, miners: list) -> str:
    """Format epoch data into a Discord embed message."""
    epoch = epoch_data.get("epoch", "N/A")
    reward = epoch_data.get("reward", epoch_data.get("base_reward", "N/A"))
    block_height = epoch_data.get("height", epoch_data.get("block_height", "N/A"))
    
    # Count miners by hardware type
    hardware_counts = {}
    for miner in miners:
        hw = miner.get("hardware", miner.get("type", "unknown"))
        hardware_counts[hw] = hardware_counts.get(hw, 0) + 1
    
    # Find top earner (if available in epoch data)
    top_earner = epoch_data.get("top_miner", epoch_data.get("top_earner"))
    top_amount = epoch_data.get("top_amount", epoch_data.get("top_reward"))
    
    # Format hardware breakdown
    hw_emoji = {
        "PowerPC G4": "G4",
        "PowerPC G5": "G5", 
        "PowerPC G3": "G3",
        "IBM POWER8": "POWER8",
        "Vintage x86": "x86",
        "Apple Silicon": "M-series",
        "Modern": "Modern",
    }
    
    hw_parts = []
    for hw, count in sorted(hardware_counts.items(), key=lambda x: -x[1]):
        short = hw_emoji.get(hw, hw[:6])
        hw_parts.append(f"{short}: {count}")
    
    total_rtc = float(reward) * len(miners) if isinstance(reward, (int, float)) else "N/A"
    
    message = f"""📊 **Epoch {epoch} Complete**

💰 **{reward} RTC** distributed to **{len(miners)}** miners"""
    
    if top_earner and top_amount:
        message += f"""
🏆 Top earner: {top_earner} ({top_amount} RTC)"""
    
    if hw_parts:
        message += f"""
⛏️ Active miners: {len(miners)} ({", ".join(hw_parts)})"""
    
    message += f"""
📦 Block height: {block_height}
💎 Total RTC mined: {total_rtc}

🔍 Explorer: {DEFAULT_NODE}/explorer"""

    return message


def post_to_discord(webhook_url: str, message: str) -> bool:
    """Post message to Discord webhook."""
    if not webhook_url:
        print("Discord webhook URL not configured", file=sys.stderr)
        return False
    
    try:
        resp = requests.post(
            webhook_url,
            json={"content": message},
            timeout=10
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"Error posting to Discord: {e}", file=sys.stderr)
        return False


def post_to_moltbook(api_key: str, api_url: str, message: str) -> bool:
    """Post message to Moltbook API."""
    if not api_key:
        return False
    
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.post(
            f"{api_url}/posts",
            headers=headers,
            json={"content": message},
            timeout=10
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"Error posting to Moltbook: {e}", file=sys.stderr)
        return False


def run_once(node_url: str, state: dict, discord_webhook: str, moltbook_key: str, moltbook_url: str) -> dict:
    """Run one poll cycle. Returns updated state."""
    epoch_data = fetch_epoch(node_url)
    if not epoch_data:
        return state
    
    current_epoch = epoch_data.get("epoch")
    if current_epoch is None:
        return state
    
    # Check if new epoch
    if current_epoch != state.get("last_epoch"):
        miners = fetch_miners(node_url)
        message = format_epoch_message(epoch_data, miners)
        
        # Post to configured platforms
        posted = False
        if discord_webhook:
            posted = post_to_discord(discord_webhook, message) or posted
        if moltbook_key:
            posted = post_to_moltbook(moltbook_key, moltbook_url, message) or posted
        
        if posted:
            print(f"Posted epoch {current_epoch} summary")
            state["last_epoch"] = current_epoch
            state["last_posted"] = datetime.utcnow().isoformat()
        else:
            print(f"New epoch {current_epoch} but no platforms configured")
    
    return state


def main():
    parser = argparse.ArgumentParser(description="RustChain Epoch Reporter Bot")
    parser.add_argument("--config", help="Config file path (JSON)")
    parser.add_argument("--node", default=os.environ.get("API_NODE", DEFAULT_NODE),
                        help="RustChain node URL")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLL_INTERVAL", DEFAULT_INTERVAL)),
                        help="Poll interval in seconds")
    parser.add_argument("--state-file", default=os.environ.get("STATE_FILE", DEFAULT_STATE_FILE),
                        help="State file path")
    parser.add_argument("--discord", default=os.environ.get("DISCORD_WEBHOOK_URL"),
                        help="Discord webhook URL")
    parser.add_argument("--moltbook-key", default=os.environ.get("MOLTBOOK_API_KEY"),
                        help="Moltbook API key")
    parser.add_argument("--moltbook-url", default=os.environ.get("MOLTBOOK_API_URL", "https://moltbook.ai/api/v1"),
                        help="Moltbook API URL")
    parser.add_argument("--once", action="store_true",
                        help="Run once instead of continuous loop")
    
    args = parser.parse_args()
    
    # Load config from file if provided
    config = {}
    if args.config and Path(args.config).exists():
        with open(args.config) as f:
            config = json.load(f)
    
    # Merge config with args (args take precedence)
    node_url = args.node
    discord_webhook = args.discord or config.get("discord_webhook")
    moltbook_key = args.moltbook_key or config.get("moltbook_api_key")
    moltbook_url = args.moltbook_url
    poll_interval = args.interval
    state_file = args.state_file
    
    print(f"RustChain Epoch Reporter starting...")
    print(f"Node: {node_url}")
    print(f"Poll interval: {poll_interval}s")
    print(f"Discord: {'configured' if discord_webhook else 'not configured'}")
    print(f"Moltbook: {'configured' if moltbook_key else 'not configured'}")
    
    state = load_state(state_file)
    print(f"Last epoch: {state.get('last_epoch')}")
    
    if args.once:
        state = run_once(node_url, state, discord_webhook, moltbook_key, moltbook_url)
        save_state(state_file, state)
    else:
        try:
            while True:
                state = run_once(node_url, state, discord_webhook, moltbook_key, moltbook_url)
                save_state(state_file, state)
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\nShutting down...")


if __name__ == "__main__":
    main()
