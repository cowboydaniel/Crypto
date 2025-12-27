"""
CPUCoin Miner - Share-based mining with physical coin file creation

The miner uses a block shares system:
1. Each block contains multiple shares (coinlets)
2. Finding a share is easier than finding a block
3. Multiple miners can find different shares in the same block
4. Finding the full block closes it and awards remaining shares as bonus

Mining flow:
1. Get or create an open block
2. Mine for shares (check share difficulty)
3. If hash also meets block difficulty -> BLOCK FOUND! Get bonus shares
4. Mint coin files for each share earned
"""

import os
import time
import json
import threading
import multiprocessing
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field

from . import config
from .blockchain import Block, Blockchain
from .coin import Coin, CoinStore, DEFAULT_COIN_DIR
from .wallet import Wallet
from .crypto_utils import mining_hash, check_difficulty


@dataclass
class ShareResult:
    """Result of mining a single share."""
    success: bool
    share_index: int = 0
    nonce: int = 0
    hash_value: str = ""
    is_block_find: bool = False  # True if this hash also found the block
    coin: Optional[Coin] = None
    hash_rate: float = 0.0
    attempts: int = 0
    elapsed_time: float = 0.0


@dataclass
class BlockResult:
    """Result of mining a complete block (all shares + block find)."""
    block: Optional[Block] = None
    shares_found: int = 0
    bonus_shares: int = 0
    coins_minted: List[Coin] = field(default_factory=list)
    block_found: bool = False
    total_value: float = 0.0
    elapsed_time: float = 0.0


