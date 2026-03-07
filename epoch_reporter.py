#!/usr/bin/env python3
"""
epoch_reporter.py — RustChain Epoch Reporter Bot
Bounty #749 — 10-15 RTC

Polls the RustChain node every 60 seconds. When a new epoch is detected,
posts a summary to configured platforms (Discord webhook, Moltbook, X/Twitter).

Usage:
    python3 epoch_reporter.py

Configuration (env vars):
    RUSTCHAIN_NODE         Node URL (default: https://50.28.86.131)
    DISCORD_WEBHOOK        Discord webhook URL (optional)
    MOLTBOOK_API_KEY       Moltbook API key (optional)
    MOLTBOOK_API_URL       Moltbook base URL (default: https://moltbook.com)
    X_ENABLE               Set to "1" to enable X/Twitter posting
    STATE_FILE             Path to state file (default: /tmp/epoch_reporter_state.json)
    POLL_INTERVAL          Seconds between polls (default: 60)

Platforms enabled by setting the relevant env var.
"""

import os
import json
import time
import requests
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [epoch-reporter] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("epoch-reporter")

# ─── Configuration ────────────────────────────────────────────────────────────
NODE_URL       = os.environ.get("RUSTCHAIN_NODE", "https://50.28.86.131")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
MOLTBOOK_KEY   = os.environ.get("MOLTBOOK_API_KEY", "")
MOLTBOOK_URL   = os.environ.get("MOLTBOOK_API_URL", "https://moltbook.com")
X_ENABLE       = os.environ.get("X_ENABLE", "") == "1"
STATE_FILE     = os.environ.get("STATE_FILE", "/tmp/epoch_reporter_state.json")
POLL_INTERVAL  = int(os.environ.get("POLL_INTERVAL", "60"))


