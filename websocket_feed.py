#!/usr/bin/env python3
"""
WebSocket Real-Time Feed for RustChain
Bounty: 25-40 RTC
"""

import asyncio
import json
import requests
import websockets
from datetime import datetime

RPC_URL = "https://50.28.86.131"
WS_PORT = 8765

async def fetch_block_data():
    """Fetch latest block data from RPC."""
    try:
        # Get current epoch
        epoch_resp = requests.get(f"{RPC_URL}/epoch", timeout=5)
        epoch_data = epoch_resp.json() if epoch_resp.status_code == 200 else {}
        
        # Get miners
        miners_resp = requests.get(f"{RPC_URL}/api/miners", timeout=5)
        miners = miners_resp.json() if miners_resp.status_code == 200 else []
        
        # Get recent blocks
        try:
            import sqlite3
            conn = sqlite3.connect("/root/rustchain/rustchain_v2.db")
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM headers ORDER BY height DESC LIMIT 10")
            blocks = cursor.fetchall()
            conn.close()
        except:
            blocks = []
        
        return {
            "epoch": epoch_data.get("epoch", 0),
            "miners": len(miners),
            "total_staked": sum(m.get("stake", 0) for m in miners),
            "blocks": len(blocks),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

async def handle_client(websocket, path):
    """Handle WebSocket client connection."""
    try:
        await websocket.send(json.dumps({
            "type": "connected",
            "message": "Connected to RustChain Real-Time Feed"
        }))
        
        while True:
            data = await fetch_block_data()
            await websocket.send(json.dumps(data))
            await asyncio.sleep(5)  # Update every 5 seconds
    except websockets.exceptions.ConnectionClosed:
        pass

async def main():
    """Start WebSocket server."""
    print(f"Starting WebSocket server on port {WS_PORT}")
    async with websockets.serve(handle_client, "0.0.0.0", WS_PORT):
        print(f"WebSocket server running on ws://0.0.0.0:{WS_PORT}")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        import websockets
        asyncio.run(main())
    except ImportError:
        print("Install websockets: pip install websockets")
