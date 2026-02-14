# RustChain Network Monitor

**By Sophia Elya** - Real-time monitoring tool for RustChain Proof-of-Antiquity blockchain

A lightweight Python tool for monitoring RustChain nodes, miners, and epoch rewards in real-time.

## Features

✅ **Live Epoch Tracking** - Watch epoch settlements as they happen  
✅ **Miner Status Dashboard** - Monitor your vintage hardware miners  
✅ **Reward Calculator** - Estimate earnings based on hardware multipliers  
✅ **Network Health** - Check node status and active miner count  
✅ **Hardware Distribution** - See which vintage machines are mining  
✅ **Alert System** - Get notified when new epochs settle  

## Quick Start

```bash
# Install dependencies
pip install requests

# Check network summary
python3 rustchain_monitor.py

# Watch your miner (live updates every 60 seconds)
python3 rustchain_monitor.py --miner your-miner-id --watch

# Custom node and update interval
python3 rustchain_monitor.py --node https://custom-node.com --miner your-id --watch --interval 30
```

## Hardware Multipliers

| Hardware | Multiplier | Expected Reward/Epoch |
|----------|------------|----------------------|
| PowerPC G4 | 2.5x | ~2.5x share |
| PowerPC G5 | 2.0x | ~2.0x share |
| PowerPC G3 | 1.8x | ~1.8x share |
| IBM POWER8 | 1.5x | ~1.5x share |
| Vintage x86 | 1.4x | ~1.4x share |
| Apple Silicon | 1.2x | ~1.2x share |
| Modern | 1.0x | 1.0x share |

*Base reward: 1.5 RTC per epoch (~10 minutes)*

## Example Output

```
╔═══════════════════════════════════════════════════════╗
║  RustChain Miner Monitor - 2026-02-13 18:30:00        ║
╠═══════════════════════════════════════════════════════╣
║  Miner ID: dual-g4-125                                ║
║  Balance:  12.450000 RTC                              ║
║  Epoch:    142                                        ║
╠═══════════════════════════════════════════════════════╣
║  Hardware: g4                                         ║
║  Expected: ~0.375000 RTC/epoch                        ║
║  Status:   ✅ Active                                  ║
╚═══════════════════════════════════════════════════════╝

🎉 NEW EPOCH! Earned: 0.382150 RTC
```

## About RustChain

RustChain is a blockchain that rewards vintage hardware miners using Proof-of-Antiquity consensus. Instead of rewarding the fastest hardware (like Bitcoin), we reward the *oldest* genuine hardware.

Hardware fingerprinting prevents VM/emulator fraud, ensuring only real vintage machines earn the antiquity multipliers.

**Learn more**: [rustchain.org](https://rustchain.org)

## API Endpoints Used

- `GET /health` - Node health check
- `GET /epoch` - Current epoch info
- `GET /api/miners` - Active miners list
- `GET /wallet/balance?miner_id=X` - Miner balance

## Contributing

Found a bug? Want to add features? PRs welcome!

Ideas for contributions:
- Grafana dashboard export
- Discord/Telegram notifications
- Historical reward tracking
- Multi-node monitoring
- Export to CSV/JSON

## License

MIT License - Free to use, modify, and distribute

---

**Created by Sophia Elya** | [BoTTube](https://bottube.ai/sophia-elya) | [@RustchainPOA](https://x.com/RustchainPOA)
