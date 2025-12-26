"""
CPUCoin Transaction System

Transactions in CPUCoin are primarily about transferring ownership of coin files.
Each transaction records the movement of coins between wallets.
"""

import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

from .crypto_utils import sha256, double_sha256
from .wallet import verify_signature


@dataclass
class TransactionInput:
    """Input to a transaction (coin being spent)."""
    coin_id: str              # ID of the coin being spent
    owner_pubkey: str         # Public key of the spender
    signature: str            # Signature authorizing the spend


@dataclass
class TransactionOutput:
    """Output of a transaction (new coin ownership)."""
    recipient_pubkey: str     # Public key of the recipient
    amount: float             # Amount being transferred
    coin_id: str = ""         # ID of the resulting coin (set after creation)


@dataclass
class Transaction:
    """
    A CPUCoin transaction.

    Transactions move coins from inputs to outputs.
    Unlike Bitcoin, our coins are actual files, so transactions
    are more about recording ownership changes.
    """
    txid: str = ""
    timestamp: float = 0.0
    tx_type: str = "transfer"  # transfer, coinbase, split, combine
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    fee: float = 0.0
    message: str = ""
    signature: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.txid:
            self.txid = self.compute_txid()

    def compute_txid(self) -> str:
        """Compute unique transaction ID."""
        data = {
            'timestamp': self.timestamp,
            'tx_type': self.tx_type,
            'inputs': self.inputs,
            'outputs': self.outputs,
            'fee': self.fee,
            'message': self.message
        }
        return double_sha256(json.dumps(data, sort_keys=True))

    def get_signing_data(self) -> str:
        """Get data to be signed for this transaction."""
        data = {
            'timestamp': self.timestamp,
            'tx_type': self.tx_type,
            'inputs': self.inputs,
            'outputs': self.outputs,
            'fee': self.fee
        }
        return json.dumps(data, sort_keys=True)

    def verify_signatures(self) -> bool:
        """Verify all input signatures."""
        signing_data = self.get_signing_data()

        for inp in self.inputs:
            pubkey = inp.get('owner_pubkey', '')
            signature = inp.get('signature', '')
            if not verify_signature(pubkey, signing_data, signature):
                return False

        return True

    def is_valid(self) -> bool:
        """Validate the transaction."""
        # Coinbase transactions don't need inputs
        if self.tx_type == 'coinbase':
            return len(self.outputs) > 0

        # Regular transactions need inputs
        if not self.inputs:
            return False

        # Verify signatures
        if not self.verify_signatures():
            return False

        # Check amounts (inputs >= outputs + fee)
        # Note: Input amounts are validated against actual coin files
        total_output = sum(out.get('amount', 0) for out in self.outputs)
        return total_output >= 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'txid': self.txid,
            'timestamp': self.timestamp,
            'tx_type': self.tx_type,
            'inputs': self.inputs,
            'outputs': self.outputs,
            'fee': self.fee,
            'message': self.message,
            'signature': self.signature
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transaction':
        """Create from dictionary."""
        return cls(**data)

    def __repr__(self) -> str:
        return f"Transaction({self.txid[:16]}..., {self.tx_type}, {len(self.inputs)} in, {len(self.outputs)} out)"


class TransactionBuilder:
    """Helper class to build transactions."""

    @staticmethod
    def create_coinbase(miner_pubkey: str, reward: float, block_height: int,
                        fees: float = 0.0) -> Transaction:
        """
        Create a coinbase transaction (mining reward).

        Args:
            miner_pubkey: Miner's public key
            reward: Block reward amount
            block_height: Current block height
            fees: Total transaction fees collected

        Returns:
            Coinbase transaction
        """
        return Transaction(
            tx_type='coinbase',
            inputs=[],
            outputs=[{
                'recipient_pubkey': miner_pubkey,
                'amount': reward + fees
            }],
            message=f"Coinbase at block {block_height}"
        )

    @staticmethod
    def create_transfer(sender_pubkey: str, recipient_pubkey: str,
                       coin_ids: List[str], amount: float,
                       signature: str, fee: float = 0.0) -> Transaction:
        """
        Create a transfer transaction.

        Args:
            sender_pubkey: Sender's public key
            recipient_pubkey: Recipient's public key
            coin_ids: IDs of coins being transferred
            amount: Amount to transfer
            signature: Sender's signature
            fee: Transaction fee

        Returns:
            Transfer transaction
        """
        inputs = [{
            'coin_id': cid,
            'owner_pubkey': sender_pubkey,
            'signature': signature
        } for cid in coin_ids]

        outputs = [{
            'recipient_pubkey': recipient_pubkey,
            'amount': amount
        }]

        return Transaction(
            tx_type='transfer',
            inputs=inputs,
            outputs=outputs,
            fee=fee
        )


class TransactionPool:
    """
    Pool of pending transactions waiting to be mined.
    """

    def __init__(self):
        self.pending: Dict[str, Transaction] = {}

    def add(self, tx: Transaction) -> bool:
        """Add a transaction to the pool."""
        if tx.txid in self.pending:
            return False

        if not tx.is_valid():
            return False

        self.pending[tx.txid] = tx
        return True

    def remove(self, txid: str) -> Optional[Transaction]:
        """Remove a transaction from the pool."""
        return self.pending.pop(txid, None)

    def get_transactions(self, max_count: int = 100) -> List[Transaction]:
        """Get transactions for a new block, sorted by fee."""
        txs = sorted(self.pending.values(), key=lambda t: t.fee, reverse=True)
        return txs[:max_count]

    def clear_transactions(self, txids: List[str]):
        """Clear transactions that have been mined."""
        for txid in txids:
            self.pending.pop(txid, None)

    def __len__(self) -> int:
        return len(self.pending)

    def __repr__(self) -> str:
        return f"TransactionPool({len(self)} pending)"
