# CPUCoin

A CPU-minable cryptocurrency with **physical coin files** stored on your hard drive.

## Start Mining Now

Connect to the official CPUCoin mining server and start earning shares:

```bash
# 1. Clone and install
git clone https://github.com/cowboydaniel/Crypto.git
cd Crypto
pip install -e .

# 2. Create your wallet
cpucoin wallet create mywallet

# 3. Connect to the mining server and start mining
cpucoin mine --server http://34.41.230.112:8333 --wallet mywallet
```

**Mining Server:** `http://34.41.230.112:8333`

Check server status:
```bash
cpucoin server info http://34.41.230.112:8333
```

---

## Block Shares System

CPUCoin uses a **Block Shares** mining system:

- Each block contains **1000 shares** (coinlets) worth **~2.38095238 CPU each** initially (value halves alongside block reward)
- Multiple miners can earn shares from the same block
- Finding a **full block** (harder difficulty) awards all remaining shares as bonus
- Share difficulty: ~30-50 seconds per share
- Block difficulty: ~15 minutes on a 32-thread CPU

This means you don't have to find an entire block alone - you earn coins for each share you find!

## Features

- **CPU-Friendly Mining**: Uses Argon2 (memory-hard) algorithm that favors CPUs over GPUs/ASICs
- **Physical Coin Files**: Each coin is stored as a `.coin` file on your disk
- **Block Shares**: Earn partial rewards without finding full blocks
- **Multi-User Mining**: Multiple miners work on the same shared blockchain
- **Server-Based**: Central server ensures everyone mines the same chain
- **Simple CLI**: Easy-to-use command line interface

## Installation

```bash
# Clone the repository
git clone https://github.com/cowboydaniel/Crypto.git
cd Crypto

# Install dependencies
pip install -r requirements.txt

# Install CPUCoin
pip install -e .
```

## Quick Start

### 1. Create a Wallet

```bash
cpucoin wallet create mywallet
```

### 2. Start Mining (Server Mode)

```bash
# Mine 5 shares from the official server
cpucoin mine --server http://34.41.230.112:8333 --shares 5 --wallet mywallet

# Mine continuously
cpucoin mine --server http://34.41.230.112:8333 --wallet mywallet
```

### 3. Check Your Coins

```bash
# List your coin files
cpucoin coins list

# Check wallet balance
cpucoin wallet balance mywallet
```

### 4. Send Coins

```bash
cpucoin send <recipient_public_key> 10.0 --wallet mywallet
```

## Coin Files

Each mined share is stored as a physical file in `~/.cpucoin/coins/`. The files contain:

- Unique coin ID
- Value (~2.38095238 CPU per share initially; halves with block reward)
- Owner's public key
- Mining proof (nonce, hash, difficulty)
- Share index and block info
- Full ownership history

Example coin file structure:
```json
{
  "coin_id": "COIN-a1b2c3d4e5f6...",
  "value": 2.38095238,
  "owner_pubkey": "04abc123...",
  "created_at": 1703548800,
  "block_height": 42,
  "share_index": 7,
  "is_block_finder": false,
  "is_bonus_share": false,
  "mining_proof": {
    "nonce": 12345,
    "hash": "0000abc...",
    "share_difficulty": 10,
    "block_difficulty": 17
  },
  "history": [
    {"action": "share_mint", "timestamp": 1703548800, ...}
  ],
  "is_spent": false
}
```

### Export/Import Coins

You can physically transfer coins by copying the files:

```bash
# Export a coin to a USB drive
cpucoin coins export COIN-abc123... /media/usb/my_coin.coin

# Import a coin from someone else
cpucoin coins import /media/usb/received_coin.coin
```

## CLI Commands

```
Mining:
  cpucoin mine [--shares N] [--wallet NAME] [--server URL]
      Mine shares and earn coins
      --server: Connect to mining server (recommended)
      --shares: Number of shares to mine (0 = infinite)

Server:
  cpucoin server start [--port PORT]
      Start a mining server

  cpucoin server info <url>
      Show mining server information

Wallet:
  cpucoin wallet create <name> [--password PWD]
      Create a new wallet

  cpucoin wallet info [name]
      Show wallet information

  cpucoin wallet list
      List all wallets

  cpucoin wallet balance [name]
      Show wallet balance

Transactions:
  cpucoin send <recipient> <amount> [--wallet NAME]
      Send coins to another wallet

Coins:
  cpucoin coins list [--all]
      List coin files (--all includes spent)

  cpucoin coins info <coin_id>
      Show detailed coin information

  cpucoin coins export <coin_id> <filepath>
      Export a coin to a file

  cpucoin coins import <filepath>
      Import a coin from a file

Blockchain:
  cpucoin blockchain info
      Show blockchain information
```

## Technical Details

### Mining Algorithm

CPUCoin uses **Argon2id** for proof-of-work, which is:

1. **Memory-hard**: Requires 64MB of RAM per hash, making GPU mining inefficient
2. **Time-hard**: Sequential memory access patterns resist parallelization
3. **ASIC-resistant**: Memory requirements make specialized hardware impractical

### Difficulty System

- **Share Difficulty**: 10 (easier, ~30-50 sec per share)
- **Block Difficulty**: 17 (harder, ~15 min on 32 threads)
- Adjustment interval: Every 10 blocks
- Block finder gets all remaining unclaimed shares as bonus

### Block Reward

- Total reward: 2380.95238095 CPU per block initially (halves every 210,000 blocks; total supply hard-capped at 1,000,000,000 CPU)
- Distributed as: 1000 shares x ~2.38095238 CPU each initially (share value halves with block reward)

## File Locations

### Miners (your laptop)
- Wallets: `~/.cpucoin/wallets/`
- Coins: `~/.cpucoin/coins/`

### Server
- Blockchain: `~/.cpucoin-server/blockchain.json`

## License

MIT License
