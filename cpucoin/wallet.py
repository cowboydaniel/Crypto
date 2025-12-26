"""
CPUCoin Wallet - Key management and transaction signing
"""

import os
import json
import hashlib
import secrets
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

# Use ecdsa library for digital signatures
try:
    from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError
    ECDSA_AVAILABLE = True
except ImportError:
    ECDSA_AVAILABLE = False

from .crypto_utils import sha256, double_sha256
from .coin import Coin, CoinStore, DEFAULT_COIN_DIR


DEFAULT_WALLET_DIR = os.path.expanduser("~/.cpucoin/wallets")


def generate_keypair() -> Tuple[str, str]:
    """
    Generate a new ECDSA keypair.

    Returns:
        Tuple of (private_key_hex, public_key_hex)
    """
    if ECDSA_AVAILABLE:
        sk = SigningKey.generate(curve=SECP256k1)
        vk = sk.get_verifying_key()
        return sk.to_string().hex(), vk.to_string().hex()
    else:
        # Fallback: use random bytes (less secure, for demo only)
        private_key = secrets.token_hex(32)
        public_key = sha256(private_key)
        return private_key, public_key


def sign_message(private_key_hex: str, message: str) -> str:
    """
    Sign a message with a private key.

    Args:
        private_key_hex: Private key as hex string
        message: Message to sign

    Returns:
        Signature as hex string
    """
    if ECDSA_AVAILABLE:
        sk = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
        message_hash = sha256(message)
        signature = sk.sign(message_hash.encode())
        return signature.hex()
    else:
        # Fallback signature (not cryptographically secure)
        return sha256(private_key_hex + message)


def verify_signature(public_key_hex: str, message: str, signature_hex: str) -> bool:
    """
    Verify a signature.

    Args:
        public_key_hex: Public key as hex string
        message: Original message
        signature_hex: Signature to verify

    Returns:
        True if signature is valid
    """
    if ECDSA_AVAILABLE:
        try:
            vk = VerifyingKey.from_string(bytes.fromhex(public_key_hex), curve=SECP256k1)
            message_hash = sha256(message)
            return vk.verify(bytes.fromhex(signature_hex), message_hash.encode())
        except (BadSignatureError, Exception):
            return False
    else:
        # Fallback verification
        expected = sha256(sha256(public_key_hex) + message)
        return signature_hex == expected


@dataclass
class WalletData:
    """Wallet data stored on disk."""
    name: str
    address: str  # Derived from public key
    public_key: str
    encrypted_private_key: str  # Encrypted with password
    created_at: float
    coin_dir: str = DEFAULT_COIN_DIR


