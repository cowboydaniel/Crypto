# CPUCoin

A CPU-minable cryptocurrency with **physical coin files** stored on your hard drive.

## Start Mining Now

Connect to the official CPUCoin network and start mining in minutes:

```bash
# 1. Clone and install
git clone https://github.com/cowboydaniel/Crypto.git
cd Crypto
pip install -e .

# 2. Create your wallet
cpucoin wallet create mywallet

# 3. Connect to the network and start mining
cpucoin node connect 34.55.10.86:8333
cpucoin mine --wallet mywallet --threads 4
```

**Central Server:** `34.55.10.86:8333`
**Server API:** `http://34.55.10.86:8080/status`

Check the network status anytime:
```bash
curl http://34.55.10.86:8080/status
```

---

## Features

- **CPU-Friendly Mining**: Uses Argon2 (memory-hard) algorithm that favors CPUs over GPUs/ASICs
- **Physical Coin Files**: Each coin is stored as a `.coin` file on your disk - you can see, copy, and transfer them
- **Fast Mining**: Optimized for quick block times (~10 seconds target)
- **Multi-threaded**: Utilize all your CPU cores for maximum hash rate
- **Simple CLI**: Easy-to-use command line interface
- **P2P Networking**: Connect with other nodes to sync the blockchain

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

### 2. Start Mining

```bash
# Mine 5 blocks
cpucoin mine --blocks 5 --wallet mywallet

# Mine continuously
cpucoin mine --wallet mywallet

# Use multiple CPU threads
cpucoin mine --wallet mywallet --threads 4
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

Each mined coin is stored as a physical file in `~/.cpucoin/coins/`. The files contain:

- Unique coin ID
- Value (amount of CPU)
- Owner's public key
- Mining proof (nonce, hash, difficulty)
- Full ownership history

Example coin file structure:
```json
{
  "coin_id": "COIN-a1b2c3d4e5f6...",
  "value": 50.0,
  "owner_pubkey": "04abc123...",
  "created_at": 1703548800,
  "block_height": 42,
  "mining_proof": {
    "nonce": 12345,
    "hash": "0000abc...",
    "difficulty": 4
  },
  "history": [
    {"action": "mint", "timestamp": 1703548800, ...}
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
cpucoin mine [--blocks N] [--wallet NAME] [--threads N]
    Mine blocks and earn coins

cpucoin wallet create <name> [--password PWD]
    Create a new wallet

cpucoin wallet info [name]
    Show wallet information

cpucoin wallet list
    List all wallets

cpucoin wallet balance [name]
    Show wallet balance

cpucoin send <recipient> <amount> [--wallet NAME]
    Send coins to another wallet

cpucoin coins list [--all]
    List coin files (--all includes spent)

cpucoin coins info <coin_id>
    Show detailed coin information

cpucoin coins export <coin_id> <filepath>
    Export a coin to a file

cpucoin coins import <filepath>
    Import a coin from a file

cpucoin blockchain info
    Show blockchain information

cpucoin node start [--port PORT]
    Start a network node

cpucoin node connect <host:port>
    Connect to a peer node
```

## Python API

```python
from cpucoin import Blockchain, Wallet, Miner, Coin

# Create a wallet
wallet = Wallet.create("mywallett")

# Create blockchain
blockchain = Blockchain()

# Mine a block
miner = Miner(wallet, blockchain)
result = miner.mine_block(verbose=True)

# The coin is automatically saved to disk
print(f"Minted coin: {result.coin.filepath}")

# Check balance
print(f"Balance: {wallet.get_balance()} CPU")

# List coins
for coin in wallet.list_coins():
    print(f"{coin.coin_id}: {coin.value} CPU")
```

## Technical Details

### Mining Algorithm

CPUCoin uses **Argon2id** for proof-of-work, which is:

1. **Memory-hard**: Requires 64MB of RAM per hash, making GPU mining inefficient
2. **Time-hard**: Sequential memory access patterns resist parallelization
3. **ASIC-resistant**: Memory requirements make specialized hardware impractical

The mining process:
1. Create a block header with transactions
2. Hash with Argon2id (using previous block hash as salt)
3. Apply SHA-256 for final hash
4. Check if hash meets difficulty target
5. If not, increment nonce and repeat

### Difficulty Adjustment

- Target block time: 10 seconds
- Adjustment interval: Every 10 blocks
- If blocks are too fast: Difficulty increases
- If blocks are too slow: Difficulty decreases

### Block Reward

- Initial reward: 50 CPU per block
- Halving: Every 210,000 blocks (like Bitcoin)

## File Locations

- Wallets: `~/.cpucoin/wallets/`
- Coins: `~/.cpucoin/coins/`
- Blockchain: `~/.cpucoin/blockchain.json`

## License

MIT License
