"""
Block and Blockchain implementation for CPUCoin

Block Shares System:
- Each block contains multiple "shares" (coinlets)
- Miners find shares by meeting share_difficulty
- Finding the full block (block_difficulty) closes the block
- Block finder gets all remaining unclaimed shares as bonus
"""

import json
import time
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass, field, asdict
from . import config
from .crypto_utils import sha256, merkle_root, mining_hash, check_difficulty


@dataclass
class Block:
    """
    A block in the blockchain.

    Attributes:
        index: Block height in the chain
        timestamp: Unix timestamp of block creation
        transactions: List of transactions in the block
        previous_hash: Hash of the previous block
        nonce: Mining nonce (proof-of-work)
        share_difficulty: Difficulty for finding individual shares
        block_difficulty: Difficulty for finding the full block
        hash: Hash of this block
        miner: Address of the miner who found this block (block finder)
        claimed_shares: Set of share indices that have been claimed
        share_claims: List of share claim records
        is_closed: Whether the block has been closed (full block found)
    """
    index: int
    timestamp: float
    transactions: List[Dict[str, Any]]
    previous_hash: str
    nonce: int = 0
    share_difficulty: int = config.INITIAL_SHARE_DIFFICULTY
    block_difficulty: int = config.INITIAL_BLOCK_DIFFICULTY
    hash: str = ""
    miner: str = ""  # The block finder (if any)
    merkle_root: str = ""

    # Block shares system
    claimed_shares: List[int] = field(default_factory=list)  # Indices of claimed shares
    share_claims: List[Dict[str, Any]] = field(default_factory=list)  # Claim records
    is_closed: bool = False  # True when full block found
    block_finder_hash: str = ""  # Hash that closed the block
    opened_at: float = 0.0  # When the block was opened for mining

    # Legacy compatibility
    @property
    def difficulty(self) -> int:
        """Legacy compatibility - returns share difficulty."""
        return self.share_difficulty

    @difficulty.setter
    def difficulty(self, value: int):
        """Legacy compatibility - sets share difficulty."""
        self.share_difficulty = value

    def __post_init__(self):
        """Calculate merkle root if not set."""
        if not self.merkle_root and self.transactions:
            tx_hashes = [tx.get('txid', sha256(json.dumps(tx, sort_keys=True)))
                        for tx in self.transactions]
            self.merkle_root = merkle_root(tx_hashes)
        if not self.opened_at:
            self.opened_at = time.time()

    def compute_header(self) -> str:
        """Compute the block header for hashing."""
        header_data = {
            'index': self.index,
            'timestamp': self.timestamp,
            'merkle_root': self.merkle_root,
            'previous_hash': self.previous_hash,
            'share_difficulty': self.share_difficulty,
            'block_difficulty': self.block_difficulty,
            'miner': self.miner
        }
        return json.dumps(header_data, sort_keys=True)

    def compute_hash(self) -> str:
        """Compute the hash of this block using CPU-friendly algorithm."""
        header = self.compute_header()
        return mining_hash(header, self.nonce, self.previous_hash)

    def get_unclaimed_shares(self) -> List[int]:
        """Get list of share indices that haven't been claimed yet."""
        claimed_set = set(self.claimed_shares)
        return [i for i in range(config.SHARES_PER_BLOCK) if i not in claimed_set]

    def get_next_share_index(self) -> Optional[int]:
        """Get the next available share index, or None if all claimed."""
        unclaimed = self.get_unclaimed_shares()
        return unclaimed[0] if unclaimed else None

    def claim_share(self, share_index: int, miner: str, nonce: int, hash_value: str) -> bool:
        """
        Claim a share slot in this block.

        Args:
            share_index: The share slot to claim (0-99)
            miner: Public key of the miner claiming the share
            nonce: The nonce that produced the valid hash
            hash_value: The hash that met share difficulty

        Returns:
            True if share was claimed successfully
        """
        if share_index in self.claimed_shares:
            return False  # Already claimed

        if share_index < 0 or share_index >= config.SHARES_PER_BLOCK:
            return False  # Invalid index

        self.claimed_shares.append(share_index)
        self.share_claims.append({
            'share_index': share_index,
            'miner': miner,
            'nonce': nonce,
            'hash': hash_value,
            'timestamp': time.time()
        })
        return True

    def close_block(self, miner: str, nonce: int, hash_value: str):
        """
        Close this block (full block was found).

        Args:
            miner: Public key of the miner who found the block
            nonce: The winning nonce
            hash_value: The hash that met block difficulty
        """
        self.is_closed = True
        self.miner = miner
        self.nonce = nonce
        self.hash = hash_value
        self.block_finder_hash = hash_value

    def shares_remaining(self) -> int:
        """Get number of unclaimed shares."""
        return config.SHARES_PER_BLOCK - len(self.claimed_shares)

    def is_fully_claimed(self) -> bool:
        """Check if all shares have been claimed."""
        return len(self.claimed_shares) >= config.SHARES_PER_BLOCK

    def mine(self, verbose: bool = False) -> bool:
        """
        Mine this block by finding a valid nonce (legacy single-block mining).

        Args:
            verbose: Print mining progress

        Returns:
            True when block is successfully mined
        """
        start_time = time.time()
        attempts = 0

        while True:
            self.hash = self.compute_hash()
            attempts += 1

            if check_difficulty(self.hash, self.share_difficulty):
                elapsed = time.time() - start_time
                if verbose:
                    print(f"\n✓ Block mined!")
                    print(f"  Nonce: {self.nonce}")
                    print(f"  Hash: {self.hash}")
                    print(f"  Attempts: {attempts}")
                    print(f"  Time: {elapsed:.2f}s")
                    print(f"  Hash rate: {attempts/elapsed:.2f} H/s")
                return True

            self.nonce += 1

            if verbose and attempts % 100 == 0:
                elapsed = time.time() - start_time
                print(f"\rMining... Attempts: {attempts}, "
                      f"Rate: {attempts/elapsed:.2f} H/s, "
                      f"Nonce: {self.nonce}", end="", flush=True)

    def is_valid(self) -> bool:
        """Validate this block's proof-of-work."""
        computed_hash = self.compute_hash()
        # For closed blocks, check block difficulty; otherwise share difficulty
        if self.is_closed:
            return (computed_hash == self.hash and
                    check_difficulty(self.hash, self.block_difficulty))
        else:
            return (computed_hash == self.hash and
                    check_difficulty(self.hash, self.share_difficulty))

    def to_dict(self) -> Dict[str, Any]:
        """Convert block to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Block':
        """Create a Block from dictionary."""
        return cls(**data)

    def __repr__(self) -> str:
        return (f"Block(index={self.index}, hash={self.hash[:16]}..., "
                f"txs={len(self.transactions)}, nonce={self.nonce})")


class Blockchain:
    """
    The blockchain - a linked list of blocks.

    Features:
    - Genesis block creation
    - Block validation
    - Difficulty adjustment (separate for shares and blocks)
    - Chain validation and replacement
    - Block shares system with open block tracking
    """

    def __init__(self):
        self.chain: List[Block] = []
        self.pending_transactions: List[Dict[str, Any]] = []
        self.share_difficulty = config.INITIAL_SHARE_DIFFICULTY
        self.block_difficulty = config.INITIAL_BLOCK_DIFFICULTY
        self.current_open_block: Optional[Block] = None  # Block accepting shares
        self._create_genesis_block()

    # Legacy compatibility
    @property
    def difficulty(self) -> int:
        return self.share_difficulty

    @difficulty.setter
    def difficulty(self, value: int):
        self.share_difficulty = value

    def _create_genesis_block(self) -> Block:
        """Create the genesis (first) block."""
        genesis_tx = {
            'txid': sha256(config.GENESIS_MESSAGE),
            'type': 'coinbase',
            'inputs': [],
            'outputs': [{'address': 'genesis', 'amount': 0}],
            'message': config.GENESIS_MESSAGE,
            'timestamp': config.GENESIS_TIMESTAMP
        }

        genesis = Block(
            index=0,
            timestamp=config.GENESIS_TIMESTAMP,
            transactions=[genesis_tx],
            previous_hash="0" * 64,
            share_difficulty=config.INITIAL_SHARE_DIFFICULTY,
            block_difficulty=config.INITIAL_BLOCK_DIFFICULTY,
            miner="genesis",
            is_closed=True  # Genesis is always closed
        )

        # Genesis block has a fixed nonce for reproducibility
        genesis.nonce = 0
        genesis.hash = genesis.compute_hash()

        self.chain.append(genesis)
        return genesis

    @property
    def last_block(self) -> Block:
        """Get the last block in the chain."""
        return self.chain[-1]

    @property
    def height(self) -> int:
        """Get the current blockchain height."""
        return len(self.chain) - 1

    def get_block_reward(self, height: Optional[int] = None) -> float:
        """
        Calculate block reward with halving.

        Reward halves every HALVING_INTERVAL blocks.
        """
        if height is None:
            height = self.height + 1

        halvings = height // config.HALVING_INTERVAL
        reward = config.BLOCK_REWARD / (2 ** halvings)
        return reward

    def calculate_difficulty(self) -> tuple:
        """
        Calculate the next difficulties based on recent block times.

        Returns:
            Tuple of (share_difficulty, block_difficulty)
        """
        if len(self.chain) < config.DIFFICULTY_ADJUSTMENT_INTERVAL + 1:
            return (self.share_difficulty, self.block_difficulty)

        # Get the last N blocks
        interval = config.DIFFICULTY_ADJUSTMENT_INTERVAL
        last_blocks = self.chain[-interval:]

        # Calculate actual time taken for full blocks
        actual_time = last_blocks[-1].timestamp - last_blocks[0].timestamp
        expected_time = config.BLOCK_TIME_TARGET * interval

        # Adjust share difficulty based on block timing
        if actual_time < expected_time / 2:
            # Blocks too fast, increase difficulty
            new_share_difficulty = self.share_difficulty + 1
        elif actual_time > expected_time * 2:
            # Blocks too slow, decrease difficulty
            new_share_difficulty = max(1, self.share_difficulty - 1)
        else:
            new_share_difficulty = self.share_difficulty

        # Block difficulty is always offset from share difficulty
        new_block_difficulty = new_share_difficulty + config.BLOCK_DIFFICULTY_OFFSET

        return (new_share_difficulty, new_block_difficulty)

    def get_share_value(self, height: Optional[int] = None) -> float:
        """
        Get the value of a single share at the given block height.

        Args:
            height: Block height (uses next block if not specified)

        Returns:
            Value of one share in CPU
        """
        block_reward = self.get_block_reward(height)
        return block_reward / config.SHARES_PER_BLOCK

    def add_transaction(self, transaction: Dict[str, Any]) -> bool:
        """
        Add a transaction to the pending pool.

        Args:
            transaction: Transaction dictionary

        Returns:
            True if transaction was added
        """
        # Basic validation
        if not transaction.get('txid'):
            return False

        # Check for duplicates
        for tx in self.pending_transactions:
            if tx['txid'] == transaction['txid']:
                return False

        self.pending_transactions.append(transaction)
        return True

    def create_block(self, miner_address: str = "") -> Block:
        """
        Create a new block with pending transactions.

        Args:
            miner_address: Address to receive mining reward (for block finder)

        Returns:
            New open block ready for share mining
        """
        # Adjust difficulties
        self.share_difficulty, self.block_difficulty = self.calculate_difficulty()

        # Create coinbase transaction (total block reward - will be distributed as shares)
        reward = self.get_block_reward()
        fees = sum(tx.get('fee', 0) for tx in self.pending_transactions)

        coinbase = {
            'txid': sha256(f"coinbase-{self.height + 1}-{time.time()}"),
            'type': 'coinbase',
            'inputs': [],
            'outputs': [{'address': 'shares', 'amount': reward + fees}],
            'timestamp': time.time(),
            'note': f'Block reward distributed as {config.SHARES_PER_BLOCK} shares'
        }

        # Select transactions for block
        transactions = [coinbase] + self.pending_transactions[:config.MAX_TRANSACTIONS_PER_BLOCK - 1]

        block = Block(
            index=self.height + 1,
            timestamp=time.time(),
            transactions=transactions,
            previous_hash=self.last_block.hash,
            share_difficulty=self.share_difficulty,
            block_difficulty=self.block_difficulty,
            miner=miner_address,
            opened_at=time.time()
        )

        return block

    def get_or_create_open_block(self) -> Block:
        """
        Get the current open block or create a new one.

        Returns:
            The current open block accepting shares
        """
        if self.current_open_block is None or self.current_open_block.is_closed:
            self.current_open_block = self.create_block()
        return self.current_open_block

    def close_current_block(self, miner: str, nonce: int, hash_value: str) -> Block:
        """
        Close the current block (full block found).

        Args:
            miner: Address of block finder
            nonce: Winning nonce
            hash_value: Hash that met block difficulty

        Returns:
            The closed block
        """
        if self.current_open_block is None:
            self.current_open_block = self.create_block()

        self.current_open_block.close_block(miner, nonce, hash_value)
        closed_block = self.current_open_block

        # Add to chain
        self.add_block(closed_block)

        # Create new open block
        self.current_open_block = None

        return closed_block

    def add_block(self, block: Block) -> bool:
        """
        Add a mined block to the chain.

        Args:
            block: The mined block to add

        Returns:
            True if block was added successfully
        """
        # Validate block
        if not self.validate_block(block):
            return False

        # Remove included transactions from pending pool
        included_txids = {tx['txid'] for tx in block.transactions}
        self.pending_transactions = [
            tx for tx in self.pending_transactions
            if tx['txid'] not in included_txids
        ]

        self.chain.append(block)
        return True

    def validate_block(self, block: Block, previous_block: Optional[Block] = None) -> bool:
        """
        Validate a block.

        Args:
            block: Block to validate
            previous_block: Previous block (uses last block if not provided)

        Returns:
            True if block is valid
        """
        if previous_block is None:
            previous_block = self.last_block

        # Check index
        if block.index != previous_block.index + 1:
            return False

        # Check previous hash
        if block.previous_hash != previous_block.hash:
            return False

        # Check proof-of-work
        if not block.is_valid():
            return False

        # Check timestamp (not too far in future)
        if block.timestamp > time.time() + 7200:  # 2 hour tolerance
            return False

        return True

    def validate_chain(self) -> bool:
        """Validate the entire blockchain."""
        for i in range(1, len(self.chain)):
            if not self.validate_block(self.chain[i], self.chain[i - 1]):
                return False
        return True

    def replace_chain(self, new_chain: List[Block]) -> bool:
        """
        Replace chain with a longer valid chain (consensus).

        Args:
            new_chain: The new chain to potentially adopt

        Returns:
            True if chain was replaced
        """
        if len(new_chain) <= len(self.chain):
            return False

        # Validate new chain
        temp_blockchain = Blockchain.__new__(Blockchain)
        temp_blockchain.chain = new_chain
        temp_blockchain.difficulty = config.INITIAL_DIFFICULTY

        if not temp_blockchain.validate_chain():
            return False

        self.chain = new_chain
        self.difficulty = self.calculate_difficulty()
        return True

    def get_balance(self, address: str) -> float:
        """
        Calculate the balance of an address.

        Args:
            address: The address to check

        Returns:
            Balance amount
        """
        balance = 0.0
        spent_outputs = set()

        # First pass: collect spent outputs
        for block in self.chain:
            for tx in block.transactions:
                for inp in tx.get('inputs', []):
                    spent_outputs.add((inp.get('txid'), inp.get('vout', 0)))

        # Second pass: sum unspent outputs
        for block in self.chain:
            for tx in block.transactions:
                for i, out in enumerate(tx.get('outputs', [])):
                    if out.get('address') == address:
                        if (tx['txid'], i) not in spent_outputs:
                            balance += out.get('amount', 0)

        return balance

    def get_utxos(self, address: str) -> List[Dict[str, Any]]:
        """
        Get unspent transaction outputs for an address.

        Args:
            address: The address to check

        Returns:
            List of UTXOs
        """
        utxos = []
        spent_outputs = set()

        # Collect spent outputs
        for block in self.chain:
            for tx in block.transactions:
                for inp in tx.get('inputs', []):
                    spent_outputs.add((inp.get('txid'), inp.get('vout', 0)))

        # Collect unspent outputs
        for block in self.chain:
            for tx in block.transactions:
                for i, out in enumerate(tx.get('outputs', [])):
                    if out.get('address') == address:
                        if (tx['txid'], i) not in spent_outputs:
                            utxos.append({
                                'txid': tx['txid'],
                                'vout': i,
                                'amount': out.get('amount', 0),
                                'address': address
                            })

        return utxos

    def to_dict(self) -> Dict[str, Any]:
        """Convert blockchain to dictionary."""
        return {
            'chain': [block.to_dict() for block in self.chain],
            'share_difficulty': self.share_difficulty,
            'block_difficulty': self.block_difficulty,
            'pending_transactions': self.pending_transactions,
            'current_open_block': self.current_open_block.to_dict() if self.current_open_block else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Blockchain':
        """Create a Blockchain from dictionary."""
        blockchain = cls.__new__(cls)
        blockchain.chain = [Block.from_dict(b) for b in data['chain']]
        blockchain.share_difficulty = data.get('share_difficulty', config.INITIAL_SHARE_DIFFICULTY)
        blockchain.block_difficulty = data.get('block_difficulty', config.INITIAL_BLOCK_DIFFICULTY)
        blockchain.pending_transactions = data.get('pending_transactions', [])

        # Load current open block if present
        if data.get('current_open_block'):
            blockchain.current_open_block = Block.from_dict(data['current_open_block'])
        else:
            blockchain.current_open_block = None

        return blockchain

    def save(self, filepath: str):
        """Save blockchain to file."""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath: str) -> 'Blockchain':
        """Load blockchain from file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)

    def __len__(self) -> int:
        return len(self.chain)

    def __repr__(self) -> str:
        open_shares = 0
        if self.current_open_block:
            open_shares = self.current_open_block.shares_remaining()
        return (f"Blockchain(height={self.height}, "
                f"share_diff={self.share_difficulty}, "
                f"block_diff={self.block_difficulty}, "
                f"open_shares={open_shares})")
