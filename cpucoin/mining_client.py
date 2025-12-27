"""
CPUCoin Mining Client

Client for miners to connect to a central mining server.
Handles:
- Fetching current block to mine
- Submitting found shares
- Creating local coin files for earned shares
"""

import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from dataclasses import dataclass

from . import config
from .coin import Coin
from .crypto_utils import mining_hash, check_difficulty


@dataclass
class BlockTemplate:
    """Block template received from server for mining."""
    block_index: int
    previous_hash: str
    merkle_root: str
    timestamp: float
    share_difficulty: int
    block_difficulty: int
    shares_claimed: int
    shares_remaining: int
    is_closed: bool
    header: str


@dataclass
class SubmitResult:
    """Result of submitting a share to the server."""
    success: bool
    message: str
    share_index: int = -1
    is_block_find: bool = False
    bonus_shares: int = 0
    coin_data: Optional[Dict[str, Any]] = None


class MiningClient:
    """
    Client for connecting to a CPUCoin mining server.

    Usage:
        client = MiningClient("http://localhost:8333")
        template = client.get_current_block()

        # Mine until we find a valid hash
        nonce = 0
        while True:
            hash_value = mining_hash(template.header, nonce, template.previous_hash)
            if check_difficulty(hash_value, template.share_difficulty):
                result = client.submit_share(miner_pubkey, nonce, hash_value, template.block_index)
                if result.success:
                    # Create local coin file
                    client.create_coin(result, miner_pubkey)
                break
            nonce += 1
    """

    def __init__(self, server_url: str, timeout: int = 30):
        """
        Initialize the mining client.

        Args:
            server_url: URL of the mining server (e.g., "http://localhost:8333")
            timeout: Request timeout in seconds
        """
        self.server_url = server_url.rstrip('/')
        self.timeout = timeout
        self._last_error: Optional[str] = None

    def _request(self, method: str, path: str, data: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """Make an HTTP request to the server."""
        url = f"{self.server_url}{path}"

        try:
            if method == 'GET':
                req = urllib.request.Request(url)
            else:
                body = json.dumps(data).encode() if data else b''
                req = urllib.request.Request(url, data=body, method=method)
                req.add_header('Content-Type', 'application/json')

            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode())

        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read().decode())
                self._last_error = error_body.get('message', str(e))
            except Exception:
                self._last_error = str(e)
            return None

        except urllib.error.URLError as e:
            self._last_error = f"Connection failed: {e.reason}"
            return None

        except Exception as e:
            self._last_error = str(e)
            return None

    def get_server_info(self) -> Optional[Dict[str, Any]]:
        """Get server information."""
        return self._request('GET', '/')

    def get_current_block(self) -> Optional[BlockTemplate]:
        """Get the current block template for mining."""
        data = self._request('GET', '/block/current')
        if not data:
            return None

        return BlockTemplate(
            block_index=data['block_index'],
            previous_hash=data['previous_hash'],
            merkle_root=data['merkle_root'],
            timestamp=data['timestamp'],
            share_difficulty=data['share_difficulty'],
            block_difficulty=data['block_difficulty'],
            shares_claimed=data['shares_claimed'],
            shares_remaining=data['shares_remaining'],
            is_closed=data['is_closed'],
            header=data['header']
        )

    def get_blockchain_info(self) -> Optional[Dict[str, Any]]:
        """Get blockchain information."""
        return self._request('GET', '/blockchain/info')

    def submit_share(
        self, miner_pubkey: str, nonce: int, hash_value: str, block_index: int
    ) -> SubmitResult:
        """
        Submit a found share to the server.

        Args:
            miner_pubkey: Miner's public key
            nonce: The nonce that produced the valid hash
            hash_value: The hash meeting share difficulty
            block_index: The block index being mined

        Returns:
            SubmitResult with success status and coin data if accepted
        """
        data = {
            'miner_pubkey': miner_pubkey,
            'nonce': nonce,
            'hash': hash_value,
            'block_index': block_index
        }

        result = self._request('POST', '/share/submit', data)

        if result is None:
            return SubmitResult(
                success=False,
                message=self._last_error or "Unknown error"
            )

        return SubmitResult(
            success=result.get('success', False),
            message=result.get('message', ''),
            share_index=result.get('share_index', -1),
            is_block_find=result.get('is_block_find', False),
            bonus_shares=result.get('bonus_shares', 0),
            coin_data=result.get('coin_data')
        )

    def create_coin(self, result: SubmitResult, miner_pubkey: str) -> Optional[Coin]:
        """
        Create a local coin file from a successful share submission.

        Args:
            result: The successful SubmitResult from submit_share
            miner_pubkey: Miner's public key

        Returns:
            The created Coin, or None if failed
        """
        if not result.success or not result.coin_data:
            return None

        coin_data = result.coin_data

        # Mint the main share coin
        coin = Coin.mint(
            owner_pubkey=miner_pubkey,
            value=coin_data['value'],
            block_height=coin_data['block_height'],
            mining_proof=coin_data['mining_proof'],
            share_index=coin_data['share_index'],
            block_hash=coin_data['block_hash'],
            is_block_finder=coin_data['is_block_finder'],
            is_bonus_share=False
        )

        # If block find, also create bonus share coins
        if result.is_block_find and result.bonus_shares > 0:
            for i in range(result.bonus_shares):
                Coin.mint(
                    owner_pubkey=miner_pubkey,
                    value=coin_data['value'],
                    block_height=coin_data['block_height'],
                    mining_proof=coin_data['mining_proof'],
                    share_index=coin_data['share_index'] + 1 + i,  # Bonus shares get subsequent indices
                    block_hash=coin_data['block_hash'],
                    is_block_finder=False,
                    is_bonus_share=True
                )

        return coin

    def is_connected(self) -> bool:
        """Check if server is reachable."""
        info = self.get_server_info()
        return info is not None

    @property
    def last_error(self) -> Optional[str]:
        """Get the last error message."""
        return self._last_error


