"""
Block and Blockchain implementation for CPUCoin
"""

import json
import time
from typing import List, Optional, Dict, Any
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
        difficulty: Difficulty level for this block
        hash: Hash of this block
        miner: Address of the miner who found this block
    """
    index: int
    timestamp: float
    transactions: List[Dict[str, Any]]
    previous_hash: str
    nonce: int = 0
    difficulty: int = config.INITIAL_DIFFICULTY
    hash: str = ""
    miner: str = ""
    merkle_root: str = ""

    def __post_init__(self):
        """Calculate merkle root if not set."""
        if not self.merkle_root and self.transactions:
            tx_hashes = [tx.get('txid', sha256(json.dumps(tx, sort_keys=True)))
                        for tx in self.transactions]
            self.merkle_root = merkle_root(tx_hashes)

    def compute_header(self) -> str:
        """Compute the block header for hashing."""
        header_data = {
            'index': self.index,
            'timestamp': self.timestamp,
            'merkle_root': self.merkle_root,
            'previous_hash': self.previous_hash,
            'difficulty': self.difficulty,
            'miner': self.miner
        }
        return json.dumps(header_data, sort_keys=True)

    def compute_hash(self) -> str:
        """Compute the hash of this block using CPU-friendly algorithm."""
        header = self.compute_header()
        return mining_hash(header, self.nonce, self.previous_hash)

    def mine(self, verbose: bool = False) -> bool:
        """
        Mine this block by finding a valid nonce.

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

            if check_difficulty(self.hash, self.difficulty):
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
        return (computed_hash == self.hash and
                check_difficulty(self.hash, self.difficulty))

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
    - Difficulty adjustment
    - Chain validation and replacement
    """

    def __init__(self):
        self.chain: List[Block] = []
        self.pending_transactions: List[Dict[str, Any]] = []
        self.difficulty = config.INITIAL_DIFFICULTY
        self._create_genesis_block()

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
            difficulty=config.INITIAL_DIFFICULTY,
            miner="genesis"
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

    def calculate_difficulty(self) -> int:
        """
        Calculate the next difficulty based on recent block times.

        Adjusts difficulty to maintain target block time by comparing
        actual vs expected time for recent blocks.
        """
        if len(self.chain) < config.DIFFICULTY_ADJUSTMENT_INTERVAL + 1:
            return self.difficulty

        # Get the last N blocks
        interval = config.DIFFICULTY_ADJUSTMENT_INTERVAL
        last_blocks = self.chain[-interval:]

        # Calculate actual time taken
        actual_time = last_blocks[-1].timestamp - last_blocks[0].timestamp
        expected_time = config.BLOCK_TIME_TARGET * interval

        # Adjust difficulty
        if actual_time < expected_time / 2:
            # Blocks too fast, increase difficulty
            new_difficulty = self.difficulty + 1
        elif actual_time > expected_time * 2:
            # Blocks too slow, decrease difficulty
            new_difficulty = max(1, self.difficulty - 1)
        else:
            new_difficulty = self.difficulty

        return new_difficulty

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

    def create_block(self, miner_address: str) -> Block:
        """
        Create a new block with pending transactions.

        Args:
            miner_address: Address to receive mining reward

        Returns:
            New unmined block
        """
        # Adjust difficulty
        self.difficulty = self.calculate_difficulty()

        # Create coinbase transaction (mining reward)
        reward = self.get_block_reward()
        fees = sum(tx.get('fee', 0) for tx in self.pending_transactions)

        coinbase = {
            'txid': sha256(f"coinbase-{self.height + 1}-{miner_address}-{time.time()}"),
            'type': 'coinbase',
            'inputs': [],
            'outputs': [{'address': miner_address, 'amount': reward + fees}],
            'timestamp': time.time()
        }

        # Select transactions for block
        transactions = [coinbase] + self.pending_transactions[:config.MAX_TRANSACTIONS_PER_BLOCK - 1]

        block = Block(
            index=self.height + 1,
            timestamp=time.time(),
            transactions=transactions,
            previous_hash=self.last_block.hash,
            difficulty=self.difficulty,
            miner=miner_address
        )

        return block

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
            'difficulty': self.difficulty,
            'pending_transactions': self.pending_transactions
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Blockchain':
        """Create a Blockchain from dictionary."""
        blockchain = cls.__new__(cls)
        blockchain.chain = [Block.from_dict(b) for b in data['chain']]
        blockchain.difficulty = data.get('difficulty', config.INITIAL_DIFFICULTY)
        blockchain.pending_transactions = data.get('pending_transactions', [])
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
        return f"Blockchain(height={self.height}, difficulty={self.difficulty})"
