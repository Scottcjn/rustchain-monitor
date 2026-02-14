#!/usr/bin/env python3
"""
RustChain Network Monitor
A real-time monitoring tool for RustChain nodes and miners

Features:
- Live epoch tracking
- Miner status monitoring
- Reward calculations
- Hardware multiplier validation
- Network health checks
- Alert system for epoch settlements

Usage:
    python3 rustchain_monitor.py --node https://50.28.86.131
    python3 rustchain_monitor.py --miner your-miner-id --watch
"""

import requests
import time
import argparse
import json
from datetime import datetime
from typing import Dict, List, Optional

class RustChainMonitor:
    def __init__(self, node_url: str = "https://50.28.86.131"):
        self.node_url = node_url.rstrip('/')
        self.session = requests.Session()
        self.session.verify = False  # For self-signed certs
        
    def get_health(self) -> Dict:
        """Check node health"""
        response = self.session.get(f"{self.node_url}/health")
        return response.json()
    
    def get_epoch(self) -> Dict:
        """Get current epoch info"""
        response = self.session.get(f"{self.node_url}/epoch")
        return response.json()
    
    def get_miners(self) -> List[Dict]:
        """Get all active miners"""
        response = self.session.get(f"{self.node_url}/api/miners")
        return response.json()
    
    def get_miner_balance(self, miner_id: str) -> float:
        """Get specific miner's RTC balance"""
        response = self.session.get(f"{self.node_url}/wallet/balance?miner_id={miner_id}")
        return response.json().get("balance_rtc", 0.0)
    
    def calculate_expected_reward(self, device_arch: str) -> float:
        """Calculate expected reward per epoch based on hardware"""
        multipliers = {
            "g4": 2.5,
            "g5": 2.0,
            "g3": 1.8,
            "power8": 1.5,
            "retro": 1.4,
            "apple_silicon": 1.2,
            "modern": 1.0
        }
        
        base_reward = 1.5  # RTC per epoch
        multiplier = multipliers.get(device_arch.lower(), 1.0)
        
        # This is simplified - actual calculation includes all miners
        return base_reward * multiplier
    
    def watch_miner(self, miner_id: str, interval: int = 60):
        """Watch a specific miner's status"""
        print(f"🔍 Watching miner: {miner_id}")
        print(f"Refresh interval: {interval} seconds\n")
        
        last_balance = 0.0
        last_epoch = 0
        
        while True:
            try:
                # Get current state
                epoch_data = self.get_epoch()
                balance = self.get_miner_balance(miner_id)
                miners = self.get_miners()
                
                # Find our miner
                our_miner = None
                for m in miners:
                    if m.get("miner") == miner_id or m.get("miner_id") == miner_id:
                        our_miner = m
                        break
                
                current_epoch = epoch_data.get("current_epoch", 0)
                
                # Clear screen
                print("\033[2J\033[H")
                
                # Display status
                print(f"╔═══════════════════════════════════════════════════════╗")
                print(f"║  RustChain Miner Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ║")
                print(f"╠═══════════════════════════════════════════════════════╣")
                print(f"║  Miner ID: {miner_id[:40]:<40}  ║")
                print(f"║  Balance:  {balance:.6f} RTC{' ' * 30}  ║")
                print(f"║  Epoch:    {current_epoch}{' ' * 42}  ║")
                print(f"╠═══════════════════════════════════════════════════════╣")
                
                if our_miner:
                    arch = our_miner.get("device_arch", "unknown")
                    last_attest = our_miner.get("last_attestation_time", 0)
                    expected = self.calculate_expected_reward(arch)
                    
                    print(f"║  Hardware: {arch:<43}  ║")
                    print(f"║  Expected: ~{expected:.6f} RTC/epoch{' ' * 19}  ║")
                    print(f"║  Status:   {'✅ Active' if time.time() - last_attest < 3600 else '⚠️  Inactive':<43}  ║")
                else:
                    print(f"║  Status:   ⚠️  Not found in active miners{' ' * 13}  ║")
                
                print(f"╚═══════════════════════════════════════════════════════╝")
                
                # Check for new epoch
                if current_epoch > last_epoch and last_epoch > 0:
                    reward = balance - last_balance
                    print(f"\n🎉 NEW EPOCH! Earned: {reward:.6f} RTC")
                
                last_balance = balance
                last_epoch = current_epoch
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\n\n👋 Monitoring stopped")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                time.sleep(interval)
    
    def network_summary(self):
        """Display network summary"""
        health = self.get_health()
        epoch = self.get_epoch()
        miners = self.get_miners()
        
        print("╔════════════════════════════════════════╗")
        print("║      RustChain Network Summary         ║")
        print("╠════════════════════════════════════════╣")
        print(f"║  Node:    {health.get('ok', False) and '✅ Healthy' or '❌ Down'}               ║")
        print(f"║  Epoch:   {epoch.get('current_epoch', 'N/A'):<30} ║")
        print(f"║  Miners:  {len(miners)} active{' ' * 20} ║")
        print("╚════════════════════════════════════════╝\n")
        
        # Group by hardware
        by_arch = {}
        for m in miners:
            arch = m.get("device_arch", "unknown")
            by_arch[arch] = by_arch.get(arch, 0) + 1
        
        print("Hardware Distribution:")
        for arch, count in sorted(by_arch.items(), key=lambda x: -x[1]):
            print(f"  {arch:15} : {count} miners")

def main():
    parser = argparse.ArgumentParser(description="RustChain Network Monitor")
    parser.add_argument("--node", default="https://50.28.86.131", help="Node URL")
    parser.add_argument("--miner", help="Miner ID to watch")
    parser.add_argument("--watch", action="store_true", help="Watch mode (live updates)")
    parser.add_argument("--interval", type=int, default=60, help="Update interval (seconds)")
    
    args = parser.parse_args()
    
    monitor = RustChainMonitor(args.node)
    
    if args.miner and args.watch:
        monitor.watch_miner(args.miner, args.interval)
    elif args.miner:
        balance = monitor.get_miner_balance(args.miner)
        print(f"Miner: {args.miner}")
        print(f"Balance: {balance:.6f} RTC")
    else:
        monitor.network_summary()

if __name__ == "__main__":
    main()