class ShareMiner:
    """
    Share-based miner for CPUCoin.

    Features:
    - Mines for individual shares (coinlets)
    - Occasionally finds full blocks for bonus shares
    - Creates physical coin files for each share found
    - Multi-threaded support for faster mining
    """

    def __init__(self, wallet: Wallet, blockchain: Blockchain,
                 coin_dir: str = DEFAULT_COIN_DIR, num_threads: int = 1):
        """
        Initialize the miner.

        Args:
            wallet: Wallet to receive mining rewards
            blockchain: Blockchain to mine on
            coin_dir: Directory to store mined coins
            num_threads: Number of mining threads
        """
        self.wallet = wallet
        self.blockchain = blockchain
        self.coin_dir = coin_dir
        self.num_threads = min(num_threads, multiprocessing.cpu_count())

        # Mining state
        self.is_mining = False
        self.total_hashes = 0
        self.start_time = 0.0
        self.shares_found = 0
        self.blocks_found = 0
        self.coins_minted: List[Coin] = []

        # Threading
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._share_found_event = threading.Event()
        self._found_result: Optional[ShareResult] = None

    def mine_share(self, verbose: bool = True) -> ShareResult:
        """
        Mine for a single share in the current open block.

        Args:
            verbose: Print progress information

        Returns:
            ShareResult with the mined share details
        """
        # Get or create open block
        block = self.blockchain.get_or_create_open_block()
        share_index = block.get_next_share_index()

        if share_index is None:
            # Block is fully claimed, need to close it
            if verbose:
                print("Block fully claimed, creating new block...")
            block = self.blockchain.create_block()
            self.blockchain.current_open_block = block
            share_index = 0

        share_value = self.blockchain.get_share_value()

        if verbose:
            print(f"\n⛏️  Mining share #{share_index} in block #{block.index}")
            print(f"   Share difficulty: {block.share_difficulty}")
            print(f"   Block difficulty: {block.block_difficulty}")
            print(f"   Share value: {share_value:.8f} CPU")
            print(f"   Shares remaining: {block.shares_remaining()}/{config.SHARES_PER_BLOCK}")
            print()

        start_time = time.time()
        attempts = 0
        nonce = block.nonce

        while True:
            # Compute hash
            header = block.compute_header()
            hash_value = mining_hash(header, nonce, block.previous_hash)
            attempts += 1

            # Check if we found a BLOCK (much harder)
            is_block_find = check_difficulty(hash_value, block.block_difficulty)

            # Check if we found a SHARE (easier)
            if check_difficulty(hash_value, block.share_difficulty) or is_block_find:
                elapsed = time.time() - start_time
                hash_rate = attempts / elapsed if elapsed > 0 else 0

                # Claim the share
                block.claim_share(share_index, self.wallet.public_key, nonce, hash_value)

                # Create mining proof
                mining_proof = {
                    'nonce': nonce,
                    'hash': hash_value,
                    'share_difficulty': block.share_difficulty,
                    'block_difficulty': block.block_difficulty,
                    'timestamp': time.time(),
                    'attempts': attempts,
                    'hash_rate': hash_rate,
                    'is_block_find': is_block_find
                }

                # Mint the coin for this share
                coin = Coin.mint(
                    owner_pubkey=self.wallet.public_key,
                    value=share_value,
                    block_height=block.index,
                    mining_proof=mining_proof,
                    coin_dir=self.coin_dir,
                    share_index=share_index,
                    block_hash=hash_value,
                    is_block_finder=is_block_find
                )

                self.coins_minted.append(coin)
                self.shares_found += 1

                if verbose:
                    if is_block_find:
                        print(f"\n🎉 BLOCK FOUND! Block #{block.index}")
                        print(f"   Hash: {hash_value}")
                        print(f"   Meets block difficulty: {block.block_difficulty}")
                    else:
                        print(f"\n✅ Share #{share_index} mined!")
                        print(f"   Hash: {hash_value}")

                    print(f"   Nonce: {nonce}")
                    print(f"   Attempts: {attempts:,}")
                    print(f"   Time: {elapsed:.2f}s")
                    print(f"   Hash rate: {hash_rate:.2f} H/s")
                    print(f"\n💰 Coin minted: {coin.coin_id}")
                    print(f"   Value: {coin.value:.8f} CPU")
                    print(f"   File: {coin.filepath}")

                # If we found the block, handle bonus shares
                bonus_coins = []
                if is_block_find:
                    bonus_coins = self._handle_block_find(block, nonce, hash_value, mining_proof, verbose)

                result = ShareResult(
                    success=True,
                    share_index=share_index,
                    nonce=nonce,
                    hash_value=hash_value,
                    is_block_find=is_block_find,
                    coin=coin,
                    hash_rate=hash_rate,
                    attempts=attempts,
                    elapsed_time=elapsed
                )

                return result

            nonce += 1

            if verbose and attempts % 50 == 0:
                elapsed = time.time() - start_time
                hash_rate = attempts / elapsed if elapsed > 0 else 0
                print(f"\r   Mining... {attempts:,} hashes, {hash_rate:.2f} H/s", end="", flush=True)

    def _handle_block_find(self, block: Block, nonce: int, hash_value: str,
                           mining_proof: Dict, verbose: bool = True) -> List[Coin]:
        """
        Handle finding a full block - award bonus shares.

        Args:
            block: The block that was found
            nonce: The winning nonce
            hash_value: The winning hash
            mining_proof: Mining proof dict
            verbose: Print progress

        Returns:
            List of bonus coins minted
        """
        self.blocks_found += 1
        bonus_coins = []

        # Get unclaimed shares (these are bonus for block finder)
        unclaimed = block.get_unclaimed_shares()
        share_value = self.blockchain.get_share_value()

        if verbose and unclaimed:
            print(f"\n🎁 BONUS! Claiming {len(unclaimed)} remaining shares...")

        for bonus_index in unclaimed:
            # Claim the bonus share
            block.claim_share(bonus_index, self.wallet.public_key, nonce, hash_value)

            # Mint bonus coin
            bonus_coin = Coin.mint(
                owner_pubkey=self.wallet.public_key,
                value=share_value,
                block_height=block.index,
                mining_proof=mining_proof,
                coin_dir=self.coin_dir,
                share_index=bonus_index,
                block_hash=hash_value,
                is_block_finder=True,
                is_bonus_share=True
            )

            bonus_coins.append(bonus_coin)
            self.coins_minted.append(bonus_coin)
            self.shares_found += 1

            if verbose:
                print(f"   Bonus share #{bonus_index}: {bonus_coin.coin_id[:24]}...")

        # Close the block
        block.close_block(self.wallet.public_key, nonce, hash_value)

        # Add to blockchain
        self.blockchain.add_block(block)
        self.blockchain.current_open_block = None

        if verbose:
            total_bonus = len(unclaimed) * share_value
            print(f"\n📦 Block #{block.index} closed!")
            print(f"   Total bonus: {total_bonus:.8f} CPU ({len(unclaimed)} shares)")

        return bonus_coins

    def mine_continuous(self, num_shares: int = 0, verbose: bool = True,
                        callback: Optional[Callable[[ShareResult], bool]] = None) -> List[ShareResult]:
        """
        Mine shares continuously.

        Args:
            num_shares: Number of shares to mine (0 = infinite)
            verbose: Print progress
            callback: Called after each share, return False to stop

        Returns:
            List of ShareResults
        """
        self.is_mining = True
        self.start_time = time.time()
        results = []

        if verbose:
            print("=" * 60)
            print("     CPUCoin Share Miner Started")
            print("=" * 60)
            print(f"Wallet: {self.wallet.address[:30]}...")
            print(f"Threads: {self.num_threads}")
            print(f"Coin directory: {self.coin_dir}")
            print(f"Shares per block: {config.SHARES_PER_BLOCK}")
            print(f"Share value: {config.SHARE_VALUE:.8f} CPU")
            print("=" * 60)

        shares_mined = 0
        while self.is_mining:
            if num_shares > 0 and shares_mined >= num_shares:
                break

            result = self.mine_share(verbose=verbose)
            results.append(result)

            if result.success:
                shares_mined += 1
                if result.is_block_find:
                    # Count bonus shares
                    block = self.blockchain.last_block
                    shares_mined += len(block.claimed_shares) - 1  # -1 for the share we already counted

                if callback and not callback(result):
                    break

        if verbose:
            elapsed = time.time() - self.start_time
            print("\n" + "=" * 60)
            print("     Mining Session Complete")
            print("=" * 60)
            print(f"Shares mined: {self.shares_found}")
            print(f"Blocks found: {self.blocks_found}")
            print(f"Coins minted: {len(self.coins_minted)}")
            print(f"Total value: {sum(c.value for c in self.coins_minted):.8f} CPU")
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
            'shares_found': self.shares_found,
            'blocks_found': self.blocks_found,
            'coins_minted': len(self.coins_minted),
            'total_mined_value': sum(c.value for c in self.coins_minted),
            'elapsed_time': elapsed,
            'share_difficulty': self.blockchain.share_difficulty,
            'block_difficulty': self.blockchain.block_difficulty,
            'blockchain_height': self.blockchain.height
        }


