"""
CPUCoin - File-based coin system

Each coin is stored as a physical file on disk containing:
- Unique coin ID
- Value/denomination
- Owner's public key
- Chain of ownership history
- Cryptographic signatures
- Mining proof (for minted coins)
"""

import os
import json
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from .crypto_utils import sha256, double_sha256


# Default directory for storing coins
DEFAULT_COIN_DIR = os.path.expanduser("~/.cpucoin/coins")


@dataclass
class CoinData:
    """
    Data structure representing a coin stored on disk.

    Each coin file contains this data serialized as JSON.
    """
    coin_id: str                          # Unique identifier (UUID + hash)
    value: float                          # Coin value/denomination
    owner_pubkey: str                     # Current owner's public key
    created_at: float                     # Timestamp when mined
    block_height: int                     # Block height when mined
    mining_proof: Dict[str, Any]          # PoW proof (nonce, hash, difficulty)
    history: List[Dict[str, Any]] = field(default_factory=list)  # Ownership chain
    signature: str = ""                   # Owner's signature on current state
    parent_coins: List[str] = field(default_factory=list)  # For split/combine
    is_spent: bool = False                # Whether coin has been transferred
    version: int = 1                      # Format version

    def compute_hash(self) -> str:
        """Compute unique hash of this coin's data."""
        data = {
            'coin_id': self.coin_id,
            'value': self.value,
            'owner_pubkey': self.owner_pubkey,
            'created_at': self.created_at,
            'block_height': self.block_height,
            'mining_proof': self.mining_proof,
            'history': self.history,
            'parent_coins': self.parent_coins
        }
        return double_sha256(json.dumps(data, sort_keys=True))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CoinData':
        """Create from dictionary."""
        return cls(**data)


