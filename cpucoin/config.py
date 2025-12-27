"""
CPUCoin Configuration

Block Shares System:
- Each block contains multiple "shares" (coinlets)
- Finding a share is easier than finding a block
- Multiple miners can find different shares in the same block
- Finding the full block closes it and awards remaining shares as bonus
"""

# =============================================================================
# BLOCK SHARES SYSTEM
# =============================================================================

# Number of shares (coinlets) per block
SHARES_PER_BLOCK = 100

# Target time for a FULL BLOCK to be mined (on a powerful 32-thread CPU)
# Individual shares will be found much faster
BLOCK_TIME_TARGET = 900  # 15 minutes for full block

# Share timing targets (in seconds)
# On average, a share should be found every ~9 seconds network-wide
SHARE_TIME_TARGET = 9

# Difficulty adjustment interval (in blocks, not shares)
DIFFICULTY_ADJUSTMENT_INTERVAL = 10

# Initial difficulties (measured in leading zero bits)
# Block difficulty is much harder than share difficulty
INITIAL_SHARE_DIFFICULTY = 4   # Easier - find individual shares
INITIAL_BLOCK_DIFFICULTY = 12  # Much harder - find full block (closes block, bonus shares)

# Difficulty multiplier: block difficulty = share difficulty + this offset
# This ensures finding a full block is much rarer than finding shares
BLOCK_DIFFICULTY_OFFSET = 8

# =============================================================================
# ARGON2 PARAMETERS (CPU-friendly, memory-hard)
# =============================================================================

ARGON2_TIME_COST = 1  # Number of iterations
ARGON2_MEMORY_COST = 65536  # Memory usage in KB (64MB) - makes GPU mining inefficient
ARGON2_PARALLELISM = 4  # Number of parallel threads
ARGON2_HASH_LEN = 32  # Output hash length

# =============================================================================
# BLOCK CONFIGURATION
# =============================================================================

MAX_TRANSACTIONS_PER_BLOCK = 100
BLOCK_REWARD = 50.0  # Total block reward (distributed across shares)
HALVING_INTERVAL = 210000  # Halve reward every N blocks

# Derived values
SHARE_VALUE = BLOCK_REWARD / SHARES_PER_BLOCK  # Value per share (0.5 CPU)

# Block finder bonus: percentage of remaining unclaimed shares
# When someone finds the full block hash, they get this % of unclaimed shares
BLOCK_FINDER_BONUS_PERCENT = 100  # Gets ALL remaining shares

# Transaction Configuration
MIN_TRANSACTION_FEE = 0.001
COINBASE_MATURITY = 100  # Coinbase outputs can be spent after N blocks

# Network Configuration
DEFAULT_PORT = 8333
MAX_PEERS = 50
SYNC_INTERVAL = 5  # Seconds between sync attempts

# Genesis Block Configuration
GENESIS_TIMESTAMP = 1703548800  # Fixed timestamp for reproducibility
GENESIS_MESSAGE = "CPUCoin Genesis Block - Fast CPU Mining!"