class MultiThreadedShareMiner(ShareMiner):
    """
    Multi-threaded share miner for multi-core CPUs.

    Each thread works on different nonce ranges to maximize CPU utilization.
    First thread to find a valid share/block wins.
    """

    def __init__(self, wallet: Wallet, blockchain: Blockchain,
                 coin_dir: str = DEFAULT_COIN_DIR, num_threads: int = 0):
        if num_threads <= 0:
            num_threads = multiprocessing.cpu_count()
        super().__init__(wallet, blockchain, coin_dir, num_threads)
        self._threads: List[threading.Thread] = []

    def _mine_thread(self, thread_id: int, block: Block, share_index: int,
                     start_nonce: int, step: int):
        """Mining thread worker."""
        header = block.compute_header()
        nonce = start_nonce

        while not self._stop_event.is_set():
            hash_value = mining_hash(header, nonce, block.previous_hash)

            with self._lock:
                self.total_hashes += 1

            # Check if we found a BLOCK (much harder)
            is_block_find = check_difficulty(hash_value, block.block_difficulty)

            # Check if we found a SHARE (easier)
            if check_difficulty(hash_value, block.share_difficulty) or is_block_find:
                with self._lock:
                    if self._found_result is None:
                        self._found_result = ShareResult(
                            success=True,
                            share_index=share_index,
                            nonce=nonce,
                            hash_value=hash_value,
                            is_block_find=is_block_find
                        )
                        self._stop_event.set()
                return

            nonce += step

    def mine_share(self, verbose: bool = True) -> ShareResult:
        """Mine a share using multiple threads."""
        self._stop_event.clear()
        self._found_result = None
        self.total_hashes = 0

        # Get or create open block
        block = self.blockchain.get_or_create_open_block()
        share_index = block.get_next_share_index()

        if share_index is None:
            block = self.blockchain.create_block()
            self.blockchain.current_open_block = block
            share_index = 0

        share_value = self.blockchain.get_share_value()

        if verbose:
            print(f"\n⛏️  Mining share #{share_index} in block #{block.index} (multi-threaded)")
            print(f"   Threads: {self.num_threads}")
            print(f"   Share difficulty: {block.share_difficulty}")
            print(f"   Block difficulty: {block.block_difficulty}")
            print(f"   Share value: {share_value:.8f} CPU")
            print(f"   Shares remaining: {block.shares_remaining()}/{config.SHARES_PER_BLOCK}")

        start_time = time.time()

        # Start mining threads
        self._threads = []
        for i in range(self.num_threads):
            t = threading.Thread(
                target=self._mine_thread,
                args=(i, block, share_index, i, self.num_threads)
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

        # Wait for threads
        for t in self._threads:
            t.join(timeout=1.0)

        if self._found_result:
            elapsed = time.time() - start_time
            hash_rate = self.total_hashes / elapsed if elapsed > 0 else 0

            result = self._found_result
            result.hash_rate = hash_rate
            result.attempts = self.total_hashes
            result.elapsed_time = elapsed

            # Claim the share
            block.claim_share(result.share_index, self.wallet.public_key,
                            result.nonce, result.hash_value)

            # Create mining proof
            mining_proof = {
                'nonce': result.nonce,
                'hash': result.hash_value,
                'share_difficulty': block.share_difficulty,
                'block_difficulty': block.block_difficulty,
                'timestamp': time.time(),
                'attempts': self.total_hashes,
                'hash_rate': hash_rate,
                'threads': self.num_threads,
                'is_block_find': result.is_block_find
            }

            # Mint the coin
            coin = Coin.mint(
                owner_pubkey=self.wallet.public_key,
                value=share_value,
                block_height=block.index,
                mining_proof=mining_proof,
                coin_dir=self.coin_dir,
                share_index=result.share_index,
                block_hash=result.hash_value,
                is_block_finder=result.is_block_find
            )

            result.coin = coin
            self.coins_minted.append(coin)
            self.shares_found += 1

            if verbose:
                if result.is_block_find:
                    print(f"\n\n🎉 BLOCK FOUND! Block #{block.index}")
                    print(f"   Hash: {result.hash_value}")
                    print(f"   Meets block difficulty: {block.block_difficulty}")
                else:
                    print(f"\n\n✅ Share #{result.share_index} mined!")
                    print(f"   Hash: {result.hash_value}")

                print(f"   Nonce: {result.nonce}")
                print(f"   Total hashes: {self.total_hashes:,}")
                print(f"   Time: {elapsed:.2f}s")
                print(f"   Hash rate: {hash_rate:.2f} H/s")
                print(f"\n💰 Coin minted: {coin.coin_id}")
                print(f"   Value: {coin.value:.8f} CPU")
                print(f"   File: {coin.filepath}")

            # Handle block find bonus
            if result.is_block_find:
                self._handle_block_find(block, result.nonce, result.hash_value,
                                       mining_proof, verbose)

            return result

        return ShareResult(success=False)


# Legacy compatibility aliases
class Miner(ShareMiner):
    """Legacy alias for ShareMiner."""
    pass


class MultiThreadedMiner(MultiThreadedShareMiner):
    """Legacy alias for MultiThreadedShareMiner."""
    pass


@dataclass
class MiningResult:
    """Legacy result format for compatibility."""
    success: bool
    block: Optional[Block] = None
    coin: Optional[Coin] = None
    hash_rate: float = 0.0
    attempts: int = 0
    elapsed_time: float = 0.0


def quick_mine(num_shares: int = 1, wallet_name: str = "miner",
               password: str = "", verbose: bool = True) -> List[ShareResult]:
    """
    Quick mining function for easy use.

    Args:
        num_shares: Number of shares to mine
        wallet_name: Name of wallet to use/create
        password: Wallet password
        verbose: Print progress

    Returns:
        List of share results
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
    miner = MultiThreadedShareMiner(wallet, blockchain)

    # Mine shares
    results = miner.mine_continuous(num_shares=num_shares, verbose=verbose)

    # Save blockchain
    blockchain.save(os.path.expanduser("~/.cpucoin/blockchain.json"))

    return results
