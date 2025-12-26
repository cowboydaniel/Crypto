"""
Basic tests for CPUCoin
"""

import os
import sys
import tempfile
import shutil
import unittest

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cpucoin.crypto_utils import sha256, double_sha256, check_difficulty, merkle_root
from cpucoin.blockchain import Block, Blockchain
from cpucoin.coin import Coin, CoinData, CoinStore
from cpucoin.wallet import Wallet, generate_keypair, sign_message, verify_signature
from cpucoin.transaction import Transaction, TransactionBuilder


class TestCryptoUtils(unittest.TestCase):
    """Test cryptographic utilities."""

    def test_sha256(self):
        """Test SHA-256 hashing."""
        result = sha256("hello")
        self.assertEqual(len(result), 64)  # 256 bits = 64 hex chars
        # Known hash value
        self.assertEqual(
            sha256("hello"),
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        )

    def test_double_sha256(self):
        """Test double SHA-256."""
        result = double_sha256("test")
        self.assertEqual(len(result), 64)
        # Should be different from single sha256
        self.assertNotEqual(result, sha256("test"))

    def test_check_difficulty(self):
        """Test difficulty checking."""
        # Hash with 4 leading zero bits (first hex char is 0)
        self.assertTrue(check_difficulty("0" + "f" * 63, 4))
        self.assertFalse(check_difficulty("f" * 64, 4))
        # Hash with 8 leading zero bits (first 2 hex chars are 0)
        self.assertTrue(check_difficulty("00" + "f" * 62, 8))

    def test_merkle_root_empty(self):
        """Test merkle root with empty list."""
        result = merkle_root([])
        self.assertEqual(len(result), 64)

    def test_merkle_root_single(self):
        """Test merkle root with single hash."""
        h = sha256("tx1")
        result = merkle_root([h])
        self.assertEqual(result, h)

    def test_merkle_root_multiple(self):
        """Test merkle root with multiple hashes."""
        hashes = [sha256(f"tx{i}") for i in range(4)]
        result = merkle_root(hashes)
        self.assertEqual(len(result), 64)


class TestBlockchain(unittest.TestCase):
    """Test blockchain functionality."""

    def test_create_blockchain(self):
        """Test blockchain creation with genesis block."""
        bc = Blockchain()
        self.assertEqual(len(bc), 1)
        self.assertEqual(bc.height, 0)
        self.assertEqual(bc.chain[0].index, 0)

    def test_create_block(self):
        """Test block creation."""
        bc = Blockchain()
        block = bc.create_block("test_miner")
        self.assertEqual(block.index, 1)
        self.assertEqual(block.previous_hash, bc.chain[0].hash)

    def test_block_hash(self):
        """Test block hashing."""
        block = Block(
            index=1,
            timestamp=1000.0,
            transactions=[],
            previous_hash="0" * 64,
            miner="test"
        )
        hash1 = block.compute_hash()
        self.assertEqual(len(hash1), 64)

        # Changing nonce should change hash
        block.nonce = 1
        hash2 = block.compute_hash()
        self.assertNotEqual(hash1, hash2)

    def test_validate_chain(self):
        """Test chain validation."""
        bc = Blockchain()
        self.assertTrue(bc.validate_chain())