class ServerShareMiner:
    """
    Share miner that connects to a central server.

    This miner:
    1. Fetches the current block from the server
    2. Mines locally until finding a valid share hash
    3. Submits the share to the server
    4. Creates local coin files for accepted shares
    """

    def __init__(self, wallet, server_url: str):
        """
        Initialize the server-connected miner.

        Args:
            wallet: Wallet with miner's keys
            server_url: URL of the mining server
        """
        self.wallet = wallet
        self.client = MiningClient(server_url)
        self.is_running = False
        self._stop_requested = False

    def stop(self):
        """Request mining to stop."""
        self._stop_requested = True

    def mine_share(self, verbose: bool = True) -> Optional[SubmitResult]:
        """
        Mine a single share.

        Returns:
            SubmitResult if share found and submitted, None if stopped/error
        """
        # Get current block from server
        template = self.client.get_current_block()
        if not template:
            if verbose:
                print(f"Failed to get block: {self.client.last_error}")
            return None

        if template.is_closed:
            if verbose:
                print("Block is closed, fetching new block...")
            return None

        if verbose:
            print(f"Mining block #{template.block_index} "
                  f"(shares: {template.shares_claimed}/{config.SHARES_PER_BLOCK}, "
                  f"difficulty: {template.share_difficulty}/{template.block_difficulty})")

        # Mine until we find a valid hash
        start_time = time.time()
        nonce = 0
        attempts = 0

        while not self._stop_requested:
            hash_value = mining_hash(template.header, nonce, template.previous_hash)
            attempts += 1

            # Check share difficulty
            if check_difficulty(hash_value, template.share_difficulty):
                elapsed = time.time() - start_time

                # Check if also meets block difficulty
                is_block = check_difficulty(hash_value, template.block_difficulty)

                if verbose:
                    if is_block:
                        print(f"\n🎉 BLOCK FOUND!")
                    else:
                        print(f"\n✓ Share found!")
                    print(f"  Nonce: {nonce}")
                    print(f"  Hash: {hash_value[:32]}...")
                    print(f"  Attempts: {attempts}")
                    print(f"  Time: {elapsed:.2f}s")
                    print(f"  Rate: {attempts/elapsed:.2f} H/s")

                # Submit to server
                result = self.client.submit_share(
                    miner_pubkey=self.wallet.public_key,
                    nonce=nonce,
                    hash_value=hash_value,
                    block_index=template.block_index
                )

                if result.success:
                    # Create local coin file
                    coin = self.client.create_coin(result, self.wallet.public_key)
                    if coin:
                        if verbose:
                            print(f"  💰 Coin created: {coin.coin_id[:24]}...")
                            if result.is_block_find:
                                print(f"  🎁 Bonus shares: {result.bonus_shares}")
                        # Add to wallet balance
                        self.wallet.add_coin(coin.coin_id)
                else:
                    if verbose:
                        print(f"  ❌ Share rejected: {result.message}")

                return result

            nonce += 1

            # Progress update every 100 hashes
            if verbose and attempts % 100 == 0:
                elapsed = time.time() - start_time
                print(f"\rMining... Attempts: {attempts}, "
                      f"Rate: {attempts/elapsed:.2f} H/s, "
                      f"Nonce: {nonce}", end="", flush=True)

        return None

    def mine_continuous(self, num_shares: int = 0, verbose: bool = True) -> list:
        """
        Mine shares continuously.

        Args:
            num_shares: Number of shares to mine (0 = infinite)
            verbose: Print progress

        Returns:
            List of SubmitResult for successful shares
        """
        self.is_running = True
        self._stop_requested = False
        results = []
        shares_mined = 0

        while not self._stop_requested:
            if num_shares > 0 and shares_mined >= num_shares:
                break

            result = self.mine_share(verbose=verbose)
            if result and result.success:
                results.append(result)
                shares_mined += 1

                # Count bonus shares too
                if result.is_block_find:
                    shares_mined += result.bonus_shares

            # Small delay before next share to avoid hammering server
            time.sleep(0.1)

        self.is_running = False
        return results