class Wallet:
    """
    CPUCoin Wallet - Manages keys and coins.

    The wallet stores:
    - ECDSA keypair for signing transactions
    - Reference to the coin directory
    - Transaction history
    """

    def __init__(self, name: str, private_key: str, public_key: str,
                 address: str, coin_dir: str = DEFAULT_COIN_DIR):
        self.name = name
        self._private_key = private_key
        self.public_key = public_key
        self.address = address
        self.coin_dir = coin_dir
        self.coin_store = CoinStore(coin_dir)

    @classmethod
    def create(cls, name: str, password: str = "",
               wallet_dir: str = DEFAULT_WALLET_DIR,
               coin_dir: str = DEFAULT_COIN_DIR) -> 'Wallet':
        """
        Create a new wallet.

        Args:
            name: Wallet name
            password: Password to encrypt private key (optional)
            wallet_dir: Directory to store wallet file
            coin_dir: Directory to store coin files

        Returns:
            New Wallet instance
        """
        # Generate keypair
        private_key, public_key = generate_keypair()

        # Generate address from public key
        address = cls.pubkey_to_address(public_key)

        # Create wallet instance
        wallet = cls(name, private_key, public_key, address, coin_dir)

        # Save wallet
        wallet.save(wallet_dir, password)

        return wallet

    @staticmethod
    def pubkey_to_address(public_key: str) -> str:
        """
        Convert public key to wallet address.

        Uses double hash with checksum, similar to Bitcoin.
        """
        # SHA256 of public key
        sha = hashlib.sha256(bytes.fromhex(public_key)).digest()
        # RIPEMD160 of SHA256
        ripe = hashlib.new('ripemd160', sha).digest()
        # Add version byte (0x00 for mainnet)
        versioned = b'\x00' + ripe
        # Checksum (first 4 bytes of double SHA256)
        checksum = hashlib.sha256(hashlib.sha256(versioned).digest()).digest()[:4]
        # Final address in hex
        address_bytes = versioned + checksum
        # Encode as base58 (simplified - using hex for now)
        return "CPU" + address_bytes.hex()

    def save(self, wallet_dir: str = DEFAULT_WALLET_DIR, password: str = ""):
        """Save wallet to disk."""
        Path(wallet_dir).mkdir(parents=True, exist_ok=True)

        # Encrypt private key with password
        if password:
            encrypted_key = self._encrypt_key(self._private_key, password)
        else:
            encrypted_key = self._private_key  # Not recommended!

        import time
        data = {
            'name': self.name,
            'address': self.address,
            'public_key': self.public_key,
            'encrypted_private_key': encrypted_key,
            'created_at': time.time(),
            'coin_dir': self.coin_dir
        }

        filepath = os.path.join(wallet_dir, f"{self.name}.wallet")
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, name: str, password: str = "",
             wallet_dir: str = DEFAULT_WALLET_DIR) -> 'Wallet':
        """Load wallet from disk."""
        filepath = os.path.join(wallet_dir, f"{name}.wallet")

        with open(filepath, 'r') as f:
            data = json.load(f)

        # Decrypt private key
        encrypted_key = data['encrypted_private_key']
        if password:
            private_key = cls._decrypt_key(encrypted_key, password)
        else:
            private_key = encrypted_key

        return cls(
            name=data['name'],
            private_key=private_key,
            public_key=data['public_key'],
            address=data['address'],
            coin_dir=data.get('coin_dir', DEFAULT_COIN_DIR)
        )

    @staticmethod
    def _encrypt_key(key: str, password: str) -> str:
        """Simple XOR encryption (use proper encryption in production!)."""
        key_bytes = bytes.fromhex(key)
        password_hash = hashlib.sha256(password.encode()).digest()
        # Extend password hash to match key length
        extended_pwd = (password_hash * (len(key_bytes) // len(password_hash) + 1))[:len(key_bytes)]
        encrypted = bytes(a ^ b for a, b in zip(key_bytes, extended_pwd))
        return encrypted.hex()

    @staticmethod
    def _decrypt_key(encrypted: str, password: str) -> str:
        """Decrypt key."""
        return Wallet._encrypt_key(encrypted, password)  # XOR is symmetric

    def sign(self, message: str) -> str:
        """Sign a message with the wallet's private key."""
        return sign_message(self._private_key, message)

    def verify(self, message: str, signature: str) -> bool:
        """Verify a signature made by this wallet."""
        return verify_signature(self.public_key, message, signature)

    def get_balance(self) -> float:
        """Get total balance of unspent coins."""
        return self.coin_store.get_balance(self.public_key)

    def list_coins(self, include_spent: bool = False) -> List[Coin]:
        """List all coins owned by this wallet."""
        return self.coin_store.list_coins(
            owner_pubkey=self.public_key,
            include_spent=include_spent
        )

    def send(self, recipient_pubkey: str, amount: float) -> Optional[List[Coin]]:
        """
        Send coins to another wallet.

        Args:
            recipient_pubkey: Recipient's public key
            amount: Amount to send

        Returns:
            List of new coins (recipient's coin and change), or None if failed
        """
        # Find coins to spend
        coins_to_spend = self.coin_store.find_coins_for_amount(self.public_key, amount)
        if not coins_to_spend:
            print(f"Insufficient funds. Balance: {self.get_balance()}, Required: {amount}")
            return None

        total_input = sum(c.data.value for c in coins_to_spend)
        change = total_input - amount

        result_coins = []

        # If we need exact amount and have exact coin, just transfer
        if len(coins_to_spend) == 1 and abs(change) < 0.00000001:
            coin = coins_to_spend[0]
            message = f"transfer:{coin.coin_id}:{recipient_pubkey}:{amount}"
            signature = self.sign(message)
            new_coin = coin.transfer(recipient_pubkey, signature, self.coin_dir)
            return [new_coin]

        # Combine coins if needed, then split
        if len(coins_to_spend) > 1:
            message = f"combine:{[c.coin_id for c in coins_to_spend]}"
            signature = self.sign(message)
            combined = Coin.combine(coins_to_spend, self.public_key, signature, self.coin_dir)
        else:
            combined = coins_to_spend[0]

        # Split into recipient amount and change
        if change > 0.00000001:
            message = f"split:{combined.coin_id}:{amount}:{change}"
            signature = self.sign(message)
            split_coins = combined.split([amount, change], signature, self.coin_dir)

            # Transfer recipient's portion
            recipient_coin = split_coins[0]
            transfer_msg = f"transfer:{recipient_coin.coin_id}:{recipient_pubkey}:{amount}"
            transfer_sig = self.sign(transfer_msg)
            final_recipient_coin = recipient_coin.transfer(recipient_pubkey, transfer_sig, self.coin_dir)

            return [final_recipient_coin, split_coins[1]]  # recipient coin and change
        else:
            # Transfer entire combined coin
            message = f"transfer:{combined.coin_id}:{recipient_pubkey}:{amount}"
            signature = self.sign(message)
            new_coin = combined.transfer(recipient_pubkey, signature, self.coin_dir)
            return [new_coin]

    def export_coin(self, coin_id: str, filepath: str) -> bool:
        """Export a coin to a file for physical transfer."""
        return self.coin_store.export_coin(coin_id, filepath)

    def import_coin(self, filepath: str) -> Optional[Coin]:
        """Import a coin from an external file."""
        return self.coin_store.import_coin(filepath)

    def get_info(self) -> Dict[str, Any]:
        """Get wallet information."""
        coins = self.list_coins()
        return {
            'Name': self.name,
            'Address': self.address,
            'Public Key': self.public_key[:32] + "...",
            'Balance': f"{self.get_balance():.8f} CPU",
            'Coins': len(coins),
            'Coin Directory': self.coin_dir
        }

    def __repr__(self) -> str:
        return f"Wallet({self.name}, {self.address[:20]}..., {self.get_balance():.8f} CPU)"


def list_wallets(wallet_dir: str = DEFAULT_WALLET_DIR) -> List[str]:
    """List all wallet names in the wallet directory."""
    wallet_path = Path(wallet_dir)
    if not wallet_path.exists():
        return []
    return [f.stem for f in wallet_path.glob("*.wallet")]