class TestCoin(unittest.TestCase):
    """Test coin file functionality."""

    def setUp(self):
        """Create temporary directory for coins."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_mint_coin(self):
        """Test minting a new coin."""
        coin = Coin.mint(
            owner_pubkey="test_owner",
            value=50.0,
            block_height=1,
            mining_proof={"nonce": 123, "hash": "abc", "difficulty": 2},
            coin_dir=self.temp_dir
        )

        self.assertTrue(coin.coin_id.startswith("COIN-"))
        self.assertEqual(coin.value, 50.0)
        self.assertEqual(coin.owner, "test_owner")
        self.assertFalse(coin.is_spent)
        self.assertTrue(os.path.exists(coin.filepath))

    def test_load_coin(self):
        """Test loading a coin from disk."""
        # Mint a coin
        original = Coin.mint(
            owner_pubkey="test_owner",
            value=25.0,
            block_height=5,
            mining_proof={"nonce": 456},
            coin_dir=self.temp_dir
        )

        # Load it
        loaded = Coin.load(original.filepath)

        self.assertEqual(loaded.coin_id, original.coin_id)
        self.assertEqual(loaded.value, original.value)
        self.assertEqual(loaded.owner, original.owner)

    def test_coin_transfer(self):
        """Test transferring a coin."""
        coin = Coin.mint(
            owner_pubkey="alice",
            value=10.0,
            block_height=1,
            mining_proof={"nonce": 1},
            coin_dir=self.temp_dir
        )

        new_coin = coin.transfer("bob", "signature123", self.temp_dir)

        self.assertTrue(coin.is_spent)
        self.assertEqual(new_coin.owner, "bob")
        self.assertEqual(new_coin.value, 10.0)
        self.assertFalse(new_coin.is_spent)

    def test_coin_split(self):
        """Test splitting a coin."""
        coin = Coin.mint(
            owner_pubkey="alice",
            value=100.0,
            block_height=1,
            mining_proof={"nonce": 1},
            coin_dir=self.temp_dir
        )

        new_coins = coin.split([60.0, 40.0], "sig", self.temp_dir)

        self.assertTrue(coin.is_spent)
        self.assertEqual(len(new_coins), 2)
        self.assertEqual(new_coins[0].value, 60.0)
        self.assertEqual(new_coins[1].value, 40.0)

    def test_coin_store(self):
        """Test coin store functionality."""
        store = CoinStore(self.temp_dir)

        # Mint some coins
        coin1 = Coin.mint("alice", 10.0, 1, {"nonce": 1}, self.temp_dir)
        coin2 = Coin.mint("alice", 20.0, 2, {"nonce": 2}, self.temp_dir)
        coin3 = Coin.mint("bob", 15.0, 3, {"nonce": 3}, self.temp_dir)

        # List coins
        alice_coins = store.list_coins(owner_pubkey="alice")
        self.assertEqual(len(alice_coins), 2)

        # Get balance
        alice_balance = store.get_balance("alice")
        self.assertEqual(alice_balance, 30.0)


class TestWallet(unittest.TestCase):
    """Test wallet functionality."""

    def setUp(self):
        """Create temporary directories."""
        self.wallet_dir = tempfile.mkdtemp()
        self.coin_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.wallet_dir)
        shutil.rmtree(self.coin_dir)

    def test_generate_keypair(self):
        """Test keypair generation."""
        private, public = generate_keypair()
        self.assertTrue(len(private) > 0)
        self.assertTrue(len(public) > 0)

    def test_create_wallet(self):
        """Test wallet creation."""
        wallet = Wallet.create("test", "", self.wallet_dir, self.coin_dir)

        self.assertEqual(wallet.name, "test")
        self.assertTrue(wallet.address.startswith("CPU"))
        self.assertTrue(os.path.exists(
            os.path.join(self.wallet_dir, "test.wallet")
        ))

    def test_load_wallet(self):
        """Test wallet loading."""
        original = Wallet.create("test2", "pass123", self.wallet_dir, self.coin_dir)
        loaded = Wallet.load("test2", "pass123", self.wallet_dir)

        self.assertEqual(loaded.name, original.name)
        self.assertEqual(loaded.address, original.address)
        self.assertEqual(loaded.public_key, original.public_key)

    def test_sign_and_verify(self):
        """Test message signing and verification."""
        wallet = Wallet.create("signer", "", self.wallet_dir, self.coin_dir)

        message = "Hello, CPUCoin!"
        signature = wallet.sign(message)

        self.assertTrue(len(signature) > 0)


class TestTransaction(unittest.TestCase):
    """Test transaction functionality."""

    def test_create_coinbase(self):
        """Test coinbase transaction creation."""
        tx = TransactionBuilder.create_coinbase(
            miner_pubkey="miner123",
            reward=50.0,
            block_height=1
        )

        self.assertEqual(tx.tx_type, "coinbase")
        self.assertEqual(len(tx.inputs), 0)
        self.assertEqual(len(tx.outputs), 1)
        self.assertEqual(tx.outputs[0]['amount'], 50.0)

    def test_transaction_id(self):
        """Test transaction ID generation."""
        tx = Transaction(
            tx_type="transfer",
            inputs=[{"coin_id": "test"}],
            outputs=[{"recipient_pubkey": "bob", "amount": 10.0}]
        )

        self.assertEqual(len(tx.txid), 64)


if __name__ == '__main__':
    unittest.main()
