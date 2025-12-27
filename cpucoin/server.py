"""
CPUCoin Mining Server

Central server that holds the canonical blockchain and accepts share submissions.
Miners connect via HTTP API to:
- Get the current block to mine
- Submit found shares for validation
- Receive coin files for valid shares

Local storage (on miners):
- Wallet (private keys)
- Coin files (proof of ownership)

Server storage:
- Blockchain (canonical chain)
- Block state (shares claimed, open blocks)
"""

import os
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

from . import config
from .blockchain import Block, Blockchain
from .crypto_utils import check_difficulty, mining_hash


# Server state
_blockchain: Optional[Blockchain] = None
_lock = threading.Lock()
_server_data_dir = os.path.expanduser("~/.cpucoin-server")


def get_blockchain() -> Blockchain:
    """Get or load the server blockchain."""
    global _blockchain
    if _blockchain is None:
        blockchain_path = os.path.join(_server_data_dir, "blockchain.json")
        os.makedirs(_server_data_dir, exist_ok=True)

        if os.path.exists(blockchain_path):
            _blockchain = Blockchain.load(blockchain_path)
            print(f"Loaded blockchain: height {_blockchain.height}")
        else:
            _blockchain = Blockchain()
            print("Created new blockchain")

    return _blockchain


def save_blockchain():
    """Save the blockchain to disk."""
    blockchain_path = os.path.join(_server_data_dir, "blockchain.json")
    get_blockchain().save(blockchain_path)


@dataclass
class ShareSubmission:
    """A share submission from a miner."""
    miner_pubkey: str
    nonce: int
    hash_value: str
    block_index: int
    timestamp: float


@dataclass
class ShareResult:
    """Result of a share submission."""
    success: bool
    message: str
    share_index: int = -1
    is_block_find: bool = False
    bonus_shares: int = 0
    coin_data: Optional[Dict[str, Any]] = None


class MiningServerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the mining server."""

    def log_message(self, format, *args):
        """Custom logging."""
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}")

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        """Send a JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_json(self) -> Optional[Dict[str, Any]]:
        """Read JSON from request body."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            return json.loads(body.decode())
        except Exception:
            return None

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        path = urlparse(self.path).path

        if path == '/':
            self._handle_info()
        elif path == '/block/current':
            self._handle_get_current_block()
        elif path == '/blockchain/info':
            self._handle_blockchain_info()
        elif path == '/blockchain/height':
            self._handle_blockchain_height()
        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        """Handle POST requests."""
        path = urlparse(self.path).path

        if path == '/share/submit':
            self._handle_submit_share()
        elif path == '/blockchain/reset':
            self._handle_reset()
        else:
            self._send_json({'error': 'Not found'}, 404)

    def _handle_info(self):
        """Server info endpoint."""
        blockchain = get_blockchain()
        self._send_json({
            'name': 'CPUCoin Mining Server',
            'version': '2.0.0',
            'blockchain_height': blockchain.height,
            'share_difficulty': blockchain.share_difficulty,
            'block_difficulty': blockchain.block_difficulty,
            'shares_per_block': config.SHARES_PER_BLOCK,
            'share_value': config.SHARE_VALUE,
            'timestamp': time.time()
        })

    def _handle_get_current_block(self):
        """Get the current open block for mining."""
        with _lock:
            blockchain = get_blockchain()
            block = blockchain.get_or_create_open_block()

            # Return block info needed for mining
            self._send_json({
                'block_index': block.index,
                'previous_hash': block.previous_hash,
                'merkle_root': block.merkle_root,
                'timestamp': block.timestamp,
                'share_difficulty': block.share_difficulty,
                'block_difficulty': block.block_difficulty,
                'shares_claimed': len(block.claimed_shares),
                'shares_remaining': block.shares_remaining(),
                'is_closed': block.is_closed,
                'header': block.compute_header()
            })

    def _handle_blockchain_info(self):
        """Get blockchain information."""
        blockchain = get_blockchain()

        open_block_info = None
        if blockchain.current_open_block:
            ob = blockchain.current_open_block
            open_block_info = {
                'index': ob.index,
                'shares_claimed': len(ob.claimed_shares),
                'shares_remaining': ob.shares_remaining(),
                'opened_at': ob.opened_at
            }

        self._send_json({
            'height': blockchain.height,
            'share_difficulty': blockchain.share_difficulty,
            'block_difficulty': blockchain.block_difficulty,
            'block_reward': blockchain.get_block_reward(),
            'share_value': blockchain.get_share_value(),
            'shares_per_block': config.SHARES_PER_BLOCK,
            'pending_transactions': len(blockchain.pending_transactions),
            'current_open_block': open_block_info,
            'recent_blocks': [
                {
                    'index': b.index,
                    'hash': b.hash[:24] + '...',
                    'shares': len(b.claimed_shares) if hasattr(b, 'claimed_shares') else 0,
                    'is_closed': b.is_closed if hasattr(b, 'is_closed') else True
                }
                for b in blockchain.chain[-5:]
            ]
        })

    def _handle_blockchain_height(self):
        """Get just the blockchain height."""
        blockchain = get_blockchain()
        self._send_json({'height': blockchain.height})

    def _handle_submit_share(self):
        """Handle a share submission from a miner."""
        data = self._read_json()
        if not data:
            self._send_json({'error': 'Invalid JSON'}, 400)
            return

        # Validate required fields
        required = ['miner_pubkey', 'nonce', 'hash', 'block_index']
        if not all(k in data for k in required):
            self._send_json({'error': f'Missing fields. Required: {required}'}, 400)
            return

        miner_pubkey = data['miner_pubkey']
        nonce = int(data['nonce'])
        hash_value = data['hash']
        block_index = int(data['block_index'])

        with _lock:
            result = self._process_share_submission(
                miner_pubkey, nonce, hash_value, block_index
            )

        if result.success:
            self._send_json(asdict(result))
        else:
            self._send_json(asdict(result), 400)

    def _process_share_submission(
        self, miner_pubkey: str, nonce: int, hash_value: str, block_index: int
    ) -> ShareResult:
        """Process a share submission."""
        blockchain = get_blockchain()
        block = blockchain.get_or_create_open_block()

        # Check block index matches
        if block_index != block.index:
            return ShareResult(
                success=False,
                message=f"Block index mismatch. Current: {block.index}, submitted: {block_index}"
            )

        # Check if block is still open
        if block.is_closed:
            return ShareResult(
                success=False,
                message="Block is already closed"
            )

        # Verify the hash
        computed_hash = mining_hash(block.compute_header(), nonce, block.previous_hash)
        if computed_hash != hash_value:
            return ShareResult(
                success=False,
                message="Hash verification failed"
            )

        # Check if hash meets share difficulty
        if not check_difficulty(hash_value, block.share_difficulty):
            return ShareResult(
                success=False,
                message=f"Hash does not meet share difficulty {block.share_difficulty}"
            )

        # Check if this is a block find (meets block difficulty)
        is_block_find = check_difficulty(hash_value, block.block_difficulty)

        # Get next available share index
        share_index = block.get_next_share_index()
        if share_index is None:
            return ShareResult(
                success=False,
                message="No shares remaining in block"
            )

        # Claim the share
        if not block.claim_share(share_index, miner_pubkey, nonce, hash_value):
            return ShareResult(
                success=False,
                message="Failed to claim share"
            )

        # Build coin data for the miner
        share_value = blockchain.get_share_value()
        coin_data = {
            'value': share_value,
            'block_height': block.index,
            'share_index': share_index,
            'block_hash': hash_value,
            'is_block_finder': is_block_find,
            'is_bonus_share': False,
            'mining_proof': {
                'nonce': nonce,
                'hash': hash_value,
                'share_difficulty': block.share_difficulty,
                'block_difficulty': block.block_difficulty
            }
        }

        bonus_shares = 0

        # If block find, close the block and award bonus shares
        if is_block_find:
            bonus_shares = block.shares_remaining() - 1  # -1 because we already claimed one
            block.close_block(miner_pubkey, nonce, hash_value)

            # Add block to chain
            blockchain.add_block(block)
            blockchain.current_open_block = None

            # Include bonus share info in coin data
            coin_data['bonus_shares_earned'] = bonus_shares

            print(f"BLOCK FOUND by {miner_pubkey[:16]}! Bonus shares: {bonus_shares}")

        # Save blockchain
        save_blockchain()

        print(f"Share #{share_index} claimed by {miner_pubkey[:16]}... (block find: {is_block_find})")

        return ShareResult(
            success=True,
            message="Share accepted" + (" - BLOCK FOUND!" if is_block_find else ""),
            share_index=share_index,
            is_block_find=is_block_find,
            bonus_shares=bonus_shares,
            coin_data=coin_data
        )

    def _handle_reset(self):
        """Reset the blockchain (admin only, for testing)."""
        global _blockchain
        with _lock:
            _blockchain = Blockchain()
            save_blockchain()
        self._send_json({'message': 'Blockchain reset', 'height': 0})


def run_server(host: str = "0.0.0.0", port: int = 8333):
    """Run the mining server."""
    # Initialize blockchain
    get_blockchain()

    server = HTTPServer((host, port), MiningServerHandler)
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║                 CPUCoin Mining Server                     ║
╠═══════════════════════════════════════════════════════════╣
║  Server running on http://{host}:{port:<5}                   ║
║                                                           ║
║  Endpoints:                                               ║
║    GET  /                    - Server info                ║
║    GET  /block/current       - Get current block to mine  ║
║    GET  /blockchain/info     - Blockchain information     ║
║    POST /share/submit        - Submit a found share       ║
║                                                           ║
║  Miners connect with: --server http://{host}:{port:<5}       ║
╚═══════════════════════════════════════════════════════════╝
    """)

    blockchain = get_blockchain()
    print(f"Blockchain height: {blockchain.height}")
    print(f"Share difficulty: {blockchain.share_difficulty}")
    print(f"Block difficulty: {blockchain.block_difficulty}")
    print(f"Share value: {blockchain.get_share_value():.8f} CPU")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()


if __name__ == '__main__':
    run_server()
