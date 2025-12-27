# CPUCoin Mining Server - Admin Guide

This document explains how to run and manage the CPUCoin mining server.

## Quick Start

```bash
cd /path/to/Crypto

# Start the server
python -c "from cpucoin.cli import main; main()" server start --port 8335
```

The server will:
- Listen on `0.0.0.0:8335` by default
- Store blockchain in `~/.cpucoin-server/blockchain.json`
- Accept share submissions from miners

## Server Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Server info and status |
| `/block/current` | GET | Current block template for mining |
| `/blockchain/info` | GET | Full blockchain information |
| `/blockchain/height` | GET | Just the blockchain height |
| `/share/submit` | POST | Submit a found share |
| `/blockchain/reset` | POST | Reset blockchain (testing only) |

## API Examples

### Get Server Info
```bash
curl http://localhost:8335/
```

Response:
```json
{
  "name": "CPUCoin Mining Server",
  "version": "2.0.0",
  "blockchain_height": 42,
  "share_difficulty": 10,
  "block_difficulty": 17,
  "shares_per_block": 100,
  "share_value": 0.5
}
```

### Get Current Block
```bash
curl http://localhost:8335/block/current
```

Response:
```json
{
  "block_index": 43,
  "previous_hash": "0000abc...",
  "share_difficulty": 10,
  "block_difficulty": 17,
  "shares_claimed": 7,
  "shares_remaining": 93,
  "is_closed": false,
  "header": "{...}"
}
```

### Submit a Share
```bash
curl -X POST http://localhost:8335/share/submit \
  -H "Content-Type: application/json" \
  -d '{
    "miner_pubkey": "04abc123...",
    "nonce": 12345,
    "hash": "0000def...",
    "block_index": 43
  }'
```

Response (success):
```json
{
  "success": true,
  "message": "Share accepted",
  "share_index": 7,
  "is_block_find": false,
  "bonus_shares": 0,
  "coin_data": {
    "value": 0.5,
    "block_height": 43,
    "share_index": 7,
    ...
  }
}
```

Response (block found!):
```json
{
  "success": true,
  "message": "Share accepted - BLOCK FOUND!",
  "share_index": 8,
  "is_block_find": true,
  "bonus_shares": 91,
  "coin_data": {...}
}
```

## Running in Production

### Using systemd

Create `/etc/systemd/system/cpucoin-server.service`:

```ini
[Unit]
Description=CPUCoin Mining Server
After=network.target

[Service]
Type=simple
User=cpucoin
WorkingDirectory=/opt/cpucoin
ExecStart=/usr/bin/python -c "from cpucoin.cli import main; main()" server start --port 8335
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable cpucoin-server
sudo systemctl start cpucoin-server
sudo systemctl status cpucoin-server
```

### Using screen/tmux

```bash
screen -S cpucoin-server
python -c "from cpucoin.cli import main; main()" server start --port 8335
# Press Ctrl+A, D to detach
```

### Docker (example)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .
EXPOSE 8335
CMD ["python", "-c", "from cpucoin.cli import main; main()", "server", "start", "--port", "8335"]
```

## Configuration

Edit `cpucoin/config.py` to adjust:

```python
# Block shares system
SHARES_PER_BLOCK = 100          # Shares per block
BLOCK_TIME_TARGET = 900         # 15 minutes for full block

# Difficulty
INITIAL_SHARE_DIFFICULTY = 10   # ~30-50 sec per share
INITIAL_BLOCK_DIFFICULTY = 17   # ~15 min on 32 threads
BLOCK_DIFFICULTY_OFFSET = 7     # block_diff = share_diff + offset

# Rewards
BLOCK_REWARD = 50.0             # Total CPU per block
SHARE_VALUE = 0.5               # CPU per share (50/100)
```

## Data Storage

Server data is stored in `~/.cpucoin-server/`:

```
~/.cpucoin-server/
└── blockchain.json     # The canonical blockchain
```

## Monitoring

Check server status:
```bash
curl http://localhost:8335/blockchain/info | jq
```

Watch for new shares:
```bash
watch -n 1 'curl -s http://localhost:8335/blockchain/info | jq .current_open_block'
```

## Reset Blockchain

For testing, you can reset the entire blockchain:

```bash
# Via API
curl -X POST http://localhost:8335/blockchain/reset

# Or delete the file
rm ~/.cpucoin-server/blockchain.json
```

## Security Notes

1. The server has no authentication - anyone can submit shares
2. Run behind a reverse proxy (nginx) for rate limiting
3. Consider firewall rules to limit access
4. The `/blockchain/reset` endpoint should be disabled in production

## Troubleshooting

### Port already in use
```bash
lsof -i :8335
kill <pid>
```

### Miners can't connect
- Check firewall: `sudo ufw allow 8335`
- Check server is listening: `netstat -tlnp | grep 8335`
- Test locally: `curl http://localhost:8335/`

### Blockchain corruption
```bash
# Backup and reset
cp ~/.cpucoin-server/blockchain.json ~/.cpucoin-server/blockchain.json.bak
rm ~/.cpucoin-server/blockchain.json
# Restart server
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MINING SERVER                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  ~/.cpucoin-server/blockchain.json                  │   │
│  │  - Canonical blockchain                              │   │
│  │  - Current open block                                │   │
│  │  - Share claims                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                     HTTP API                                │
│                          │                                  │
└──────────────────────────┼──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
   ┌─────────┐       ┌─────────┐       ┌─────────┐
   │ Miner 1 │       │ Miner 2 │       │ Miner 3 │
   │         │       │         │       │         │
   │ wallet/ │       │ wallet/ │       │ wallet/ │
   │ coins/  │       │ coins/  │       │ coins/  │
   └─────────┘       └─────────┘       └─────────┘

   ~/.cpucoin/        ~/.cpucoin/        ~/.cpucoin/
   (local only)       (local only)       (local only)
```

Each miner:
1. Gets block template from server
2. Mines locally (CPU work)
3. Submits valid shares to server
4. Creates local coin files for accepted shares
