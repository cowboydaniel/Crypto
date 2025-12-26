"""
CPUCoin Miner - CPU-optimized mining with physical coin file creation

The miner:
1. Creates block candidates with pending transactions
2. Uses Argon2 (memory-hard) for CPU-friendly proof-of-work
3. Mints new coin files on successful block discovery
4. Supports multi-threaded mining for multi-core CPUs
"""

import os
import time
import json
import threading
import multiprocessing
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass

from . import config
from .blockchain import Block, Blockchain
from .coin import Coin, CoinStore, DEFAULT_COIN_DIR
from .wallet import Wallet
from .crypto_utils import mining_hash, check_difficulty


@dataclass
class MiningResult:
    """Result of a mining attempt."""
    success: bool
    block: Optional[Block] = None
    coin: Optional[Coin] = None
    hash_rate: float = 0.0
    attempts: int = 0
    elapsed_time: float = 0.0


class Miner:
    """
    CPU Miner for CPUCoin.

    Features:
    - Argon2-based proof-of-work (CPU-friendly, memory-hard)
    - Multi-threaded mining support
    - Creates physical coin files on successful mining
    - Real-time hash rate monitoring
    - Configurable difficulty adjustment
    """

    def __init__(self, wallet: Wallet, blockchain: Blockchain,
                 coin_dir: str = DEFAULT_COIN_DIR, num_threads: int = 1):
        """
        Initialize the miner.

        Args:
            wallet: Wallet to receive mining rewards
            blockchain: Blockchain to mine on
            coin_dir: Directory to store mined coins
            num_threads: Number of mining threads (default 1)
        """
        self.wallet = wallet
        self.blockchain = blockchain
        self.coin_dir = coin_dir
        self.num_threads = min(num_threads, multiprocessing.cpu_count())

        # Mining state
        self.is_mining = False
        self.current_block: Optional[Block] = None
        self.total_hashes = 0
        self.start_time = 0.0
        self.blocks_mined = 0
        self.coins_minted: List[Coin] = []

        # Callbacks
        self.on_block_found: Optional[Callable[[Block, Coin], None]] = None
        self.on_hash_update: Optional[Callable[[float, int], None]] = None

        # Threading
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def mine_block(self, verbose: bool = True) -> MiningResult:
        """
        Mine a single block.

        Args:
            verbose: Print progress information

        Returns:
            MiningResult with the mined block and coin
        """
        # Create new block
        block = self.blockchain.create_block(self.wallet.public_key)

        if verbose:
            print(f"\n⛏️  Mining block #{block.index}")
            print(f"   Difficulty: {block.difficulty}")
            print(f"   Transactions: {len(block.transactions)}")
            print(f"   Target reward: {self.blockchain.get_block_reward():.8f} CPU")
            print()

        start_time = time.time()
        attempts = 0

        while True:
            block.hash = block.compute_hash()
            attempts += 1

            if check_difficulty(block.hash, block.difficulty):
                elapsed = time.time() - start_time
                hash_rate = attempts / elapsed if elapsed > 0 else 0

                # Block found! Create the physical coin file
                mining_proof = {
                    'nonce': block.nonce,
                    'hash': block.hash,
                    'difficulty': block.difficulty,
                    'timestamp': time.time(),
                    'attempts': attempts,
                    'hash_rate': hash_rate
                }

                # Mint the coin file
                coin = Coin.mint(
                    owner_pubkey=self.wallet.public_key,
                    value=self.blockchain.get_block_reward(),
                    block_height=block.index,
                    mining_proof=mining_proof,
                    coin_dir=self.coin_dir
                )

                if verbose:
                    print(f"\n✅ Block #{block.index} mined successfully!")
                    print(f"   Hash: {block.hash}")
                    print(f"   Nonce: {block.nonce}")
                    print(f"   Attempts: {attempts:,}")
                    print(f"   Time: {elapsed:.2f}s")
                    print(f"   Hash rate: {hash_rate:.2f} H/s")
                    print(f"\n💰 Coin minted: {coin.coin_id}")
                    print(f"   Value: {coin.value:.8f} CPU")
                    print(f"   File: {coin.filepath}")

                # Add block to chain
                self.blockchain.add_block(block)

                return MiningResult(
                    success=True,
                    block=block,
                    coin=coin,
                    hash_rate=hash_rate,
                    attempts=attempts,
                    elapsed_time=elapsed
                )

            block.nonce += 1

            if verbose and attempts % 50 == 0:
                elapsed = time.time() - start_time
                hash_rate = attempts / elapsed if elapsed > 0 else 0
                print(f"\r   Mining... {attempts:,} hashes, {hash_rate:.2f} H/s", end="", flush=True)

    def mine_continuous(self, num_blocks: int = 0, verbose: bool = True,
                        callback: Optional[Callable[[MiningResult], bool]] = None):
        """
        Mine blocks continuously.

        Args:
            num_blocks: Number of blocks to mine (0 = infinite)
            verbose: Print progress
            callback: Called after each block, return False to stop

        Returns:
            List of MiningResults
        """
        self.is_mining = True
        self.start_time = time.time()
        results = []

        if verbose:
            print("=" * 60)
            print("     CPUCoin Miner Started")
            print("=" * 60)
            print(f"Wallet: {self.wallet.address[:30]}...")
            print(f"Threads: {self.num_threads}")
            print(f"Coin directory: {self.coin_dir}")
            print("=" * 60)

        blocks_mined = 0
        while self.is_mining:
            if num_blocks > 0 and blocks_mined >= num_blocks:
                break

            result = self.mine_block(verbose=verbose)
            results.append(result)

            if result.success:
                blocks_mined += 1
                self.blocks_mined += 1
                self.coins_minted.append(result.coin)

                if callback and not callback(result):
                    break

        if verbose:
            elapsed = time.time() - self.start_time
            print("\n" + "=" * 60)
            print("     Mining Session Complete")
            print("=" * 60)
            print(f"Blocks mined: {blocks_mined}")
            print(f"Total time: {elapsed:.2f}s")
            print(f"Current balance: {self.wallet.get_balance():.8f} CPU")
            print("=" * 60)

        self.is_mining = False
        return results

    def stop(self):
        """Stop mining."""
        self.is_mining = False
        self._stop_event.set()

    def get_stats(self) -> Dict[str, Any]:
        """Get mining statistics."""
        elapsed = time.time() - self.start_time if self.start_time else 0
        return {
            'is_mining': self.is_mining,
            'blocks_mined': self.blocks_mined,
            'coins_minted': len(self.coins_minted),
            'total_mined_value': sum(c.value for c in self.coins_minted),
            'elapsed_time': elapsed,
            'current_difficulty': self.blockchain.difficulty,
            'blockchain_height': self.blockchain.height
        }