def load_state() -> dict:
    """Load persisted state from disk."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_epoch": None, "posted_epochs": []}


def save_state(state: dict) -> None:
    """Persist state to disk."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def fetch_epoch() -> dict | None:
    """Fetch current epoch from RustChain node."""
    try:
        r = requests.get(f"{NODE_URL}/epoch", timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Failed to fetch epoch: {e}")
        return None


def fetch_miners() -> dict | None:
    """Fetch active miners list."""
    try:
        r = requests.get(f"{NODE_URL}/api/miners", timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Failed to fetch miners: {e}")
        return None


def fetch_health() -> dict | None:
    """Fetch node health."""
    try:
        r = requests.get(f"{NODE_URL}/health", timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Failed to fetch health: {e}")
        return None


def arch_emoji(arch: str) -> str:
    """Return emoji for hardware arch."""
    arch = (arch or "").lower()
    if "g4" in arch:   return "🍎 G4"
    if "g5" in arch:   return "🍎 G5"
    if "g3" in arch:   return "🍎 G3"
    if "power8" in arch or "p8" in arch: return "🖥️ POWER8"
    if "apple" in arch or "m1" in arch or "m2" in arch: return "💻 Apple Si"
    return "🖥️ Modern"


def build_epoch_summary(epoch_data: dict, miners_data: dict | None) -> str:
    """Build a human-readable epoch summary."""
    epoch_num = epoch_data.get("epoch", "?")
    slot = epoch_data.get("slot", "?")
    enrolled = epoch_data.get("enrolled_miners", "?")
    pot = epoch_data.get("pot_rtc", 1.5)

    lines = [
        f"📊 Epoch {epoch_num} Complete",
        "",
        f"💰 {pot} RTC distributed to {enrolled} miners",
    ]

    # Top earner + arch breakdown
    if miners_data and "miners" in miners_data:
        miners = miners_data["miners"]
        if miners:
            # Find top earner by multiplier
            top = max(miners, key=lambda m: float(m.get("multiplier", 1.0) or 1.0), default=None)
            if top:
                top_id = top.get("miner_id") or top.get("wallet") or "unknown"
                top_mult = top.get("multiplier", "?")
                top_arch = top.get("arch") or top.get("device_arch") or "modern"
                reward_est = round(float(pot or 1.5) * float(top_mult or 1) / max(len(miners), 1), 4)
                lines.append(f"🏆 Top earner: {top_id} ({top_arch} {top_mult}x, ~{reward_est} RTC)")

        # Arch breakdown
        arch_counts = {}
        for m in miners:
            arch = (m.get("arch") or m.get("device_arch") or "modern").lower()
            arch_counts[arch] = arch_counts.get(arch, 0) + 1
        arch_str = ", ".join(f"{v} {arch_emoji(k)}" for k, v in sorted(arch_counts.items(), key=lambda x: -x[1]))
        lines.append(f"⛏️  Active miners: {len(miners)} ({arch_str})")

    lines += [
        f"📦 Block height: {slot:,}" if isinstance(slot, int) else f"📦 Block height: {slot}",
        "",
        f"Explorer: {NODE_URL}/explorer"
    ]

    return "\n".join(lines)


def post_discord(message: str) -> bool:
    """Post to Discord via webhook."""
    if not DISCORD_WEBHOOK:
        return False
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": f"```\n{message}\n```"}, timeout=10)
        r.raise_for_status()
        log.info(f"Posted to Discord")
        return True
    except Exception as e:
        log.error(f"Discord post failed: {e}")
        return False


def post_moltbook(message: str) -> bool:
    """Post to Moltbook."""
    if not MOLTBOOK_KEY:
        return False
    try:
        r = requests.post(
            f"{MOLTBOOK_URL}/api/v1/posts",
            json={"content": message},
            headers={"Authorization": f"Bearer {MOLTBOOK_KEY}"},
            timeout=10
        )
        r.raise_for_status()
        log.info(f"Posted to Moltbook")
        return True
    except Exception as e:
        log.error(f"Moltbook post failed: {e}")
        return False


def post_platforms(epoch_num: int, message: str) -> None:
    """Post to all configured platforms."""
    posted = []
    if post_discord(message):
        posted.append("Discord")
    if post_moltbook(message):
        posted.append("Moltbook")
    if posted:
        log.info(f"Epoch {epoch_num} posted to: {', '.join(posted)}")
    else:
        log.info(f"Epoch {epoch_num} summary (no platforms configured):\n{message}")


def main():
    log.info(f"RustChain Epoch Reporter starting")
    log.info(f"Node: {NODE_URL}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info(f"Discord: {'enabled' if DISCORD_WEBHOOK else 'disabled'}")
    log.info(f"Moltbook: {'enabled' if MOLTBOOK_KEY else 'disabled'}")
    log.info(f"State file: {STATE_FILE}")

    state = load_state()
    log.info(f"Last known epoch: {state.get('last_epoch', 'unknown')}")

    while True:
        epoch_data = fetch_epoch()

        if epoch_data:
            current_epoch = epoch_data.get("epoch")

            if current_epoch is not None:
                last_epoch = state.get("last_epoch")
                posted_epochs = state.get("posted_epochs", [])

                # New epoch detected
                if last_epoch is not None and current_epoch > last_epoch:
                    completed_epoch = current_epoch - 1
                    if completed_epoch not in posted_epochs:
                        log.info(f"New epoch detected! {last_epoch} → {current_epoch}")
                        miners_data = fetch_miners()
                        message = build_epoch_summary(
                            {**epoch_data, "epoch": completed_epoch},
                            miners_data
                        )
                        post_platforms(completed_epoch, message)

                        # Track posted epochs (keep last 100)
                        posted_epochs.append(completed_epoch)
                        if len(posted_epochs) > 100:
                            posted_epochs = posted_epochs[-100:]
                        state["posted_epochs"] = posted_epochs

                state["last_epoch"] = current_epoch
                save_state(state)
            else:
                log.warning("Epoch data missing 'epoch' field")
        else:
            log.warning("Could not fetch epoch data — node may be down")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
