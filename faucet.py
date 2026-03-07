#!/usr/bin/env python3
"""
RustChain Testnet Faucet
Gives free test RTC to developers
Bounty: 10-15 RTC
"""

import os
import sqlite3
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

DB_PATH = "/tmp/faucet.db"
FAUCET_WALLET = os.getenv("FAUCET_WALLET", "")
RPC_URL = os.getenv("RPC_URL", "https://50.28.86.131")

# Rate limits
LIMITS = {
    "no_auth": 0.5,      # RTC per 24h
    "github": 1.0,
    "github_old": 2.0
}

def init_db():
    """Initialize faucet database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS faucet_logs (
            id INTEGER PRIMARY KEY,
            wallet TEXT,
            ip_address TEXT,
            github_user TEXT,
            amount REAL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_rate_limit(ip, github_user):
    """Get rate limit for user."""
    if github_user:
        # Check GitHub account age (simplified - always assume new)
        return LIMITS["github"]
    return LIMITS["no_auth"]

def can_drip(wallet, ip, github_user):
    """Check if user can request drip."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Check last 24 hours
    since = (datetime.now() - timedelta(hours=24)).isoformat()
    
    c.execute("""
        SELECT SUM(amount) FROM faucet_logs 
        WHERE wallet = ? OR ip_address = ?
        AND timestamp > ?
    """, (wallet, ip, since))
    
    result = c.fetchone()[0] or 0
    conn.close()
    
    limit = get_rate_limit(ip, github_user)
    return result < limit, limit - result

def record_drip(wallet, ip, github_user, amount):
    """Record a drip request."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO faucet_logs (wallet, ip_address, github_user, amount)
        VALUES (?, ?, ?, ?)
    """, (wallet, ip, github_user, amount))
    conn.commit()
    conn.close()

@app.route("/faucet")
def index():
    """Faucet web page."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>RustChain Testnet Faucet</title>
        <style>
            body { font-family: system-ui; max-width: 500px; margin: 50px auto; padding: 20px; }
            input, button { width: 100%; padding: 10px; margin: 10px 0; }
            button { background: #0066ff; color: white; border: none; cursor: pointer; }
            .result { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .success { background: #d4edda; }
            .error { background: #f8d7da; }
        </style>
    </head>
    <body>
        <h1>💧 RustChain Testnet Faucet</h1>
        <form method="POST" action="/faucet/drip">
            <input type="text" name="wallet" placeholder="Your RTC wallet address" required>
            <input type="text" name="github" placeholder="GitHub username (optional)">
            <button type="submit">Get Test RTC</button>
        </form>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/faucet/drip", methods=["POST"])
def drip():
    """Process drip request."""
    wallet = request.form.get("wallet", "").strip()
    github = request.form.get("github", "").strip()
    ip = request.remote_addr
    
    if not wallet:
        return jsonify({"ok": False, "error": "Wallet address required"}), 400
    
    # Check rate limit
    can_request, remaining = can_drip(wallet, ip, github)
    
    if not can_request:
        return jsonify({
            "ok": False,
            "error": "Rate limit exceeded",
            "next_available": "24 hours"
        }), 429
    
    # Record and send (simplified - would need actual RPC call)
    amount = 1.0 if github else 0.5
    record_drip(wallet, ip, github, amount)
    
    return jsonify({
        "ok": True,
        "amount": amount,
        "wallet": wallet,
        "remaining": remaining - amount
    })

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8090)