class MultiThreadedMiner(Miner):
    """
    Multi-threaded miner for multi-core CPUs.

    Each thread works on different nonce ranges to maximize CPU utilization.
    """

    def __init__(self, wallet: Wallet, blockchain: Blockchain,
                 coin_dir: str = DEFAULT_COIN_DIR, num_threads: int = 0):
        if num_threads <= 0:
            num_threads = multiprocessing.cpu_count()
        super().__init__(wallet, blockchain, coin_dir, num_threads)
        self._found_block: Optional[Block] = None
        self._threads: List[threading.Thread] = []

    def _mine_thread(self, thread_id: int, block: Block, start_nonce: int, step: int):
        """Mining thread worker."""
        local_block = Block(
            index=block.index,
            timestamp=block.timestamp,
            transactions=block.transactions,
            previous_hash=block.previous_hash,
            difficulty=block.difficulty,
            miner=block.miner,
            merkle_root=block.merkle_root
        )
        local_block.nonce = start_nonce

        while not self._stop_event.is_set():
            local_block.hash = local_block.compute_hash()

            if check_difficulty(local_block.hash, local_block.difficulty):
                with self._lock:
                    if self._found_block is None:
                        self._found_block = local_block
                        self._stop_event.set()
                return

            local_block.nonce += step
            self.total_hashes += 1

    def mine_block(self, verbose: bool = True) -> MiningResult:
        """Mine a block using multiple threads."""
        self._stop_event.clear()
        self._found_block = None
        self.total_hashes = 0

        # Create new block
        block = self.blockchain.create_block(self.wallet.public_key)

        if verbose:
            print(f"\n⛏️  Mining block #{block.index} (multi-threaded)")
            print(f"   Difficulty: {block.difficulty}")
            print(f"   Threads: {self.num_threads}")
            print(f"   Transactions: {len(block.transactions)}")

        start_time = time.time()

        # Start mining threads
        self._threads = []
        for i in range(self.num_threads):
            t = threading.Thread(
                target=self._mine_thread,
                args=(i, block, i, self.num_threads)
            )
            t.daemon = True
            t.start()
            self._threads.append(t)

        # Monitor progress
        while not self._stop_event.is_set():
            time.sleep(0.5)
            elapsed = time.time() - start_time
            hash_rate = self.total_hashes / elapsed if elapsed > 0 else 0
            if verbose:
                print(f"\r   Mining... {self.total_hashes:,} hashes, {hash_rate:.2f} H/s", end="", flush=True)

        # Wait for threads to finish
        for t in self._threads:
            t.join(timeout=1.0)

        if self._found_block:
            elapsed = time.time() - start_time
            hash_rate = self.total_hashes / elapsed if elapsed > 0 else 0

            mining_proof = {
                'nonce': self._found_block.nonce,
                'hash': self._found_block.hash,
                'difficulty': self._found_block.difficulty,
                'timestamp': time.time(),
                'attempts': self.total_hashes,
                'hash_rate': hash_rate,
                'threads': self.num_threads
            }

            # Mint the coin file
            coin = Coin.mint(
                owner_pubkey=self.wallet.public_key,
                value=self.blockchain.get_block_reward(),
                block_height=self._found_block.index,
                mining_proof=mining_proof,
                coin_dir=self.coin_dir
            )

            if verbose:
                print(f"\n\n✅ Block #{self._found_block.index} mined!")
                print(f"   Hash: {self._found_block.hash}")
                print(f"   Nonce: {self._found_block.nonce}")
                print(f"   Total hashes: {self.total_hashes:,}")
                print(f"   Time: {elapsed:.2f}s")
                print(f"   Hash rate: {hash_rate:.2f} H/s")
                print(f"\n💰 Coin minted: {coin.coin_id}")
                print(f"   Value: {coin.value:.8f} CPU")
                print(f"   File: {coin.filepath}")

            self.blockchain.add_block(self._found_block)

            return MiningResult(
                success=True,
                block=self._found_block,
                coin=coin,
                hash_rate=hash_rate,
                attempts=self.total_hashes,
                elapsed_time=elapsed
            )

        return MiningResult(success=False)


def quick_mine(num_blocks: int = 1, wallet_name: str = "miner",
               password: str = "", verbose: bool = True) -> List[MiningResult]:
    """
    Quick mining function for easy use.

    Args:
        num_blocks: Number of blocks to mine
        wallet_name: Name of wallet to use/create
        password: Wallet password
        verbose: Print progress

    Returns:
        List of mining results
    """
    from .wallet import Wallet, list_wallets, DEFAULT_WALLET_DIR

    # Load or create wallet
    if wallet_name in list_wallets():
        wallet = Wallet.load(wallet_name, password)
    else:
        wallet = Wallet.create(wallet_name, password)
        if verbose:
            print(f"Created new wallet: {wallet.name}")
            print(f"Address: {wallet.address}")

    # Create blockchain
    blockchain = Blockchain()

    # Create miner
    miner = MultiThreadedMiner(wallet, blockchain)

    # Mine blocks
    results = miner.mine_continuous(num_blocks=num_blocks, verbose=verbose)

    # Save blockchain
    blockchain.save(os.path.expanduser("~/.cpucoin/blockchain.json"))

    return results
