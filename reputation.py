#!/usr/bin/env python3
"""
Agent Reputation Score System for RustChain
On-chain trust and reputation tracking
Bounty: 25-40 RTC
"""

import sqlite3
import time
from datetime import datetime, timedelta

DB_PATH = "/root/rustchain/rustchain_v2.db"

def get_db():
    """Get database connection."""
    return sqlite3.connect(DB_PATH)

def init_reputation_table():
    """Initialize reputation table."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_reputation (
            agent_id TEXT PRIMARY KEY,
            total_transactions INTEGER DEFAULT 0,
            successful_transactions INTEGER DEFAULT 0,
            failed_transactions INTEGER DEFAULT 0,
            total_volume REAL DEFAULT 0,
            uptime_seconds INTEGER DEFAULT 0,
            last_active TIMESTAMP,
            reputation_score REAL DEFAULT 50.0,
            trust_level TEXT DEFAULT 'neutral',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def calculate_reputation(agent_id):
    """Calculate reputation score for an agent."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get agent stats
    cursor.execute("""
        SELECT 
            COALESCE(total_transactions, 0) as total_tx,
            COALESCE(successful_transactions, 0) as success_tx,
            COALESCE(failed_transactions, 0) as failed_tx,
            COALESCE(total_volume, 0) as volume,
            COALESCE(uptime_seconds, 0) as uptime
        FROM agent_reputation 
        WHERE agent_id = ?
    """, (agent_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row or row[0] == 0:
        return 50.0, "neutral"
    
    total_tx, success_tx, failed_tx, volume, uptime = row
    
    # Calculate score
    success_rate = success_tx / total_tx if total_tx > 0 else 0
    
    # Base score from success rate (0-50 points)
    score = success_rate * 50
    
    # Volume bonus (0-25 points)
    volume_bonus = min(25, volume / 1000)
    
    # Uptime bonus (0-25 points) 
    uptime_bonus = min(25, uptime / 86400)  # 1 point per day
    
    total_score = score + volume_bonus + uptime_bonus
    
    # Determine trust level
    if total_score >= 80:
        trust = "trusted"
    elif total_score >= 60:
        trust = "reliable"
    elif total_score >= 40:
        trust = "neutral"
    elif total_score >= 20:
        trust = "unreliable"
    else:
        trust = "untrusted"
    
    return round(total_score, 2), trust

def record_transaction(agent_id, success, volume=0):
    """Record a transaction for an agent."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Upsert agent
    cursor.execute("""
        INSERT INTO agent_reputation (agent_id, total_transactions, successful_transactions, 
            failed_transactions, total_volume, last_active)
        VALUES (?, 1, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(agent_id) DO UPDATE SET
            total_transactions = total_transactions + 1,
            successful_transactions = successful_transactions + ?,
            failed_transactions = failed_transactions + ?,
            total_volume = total_volume + ?,
            last_active = CURRENT_TIMESTAMP
    """, (agent_id, 1 if success else 0, 0 if success else 1, volume,
          1 if success else 0, 0 if success else 1, volume))
    
    conn.commit()
    conn.close()
    
    # Recalculate score
    score, trust = calculate_reputation(agent_id)
    
    # Update score
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE agent_reputation 
        SET reputation_score = ?, trust_level = ?
        WHERE agent_id = ?
    """, (score, trust, agent_id))
    conn.commit()
    conn.close()
    
    return score, trust

def get_top_agents(limit=10):
    """Get top agents by reputation."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT agent_id, reputation_score, trust_level, total_transactions, total_volume
        FROM agent_reputation
        ORDER BY reputation_score DESC
        LIMIT ?
    """, (limit,))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            "agent_id": row[0],
            "score": row[1],
            "trust": row[2],
            "transactions": row[3],
            "volume": row[4]
        })
    
    conn.close()
    return results

if __name__ == "__main__":
    init_reputation_table()
    print("Agent Reputation System initialized")
