"""
CPUCoin Configuration
"""

# Mining Configuration
BLOCK_TIME_TARGET = 10  # Target time between blocks in seconds
DIFFICULTY_ADJUSTMENT_INTERVAL = 10  # Adjust difficulty every N blocks
INITIAL_DIFFICULTY = 2  # Initial number of leading zeros required

# Argon2 Parameters (CPU-friendly, memory-hard)
ARGON2_TIME_COST = 1  # Number of iterations
ARGON2_MEMORY_COST = 65536  # Memory usage in KB (64MB) - makes GPU mining inefficient
ARGON2_PARALLELISM = 4  # Number of parallel threads
ARGON2_HASH_LEN = 32  # Output hash length

# Block Configuration
MAX_TRANSACTIONS_PER_BLOCK = 100
BLOCK_REWARD = 50.0  # Initial block reward
HALVING_INTERVAL = 210000  # Halve reward every N blocks

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
