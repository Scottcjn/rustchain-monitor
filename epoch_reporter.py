#!/usr/bin/env python3
"""
Epoch Reporter Bot for RustChain
Posts epoch summaries to Discord/Moltbook/X
Bounty: 10-15 RTC
"""

import os
import json
import time
import sqlite3
import requests
from datetime import datetime

# Configuration
RPC_URL = os.getenv("RPC_URL", "https://50.28.86.131")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "")
MOLTBOOK_API_URL = "https://moltbook.com/api/v1/posts"
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")

DB_PATH = "/root/rustchain/rustchain_v2.db"
STATE_FILE = "/tmp/epoch_reporter_state.json"


def load_state():
    """Load last posted epoch from state file."""
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"last_epoch": 0}


def save_state(state):
    """Save state to file."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)


def get_current_epoch():
    """Get current epoch number from RPC."""
    try:
        resp = requests.get(f"{RPC_URL}/epoch", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("epoch", 0)
    except:
        pass
    return 0


def get_epoch_data(epoch_num):
    """Get epoch data from RPC and DB."""
    try:
        # Get epoch info from RPC
        resp = requests.get(f"{RPC_URL}/epoch", timeout=5)
        epoch_data = resp.json() if resp.status_code == 200 else {}
        
        # Get miners from RPC
        miners_resp = requests.get(f"{RPC_URL}/api/miners", timeout=5)
        miners = miners_resp.json() if miners_resp.status_code == 200 else []
        
        # Get rewards from DB if available
        rewards = []
        if os.path.exists(DB_PATH):
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM epoch_rewards WHERE epoch = ?",
                    (epoch_num,)
                )
                rewards = cursor.fetchall()
                conn.close()
            except:
                pass
        
        return {
            "epoch": epoch_num,
            "data": epoch_data,
            "miners": miners,
            "rewards": rewards
        }
    except Exception as e:
        return {"error": str(e)}


def format_epoch_message(epoch_data):
    """Format epoch summary message."""
    epoch = epoch_data.get("epoch", 0)
    data = epoch_data.get("data", {})
    miners = epoch_data.get("miners", [])
    
    # Calculate stats
    active_miners = len(miners)
    total_staked = sum(m.get("stake", 0) for m in miners)
    
    # Find top earner
    top_earner = max(miners, key=lambda m: m.get("earnings", 0)) if miners else {}
    
    message = f"""📊 Epoch {epoch} Complete

💰 {len(epoch_data.get('rewards', []))} validators
🏆 Top: {top_earner.get('name', 'N/A')} ({top_earner.get('earnings', 0):.3f} RTC)
⛏️ Active miners: {active_miners}
📦 Block height: {data.get('block_height', 'N/A')}
💎 Total RTC: {data.get('total_mined', 0)}"""

    return message


def post_to_discord(message):
    """Post message to Discord webhook."""
    if not DISCORD_WEBHOOK:
        return False
    
    try:
        resp = requests.post(
            DISCORD_WEBHOOK,
            json={"content": message},
            timeout=10
        )
        return resp.status_code == 200
    except:
        return False


def post_to_moltbook(message):
    """Post message to Moltbook."""
    if not MOLTBOOK_API_KEY:
        return False
    
    try:
        resp = requests.post(
            MOLTBOOK_API_URL,
            headers={"Authorization": f"Bearer {MOLTBOOK_API_KEY}"},
            json={"content": message},
            timeout=10
        )
        return resp.status_code == 200
    except:
        return False


def post_to_twitter(message):
    """Post message to Twitter/X (placeholder)."""
    # Twitter API requires OAuth, placeholder for now
    return False


def main():
    """Main loop."""
    print("Epoch Reporter Bot started")
    state = load_state()
    last_epoch = state.get("last_epoch", 0)
    
    while True:
        try:
            current_epoch = get_current_epoch()
            
            if current_epoch > last_epoch:
                print(f"New epoch detected: {current_epoch}")
                
                # Get epoch data
                epoch_data = get_epoch_data(current_epoch)
                
                # Format message
                message = format_epoch_message(epoch_data)
                print(message)
                
                # Post to platforms
                posted = False
                if post_to_discord(message):
                    print("Posted to Discord")
                    posted = True
                
                if post_to_moltbook(message):
                    print("Posted to Moltbook")
                    posted = True
                
                if post_to_twitter(message):
                    print("Posted to Twitter")
                    posted = True
                
                if posted:
                    # Save state
                    state["last_epoch"] = current_epoch
                    save_state(state)
                    last_epoch = current_epoch
                    
                    print(f"✅ Epoch {current_epoch} reported!")
            
            time.sleep(60)  # Check every minute
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
