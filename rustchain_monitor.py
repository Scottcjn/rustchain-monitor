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
import sys
from datetime import datetime
from typing import Dict, List, Optional

# ANSI color codes for terminal output
class Colors:
    """ANSI escape codes for colored terminal output"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright foreground colors
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    
    # Background colors
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'


class RustChainMonitor:
    def __init__(self, node_url: str = "https://50.28.86.131", use_color: bool = True):
        self.node_url = node_url.rstrip('/')
        self.session = requests.Session()
        self.session.verify = False  # For self-signed certs
        self.use_color = use_color and sys.stdout.isatty()
    
    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled"""
        if not self.use_color:
            return text
        return f"{color}{text}{Colors.RESET}"
    
    def _status(self, text: str) -> str:
        """Green for good status"""
        return self._colorize(text, Colors.BRIGHT_GREEN)
    
    def _warning(self, text: str) -> str:
        """Yellow for warnings"""
        return self._colorize(text, Colors.BRIGHT_YELLOW)
    
    def _error(self, text: str) -> str:
        """Red for errors"""
        return self._colorize(text, Colors.BRIGHT_RED)
    
    def _info(self, text: str) -> str:
        """Blue for info"""
        return self._colorize(text, Colors.BRIGHT_BLUE)
    
    def _accent(self, text: str) -> str:
        """Cyan for accent/highlight"""
        return self._colorize(text, Colors.BRIGHT_CYAN)
        
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
        print(f"{self._accent('🔍')} Watching miner: {miner_id}")
        print(f"{self._info(f'Refresh interval: {interval} seconds')}\n")
        
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
                
                # Color-coded status
                is_active = False
                if our_miner:
                    last_attest = our_miner.get("last_attestation_time", 0)
                    is_active = time.time() - last_attest < 3600
                
                status_color = Colors.BRIGHT_GREEN if is_active else Colors.BRIGHT_YELLOW
                status_text = "Active" if is_active else "Inactive"
                status_emoji = "🟢" if is_active else "🟡"
                
                # Display status with colors
                print(f"{self._accent('╔' + '═' * 58 + '╗')}")
                print(f"{self._accent('║')}  {self._accent('RustChain Miner Monitor')} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {self._accent('║')}")
                print(f"{self._accent('╠' + '═' * 58 + '╣')}")
                print(f"{self._accent('║')}  Miner ID: {miner_id[:40]:<40}  {self._accent('║')}")
                print(f"{self._accent('║')}  Balance:  {self._status(f'{balance:.6f} RTC'):<48} {self._accent('║')}")
                print(f"{self._accent('║')}  Epoch:    {self._info(str(current_epoch)):<48} {self._accent('║')}")
                print(f"{self._accent('╠' + '═' * 58 + '╣')}")
                
                if our_miner:
                    arch = our_miner.get("device_arch", "unknown")
                    last_attest = our_miner.get("last_attestation_time", 0)
                    expected = self.calculate_expected_reward(arch)
                    
                    print(f"{self._accent('║')}  Hardware: {arch:<48} {self._accent('║')}")
                    print(f"{self._accent('║')}  Expected: ~{expected:.6f} RTC/epoch{' ' * 19} {self._accent('║')}")
                    print(f"{self._accent('║')}  Status:   {self._colorize(f'{status_emoji} {status_text}', status_color):<48} {self._accent('║')}")
                else:
                    print(f"{self._accent('║')}  Status:   {self._warning('⚠️  Not found in active miners'):<48} {self._accent('║')}")
                
                print(f"{self._accent('╚' + '═' * 58 + '╝')}")
                
                # Check for new epoch
                if current_epoch > last_epoch and last_epoch > 0:
                    reward = balance - last_balance
                    print(f"\n{self._status('🎉 NEW EPOCH!')} {self._accent('Earned:')} {self._status(f'{reward:.6f} RTC')}")
                
                last_balance = balance
                last_epoch = current_epoch
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print(f"\n\n{self._info('👋 Monitoring stopped')}")
                break
            except Exception as e:
                print(f"\n{self._error(f'❌ Error: {e}')}")
                time.sleep(interval)
    
    def network_summary(self):
        """Display network summary"""
        health = self.get_health()
        epoch = self.get_epoch()
        miners = self.get_miners()
        
        is_healthy = health.get('ok', False)
        node_status = self._status("✅ Healthy") if is_healthy else self._error("❌ Down")
        
        print(f"{self._accent('╔' + '═' * 44 + '╗')}")
        print(f"{self._accent('║')}      {self._accent('RustChain Network Summary')}         {self._accent('║')}")
        print(f"{self._accent('╠' + '═' * 44 + '╣')}")
        print(f"{self._accent('║')}  Node:    {node_status:<30} {self._accent('║')}")
        print(f"{self._accent('║')}  Epoch:   {self._info(str(epoch.get('current_epoch', 'N/A'))):<30} {self._accent('║')}")
        print(f"{self._accent('║')}  Miners:  {self._status(str(len(miners)))} active{' ' * 17} {self._accent('║')}")
        print(f"{self._accent('╚' + '═' * 44 + '╝')}\n")
        
        # Group by hardware
        by_arch = {}
        for m in miners:
            arch = m.get("device_arch", "unknown")
            by_arch[arch] = by_arch.get(arch, 0) + 1
        
        print(f"{self._accent('Hardware Distribution:')}")
        for arch, count in sorted(by_arch.items(), key=lambda x: -x[1]):
            # Color-code based on multiplier
            multipliers = {"g4": 2.5, "g5": 2.0, "g3": 1.8, "power8": 1.5, "retro": 1.4}
            if arch.lower() in multipliers:
                arch_str = self._colorize(arch, Colors.BRIGHT_GREEN)
            elif arch.lower() == "apple_silicon":
                arch_str = self._colorize(arch, Colors.BRIGHT_CYAN)
            else:
                arch_str = self._colorize(arch, Colors.WHITE)
            print(f"  {arch_str:15} : {self._status(str(count))} miners")

def main():
    parser = argparse.ArgumentParser(description="RustChain Network Monitor")
    parser.add_argument("--node", default="https://50.28.86.131", help="Node URL")
    parser.add_argument("--miner", help="Miner ID to watch")
    parser.add_argument("--watch", action="store_true", help="Watch mode (live updates)")
    parser.add_argument("--interval", type=int, default=60, help="Update interval (seconds)")
    parser.add_argument("--color", dest="color", action="store_true", default=True, help="Enable colored output (default: auto-detect)")
    parser.add_argument("--no-color", dest="color", action="store_false", help="Disable colored output")
    
    args = parser.parse_args()
    
    monitor = RustChainMonitor(args.node, use_color=args.color)
    
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