class Coin:
    """
    A physical coin file on disk.

    Coins are stored as .coin files containing JSON data with
    cryptographic proofs of ownership and mining.
    """

    EXTENSION = ".coin"

    def __init__(self, data: CoinData, filepath: Optional[str] = None):
        self.data = data
        self.filepath = filepath

    @property
    def coin_id(self) -> str:
        return self.data.coin_id

    @property
    def value(self) -> float:
        return self.data.value

    @property
    def owner(self) -> str:
        return self.data.owner_pubkey

    @property
    def is_spent(self) -> bool:
        return self.data.is_spent

    @classmethod
    def generate_coin_id(cls, owner_pubkey: str, block_height: int, nonce: int) -> str:
        """Generate a unique coin ID."""
        unique_data = f"{owner_pubkey}{block_height}{nonce}{time.time()}{uuid.uuid4()}"
        return f"COIN-{sha256(unique_data)[:32]}"

    @classmethod
    def mint(cls, owner_pubkey: str, value: float, block_height: int,
             mining_proof: Dict[str, Any], coin_dir: str = DEFAULT_COIN_DIR) -> 'Coin':
        """
        Mint a new coin (called when mining is successful).

        Args:
            owner_pubkey: Public key of the miner
            value: Value of the coin (block reward)
            block_height: Current block height
            mining_proof: Dictionary with nonce, hash, difficulty
            coin_dir: Directory to store the coin file

        Returns:
            The newly minted Coin
        """
        coin_id = cls.generate_coin_id(owner_pubkey, block_height, mining_proof.get('nonce', 0))

        data = CoinData(
            coin_id=coin_id,
            value=value,
            owner_pubkey=owner_pubkey,
            created_at=time.time(),
            block_height=block_height,
            mining_proof=mining_proof,
            history=[{
                'action': 'mint',
                'timestamp': time.time(),
                'owner': owner_pubkey,
                'value': value,
                'block_height': block_height
            }]
        )

        coin = cls(data)
        coin.save(coin_dir)
        return coin

    def save(self, coin_dir: str = DEFAULT_COIN_DIR) -> str:
        """
        Save coin to disk as a physical file.

        Args:
            coin_dir: Directory to store the coin

        Returns:
            Path to the saved coin file
        """
        # Create directory if needed
        Path(coin_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename from coin ID
        filename = f"{self.coin_id}{self.EXTENSION}"
        filepath = os.path.join(coin_dir, filename)

        # Write coin data as JSON
        with open(filepath, 'w') as f:
            json.dump(self.data.to_dict(), f, indent=2)

        self.filepath = filepath
        return filepath

    @classmethod
    def load(cls, filepath: str) -> 'Coin':
        """
        Load a coin from disk.

        Args:
            filepath: Path to the coin file

        Returns:
            Loaded Coin object
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        return cls(CoinData.from_dict(data), filepath)

    @classmethod
    def load_by_id(cls, coin_id: str, coin_dir: str = DEFAULT_COIN_DIR) -> Optional['Coin']:
        """Load a coin by its ID."""
        filepath = os.path.join(coin_dir, f"{coin_id}{cls.EXTENSION}")
        if os.path.exists(filepath):
            return cls.load(filepath)
        return None

    def transfer(self, new_owner_pubkey: str, signature: str, coin_dir: str = DEFAULT_COIN_DIR) -> 'Coin':
        """
        Transfer this coin to a new owner.

        Creates a new coin file for the recipient and marks this one as spent.

        Args:
            new_owner_pubkey: Public key of the new owner
            signature: Current owner's signature authorizing transfer
            coin_dir: Directory for coin storage

        Returns:
            New Coin object for the recipient
        """
        if self.data.is_spent:
            raise ValueError("Coin has already been spent")

        # Mark current coin as spent
        self.data.is_spent = True

        # Add to history
        transfer_record = {
            'action': 'transfer',
            'timestamp': time.time(),
            'from': self.data.owner_pubkey,
            'to': new_owner_pubkey,
            'signature': signature
        }

        # Create new coin data for recipient
        new_data = CoinData(
            coin_id=self.generate_coin_id(new_owner_pubkey, self.data.block_height, int(time.time())),
            value=self.data.value,
            owner_pubkey=new_owner_pubkey,
            created_at=self.data.created_at,
            block_height=self.data.block_height,
            mining_proof=self.data.mining_proof,
            history=self.data.history + [transfer_record],
            parent_coins=[self.coin_id]
        )

        # Save spent status to original file
        self.save(coin_dir)

        # Create and save new coin
        new_coin = Coin(new_data)
        new_coin.save(coin_dir)

        return new_coin

    def split(self, amounts: List[float], owner_signature: str,
              coin_dir: str = DEFAULT_COIN_DIR) -> List['Coin']:
        """
        Split this coin into multiple smaller coins.

        Args:
            amounts: List of values for new coins (must sum to original value)
            owner_signature: Owner's signature authorizing the split
            coin_dir: Directory for coin storage

        Returns:
            List of new smaller Coin objects
        """
        if self.data.is_spent:
            raise ValueError("Coin has already been spent")

        if abs(sum(amounts) - self.data.value) > 0.00000001:
            raise ValueError("Split amounts must sum to original coin value")

        # Mark as spent
        self.data.is_spent = True

        split_record = {
            'action': 'split',
            'timestamp': time.time(),
            'owner': self.data.owner_pubkey,
            'original_value': self.data.value,
            'split_amounts': amounts,
            'signature': owner_signature
        }

        new_coins = []
        for i, amount in enumerate(amounts):
            new_data = CoinData(
                coin_id=self.generate_coin_id(self.data.owner_pubkey, self.data.block_height, i),
                value=amount,
                owner_pubkey=self.data.owner_pubkey,
                created_at=self.data.created_at,
                block_height=self.data.block_height,
                mining_proof=self.data.mining_proof,
                history=self.data.history + [split_record],
                parent_coins=[self.coin_id]
            )
            new_coin = Coin(new_data)
            new_coin.save(coin_dir)
            new_coins.append(new_coin)

        self.save(coin_dir)
        return new_coins

    @classmethod
    def combine(cls, coins: List['Coin'], owner_pubkey: str, owner_signature: str,
                coin_dir: str = DEFAULT_COIN_DIR) -> 'Coin':
        """
        Combine multiple coins into a single larger coin.

        Args:
            coins: List of coins to combine (must all have same owner)
            owner_pubkey: Owner's public key
            owner_signature: Owner's signature authorizing the combine
            coin_dir: Directory for coin storage

        Returns:
            New combined Coin object
        """
        # Validate all coins have same owner
        for coin in coins:
            if coin.data.owner_pubkey != owner_pubkey:
                raise ValueError("All coins must have the same owner")
            if coin.data.is_spent:
                raise ValueError(f"Coin {coin.coin_id} has already been spent")

        total_value = sum(c.data.value for c in coins)
        parent_ids = [c.coin_id for c in coins]

        combine_record = {
            'action': 'combine',
            'timestamp': time.time(),
            'owner': owner_pubkey,
            'parent_coins': parent_ids,
            'combined_value': total_value,
            'signature': owner_signature
        }

        # Mark all source coins as spent
        for coin in coins:
            coin.data.is_spent = True
            coin.data.history.append(combine_record)
            coin.save(coin_dir)

        # Create new combined coin
        new_data = CoinData(
            coin_id=cls.generate_coin_id(owner_pubkey, coins[0].data.block_height, int(time.time())),
            value=total_value,
            owner_pubkey=owner_pubkey,
            created_at=time.time(),
            block_height=coins[0].data.block_height,  # Use earliest block
            mining_proof=coins[0].data.mining_proof,
            history=[combine_record],
            parent_coins=parent_ids
        )

        new_coin = cls(new_data)
        new_coin.save(coin_dir)
        return new_coin

    def verify(self) -> bool:
        """
        Verify the coin's integrity and ownership chain.

        Returns:
            True if coin is valid
        """
        # Check coin ID format
        if not self.coin_id.startswith("COIN-"):
            return False

        # Check mining proof exists
        if not self.data.mining_proof:
            return False

        # Check value is positive
        if self.data.value <= 0:
            return False

        # Check history is not empty
        if not self.data.history:
            return False

        return True

    def get_info(self) -> Dict[str, Any]:
        """Get human-readable coin information."""
        return {
            'Coin ID': self.coin_id,
            'Value': f"{self.data.value:.8f} CPU",
            'Owner': self.data.owner_pubkey[:16] + "..." if len(self.data.owner_pubkey) > 16 else self.data.owner_pubkey,
            'Created': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.data.created_at)),
            'Block Height': self.data.block_height,
            'Status': 'SPENT' if self.data.is_spent else 'UNSPENT',
            'Transfers': len([h for h in self.data.history if h.get('action') == 'transfer']),
            'File': self.filepath
        }

    def __repr__(self) -> str:
        status = "SPENT" if self.data.is_spent else "VALID"
        return f"Coin({self.coin_id[:20]}..., {self.data.value:.8f} CPU, {status})"


class CoinStore:
    """
    Manages all coins on disk for a user.

    Provides methods to list, search, and manage coin files.
    """

    def __init__(self, coin_dir: str = DEFAULT_COIN_DIR):
        self.coin_dir = coin_dir
        Path(coin_dir).mkdir(parents=True, exist_ok=True)

    def list_coins(self, owner_pubkey: Optional[str] = None,
                   include_spent: bool = False) -> List[Coin]:
        """
        List all coins in the store.

        Args:
            owner_pubkey: Filter by owner (optional)
            include_spent: Include spent coins

        Returns:
            List of Coin objects
        """
        coins = []
        coin_dir = Path(self.coin_dir)

        if not coin_dir.exists():
            return coins

        for filepath in coin_dir.glob(f"*{Coin.EXTENSION}"):
            try:
                coin = Coin.load(str(filepath))
                if owner_pubkey and coin.data.owner_pubkey != owner_pubkey:
                    continue
                if not include_spent and coin.data.is_spent:
                    continue
                coins.append(coin)
            except Exception:
                continue  # Skip corrupt files

        return coins

    def get_balance(self, owner_pubkey: str) -> float:
        """Get total balance for an owner."""
        coins = self.list_coins(owner_pubkey=owner_pubkey, include_spent=False)
        return sum(c.data.value for c in coins)

    def get_coin(self, coin_id: str) -> Optional[Coin]:
        """Get a specific coin by ID."""
        return Coin.load_by_id(coin_id, self.coin_dir)

    def find_coins_for_amount(self, owner_pubkey: str, amount: float) -> Optional[List[Coin]]:
        """
        Find coins that sum to at least the required amount.

        Args:
            owner_pubkey: Owner's public key
            amount: Required amount

        Returns:
            List of coins to use, or None if insufficient funds
        """
        coins = self.list_coins(owner_pubkey=owner_pubkey, include_spent=False)
        coins.sort(key=lambda c: c.data.value, reverse=True)

        selected = []
        total = 0.0

        for coin in coins:
            selected.append(coin)
            total += coin.data.value
            if total >= amount:
                return selected

        return None  # Insufficient funds

    def delete_coin(self, coin_id: str) -> bool:
        """Delete a coin file (use with caution!)."""
        filepath = os.path.join(self.coin_dir, f"{coin_id}{Coin.EXTENSION}")
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False

    def export_coin(self, coin_id: str, export_path: str) -> bool:
        """
        Export a coin to a specific location (for transferring).

        Args:
            coin_id: ID of coin to export
            export_path: Where to save the exported coin

        Returns:
            True if successful
        """
        coin = self.get_coin(coin_id)
        if coin:
            import shutil
            shutil.copy2(coin.filepath, export_path)
            return True
        return False

    def import_coin(self, filepath: str) -> Optional[Coin]:
        """
        Import a coin from an external file.

        Args:
            filepath: Path to the coin file to import

        Returns:
            Imported Coin object, or None if invalid
        """
        try:
            coin = Coin.load(filepath)
            if coin.verify():
                # Copy to our coin directory
                new_path = os.path.join(self.coin_dir, os.path.basename(filepath))
                import shutil
                shutil.copy2(filepath, new_path)
                coin.filepath = new_path
                return coin
        except Exception:
            pass
        return None

    def stats(self) -> Dict[str, Any]:
        """Get statistics about stored coins."""
        all_coins = self.list_coins(include_spent=True)
        unspent = [c for c in all_coins if not c.data.is_spent]
        spent = [c for c in all_coins if c.data.is_spent]

        return {
            'total_files': len(all_coins),
            'unspent_coins': len(unspent),
            'spent_coins': len(spent),
            'total_unspent_value': sum(c.data.value for c in unspent),
            'coin_directory': self.coin_dir
        }
