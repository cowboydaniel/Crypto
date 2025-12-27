"""
CPUCoin Central Control Server

A 24/7 central server that acts as:
- The authoritative seed node for the network
- Master blockchain state keeper
- Transaction relay and validation hub
- REST API for monitoring and control
- Optional mining coordinator

Usage:
    python -m cpucoin.coin_control_server [OPTIONS]

    --host          Host to bind to (default: 0.0.0.0)
    --port          P2P port (default: 8333)
    --api-port      REST API port (default: 8080)
    --wallet        Wallet name for mining rewards
    --mine          Enable mining on this server
    --threads       Number of mining threads (default: 4)
    --data-dir      Data directory (default: ~/.cpucoin-server)
    --log-file      Log file path (optional)
    --no-api        Disable REST API
"""

import os
import sys
import json
import time
import signal
import socket
import logging
import argparse
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import traceback

# Import CPUCoin modules
from . import config
from .blockchain import Block, Blockchain
from .coin import Coin, CoinStore
from .transaction import Transaction, TransactionPool
from .wallet import Wallet
from .miner import MultiThreadedMiner
from .node import Node, Peer, Message


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    p2p_port: int = 8333
    api_port: int = 8080
    data_dir: str = "~/.cpucoin-server"
    wallet_name: Optional[str] = None
    enable_mining: bool = False
    mining_threads: int = 4
    enable_api: bool = True
    log_file: Optional[str] = None
    max_peers: int = 100
    sync_interval: int = 5
    stats_interval: int = 60
    backup_interval: int = 300  # 5 minutes
    seed_nodes: List[str] = field(default_factory=list)


# =============================================================================
# Statistics Tracking
# =============================================================================

@dataclass
class ServerStats:
    """Server statistics."""
    start_time: float = 0.0
    blocks_received: int = 0
    blocks_mined: int = 0
    transactions_received: int = 0
    transactions_relayed: int = 0
    peers_connected: int = 0
    peers_disconnected: int = 0
    total_connections: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    errors: int = 0
    last_block_time: float = 0.0
    hash_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        uptime = time.time() - self.start_time if self.start_time else 0
        return {
            'uptime_seconds': uptime,
            'uptime_human': str(timedelta(seconds=int(uptime))),
            'blocks_received': self.blocks_received,
            'blocks_mined': self.blocks_mined,
            'transactions_received': self.transactions_received,
            'transactions_relayed': self.transactions_relayed,
            'peers_connected': self.peers_connected,
            'peers_disconnected': self.peers_disconnected,
            'total_connections': self.total_connections,
            'bytes_sent': self.bytes_sent,
            'bytes_received': self.bytes_received,
            'errors': self.errors,
            'last_block_time': self.last_block_time,
            'hash_rate': self.hash_rate
        }


# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(log_file: Optional[str] = None) -> logging.Logger:
    """Setup logging configuration."""
    logger = logging.getLogger('cpucoin-server')
    logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


# =============================================================================
# REST API Handler
# =============================================================================

class APIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for REST API."""

    server_instance: 'CoinControlServer' = None

    def log_message(self, format, *args):
        """Override to use our logger."""
        if self.server_instance:
            self.server_instance.logger.debug(f"API: {args[0]}")

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _send_error(self, message: str, status: int = 400):
        """Send error response."""
        self._send_json({'error': message}, status)

    def do_GET(self):
        """Handle GET requests."""
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == '/' or path == '/status':
                self._handle_status()
            elif path == '/stats':
                self._handle_stats()
            elif path == '/blockchain':
                self._handle_blockchain(query)
            elif path == '/blockchain/info':
                self._handle_blockchain_info()
            elif path.startswith('/block/'):
                self._handle_block(path.split('/')[-1])
            elif path == '/peers':
                self._handle_peers()
            elif path == '/mempool':
                self._handle_mempool()
            elif path == '/coins':
                self._handle_coins(query)
            elif path.startswith('/balance/'):
                self._handle_balance(path.split('/')[-1])
            elif path == '/health':
                self._handle_health()
            elif path == '/mining':
                self._handle_mining_status()
            else:
                self._send_error('Not found', 404)

        except Exception as e:
            self.server_instance.logger.error(f"API error: {e}")
            self._send_error(str(e), 500)

    def do_POST(self):
        """Handle POST requests."""
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            # Read body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode() if content_length > 0 else '{}'
            data = json.loads(body) if body else {}

            if path == '/transaction':
                self._handle_submit_transaction(data)
            elif path == '/mining/start':
                self._handle_mining_start()
            elif path == '/mining/stop':
                self._handle_mining_stop()
            elif path == '/peer/connect':
                self._handle_peer_connect(data)
            elif path == '/backup':
                self._handle_backup()
            else:
                self._send_error('Not found', 404)

        except Exception as e:
            self.server_instance.logger.error(f"API error: {e}")
            self._send_error(str(e), 500)

    def _handle_status(self):
        """Return server status."""
        server = self.server_instance
        self._send_json({
            'status': 'running',
            'version': Node.VERSION,
            'server_time': datetime.now().isoformat(),
            'blockchain_height': server.blockchain.height,
            'pending_transactions': len(server.tx_pool),
            'connected_peers': len(server.node.peers),
            'mining_active': server.mining_active,
            'hash_rate': server.stats.hash_rate if server.mining_active else 0,
            'uptime': str(timedelta(seconds=int(time.time() - server.stats.start_time)))
        })

    def _handle_stats(self):
        """Return detailed statistics."""
        self._send_json(self.server_instance.stats.to_dict())

    def _handle_blockchain_info(self):
        """Return blockchain information."""
        bc = self.server_instance.blockchain
        self._send_json({
            'height': bc.height,
            'difficulty': bc.difficulty,
            'total_blocks': len(bc.chain),
            'genesis_hash': bc.chain[0].hash if bc.chain else None,
            'tip_hash': bc.chain[-1].hash if bc.chain else None,
            'tip_time': bc.chain[-1].timestamp if bc.chain else None
        })

    def _handle_blockchain(self, query: Dict):
        """Return blockchain blocks."""
        start = int(query.get('start', [0])[0])
        limit = min(int(query.get('limit', [10])[0]), 100)
        bc = self.server_instance.blockchain

        blocks = []
        for block in bc.chain[start:start + limit]:
            blocks.append({
                'index': block.index,
                'hash': block.hash,
                'previous_hash': block.previous_hash,
                'timestamp': block.timestamp,
                'transactions': len(block.transactions),
                'miner': block.miner,
                'nonce': block.nonce
            })

        self._send_json({
            'blocks': blocks,
            'total': len(bc.chain),
            'start': start,
            'limit': limit
        })

    def _handle_block(self, identifier: str):
        """Return specific block."""
        bc = self.server_instance.blockchain

        block = None
        if identifier.isdigit():
            index = int(identifier)
            if 0 <= index < len(bc.chain):
                block = bc.chain[index]
        else:
            # Search by hash
            for b in bc.chain:
                if b.hash == identifier:
                    block = b
                    break

        if block:
            self._send_json(block.to_dict())
        else:
            self._send_error('Block not found', 404)

    def _handle_peers(self):
        """Return connected peers."""
        peers = []
        for addr, peer in self.server_instance.node.peers.items():
            peers.append({
                'address': addr,
                'host': peer.host,
                'port': peer.port,
                'version': peer.version,
                'height': peer.height,
                'last_seen': peer.last_seen
            })
        self._send_json({'peers': peers, 'count': len(peers)})

    def _handle_mempool(self):
        """Return pending transactions."""
        txs = []
        for tx in self.server_instance.tx_pool.transactions:
            txs.append({
                'txid': tx.txid,
                'type': tx.tx_type,
                'fee': tx.fee,
                'timestamp': tx.timestamp
            })
        self._send_json({'transactions': txs, 'count': len(txs)})

    def _handle_coins(self, query: Dict):
        """Return coin information."""
        owner = query.get('owner', [None])[0]
        limit = min(int(query.get('limit', [100])[0]), 1000)

        coins = []
        for coin in self.server_instance.coin_store.list_coins()[:limit]:
            if owner is None or coin.owner_address == owner:
                coins.append({
                    'coin_id': coin.coin_id,
                    'value': coin.value,
                    'owner': coin.owner_address,
                    'is_spent': coin.is_spent,
                    'block_height': coin.block_height
                })

        self._send_json({'coins': coins, 'count': len(coins)})

    def _handle_balance(self, address: str):
        """Return balance for address."""
        balance = self.server_instance.blockchain.get_balance(address)
        self._send_json({
            'address': address,
            'balance': balance,
            'unit': 'CPU'
        })

    def _handle_health(self):
        """Health check endpoint."""
        server = self.server_instance
        healthy = (
            server.is_running and
            server.blockchain.height >= 0 and
            (time.time() - server.stats.start_time) > 10
        )
        self._send_json({
            'healthy': healthy,
            'checks': {
                'server_running': server.is_running,
                'blockchain_valid': server.blockchain.height >= 0,
                'node_active': server.node.is_running
            }
        }, 200 if healthy else 503)

    def _handle_mining_status(self):
        """Return mining status."""
        server = self.server_instance
        self._send_json({
            'active': server.mining_active,
            'threads': server.config.mining_threads,
            'hash_rate': server.stats.hash_rate,
            'blocks_mined': server.stats.blocks_mined,
            'wallet': server.config.wallet_name
        })

    def _handle_submit_transaction(self, data: Dict):
        """Submit a new transaction."""
        try:
            tx = Transaction.from_dict(data)
            if self.server_instance.tx_pool.add(tx):
                self.server_instance.node.broadcast_transaction(tx)
                self._send_json({'success': True, 'txid': tx.txid})
            else:
                self._send_error('Transaction rejected')
        except Exception as e:
            self._send_error(f'Invalid transaction: {e}')

    def _handle_mining_start(self):
        """Start mining."""
        server = self.server_instance
        if not server.config.wallet_name:
            self._send_error('No wallet configured for mining')
            return
        server.start_mining()
        self._send_json({'success': True, 'message': 'Mining started'})

    def _handle_mining_stop(self):
        """Stop mining."""
        self.server_instance.stop_mining()
        self._send_json({'success': True, 'message': 'Mining stopped'})

    def _handle_peer_connect(self, data: Dict):
        """Connect to a peer."""
        host = data.get('host')
        port = data.get('port', config.DEFAULT_PORT)
        if not host:
            self._send_error('Host required')
            return
        success = self.server_instance.node.connect_to_peer(host, port)
        self._send_json({'success': success})

    def _handle_backup(self):
        """Trigger manual backup."""
        self.server_instance.save_state()
        self._send_json({'success': True, 'message': 'Backup complete'})


# =============================================================================
# Main Server Class
# =============================================================================

class CoinControlServer:
    """
    Central Coin Control Server.

    Provides:
    - P2P node functionality (seed node)
    - REST API for monitoring and control
    - Optional mining
    - Automatic state persistence
    - Health monitoring
    - Statistics tracking
    """

    def __init__(self, config: ServerConfig):
        """Initialize the server."""
        self.config = config
        self.is_running = False
        self.mining_active = False

        # Setup data directory
        self.data_dir = Path(os.path.expanduser(config.data_dir))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Setup logging
        self.logger = setup_logging(config.log_file)
        self.logger.info("=" * 60)
        self.logger.info("CPUCoin Central Control Server")
        self.logger.info("=" * 60)

        # Initialize components
        self.blockchain = Blockchain()
        self.coin_store = CoinStore(str(self.data_dir / 'coins'))
        self.tx_pool = TransactionPool()
        self.stats = ServerStats()

        # Load existing state
        self._load_state()

        # Initialize P2P node
        self.node = Node(
            host=config.host,
            port=config.p2p_port,
            blockchain=self.blockchain,
            coin_store=self.coin_store
        )
        self.node.tx_pool = self.tx_pool

        # Setup callbacks
        self.node.on_block_received = self._on_block_received
        self.node.on_tx_received = self._on_tx_received
        self.node.on_peer_connected = self._on_peer_connected

        # Mining
        self.miner: Optional[MultiThreadedMiner] = None
        self.wallet: Optional[Wallet] = None
        self._mining_thread: Optional[threading.Thread] = None

        # API server
        self.api_server: Optional[HTTPServer] = None
        self._api_thread: Optional[threading.Thread] = None

        # Background threads
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

        self.logger.info(f"Data directory: {self.data_dir}")
        self.logger.info(f"Blockchain height: {self.blockchain.height}")

    def _load_state(self):
        """Load saved state from disk."""
        blockchain_file = self.data_dir / 'blockchain.json'
        if blockchain_file.exists():
            try:
                self.blockchain = Blockchain.load(str(blockchain_file))
                self.logger.info(f"Loaded blockchain with {len(self.blockchain.chain)} blocks")
            except Exception as e:
                self.logger.error(f"Failed to load blockchain: {e}")
                self.blockchain = Blockchain()

    def save_state(self):
        """Save current state to disk."""
        try:
            blockchain_file = self.data_dir / 'blockchain.json'
            self.blockchain.save(str(blockchain_file))
            self.logger.debug("State saved successfully")
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
            self.stats.errors += 1

    def start(self):
        """Start the server."""
        self.logger.info("Starting server...")
        self.is_running = True
        self.stats.start_time = time.time()

        # Start P2P node
        self.node.start()
        self.logger.info(f"P2P node listening on {self.config.host}:{self.config.p2p_port}")

        # Start REST API
        if self.config.enable_api:
            self._start_api_server()
            self.logger.info(f"REST API listening on {self.config.host}:{self.config.api_port}")

        # Connect to seed nodes
        for seed in self.config.seed_nodes:
            try:
                host, port = seed.split(':')
                self.node.connect_to_peer(host, int(port))
            except Exception as e:
                self.logger.warning(f"Failed to connect to seed {seed}: {e}")

        # Start background tasks
        self._start_background_tasks()

        # Load wallet and start mining if configured
        if self.config.wallet_name and self.config.enable_mining:
            self._load_wallet()
            self.start_mining()

        self.logger.info("Server started successfully")
        self.logger.info(f"API endpoint: http://{self.config.host}:{self.config.api_port}/")

    def stop(self):
        """Stop the server."""
        self.logger.info("Stopping server...")
        self.is_running = False

        # Stop mining
        self.stop_mining()

        # Stop P2P node
        self.node.stop()

        # Stop API server
        if self.api_server:
            self.api_server.shutdown()

        # Save state
        self.save_state()

        self.logger.info("Server stopped")

    def _start_api_server(self):
        """Start the REST API server."""
        APIHandler.server_instance = self
        self.api_server = HTTPServer(
            (self.config.host, self.config.api_port),
            APIHandler
        )
        self._api_thread = threading.Thread(
            target=self.api_server.serve_forever,
            name='api-server'
        )
        self._api_thread.daemon = True
        self._api_thread.start()

    def _start_background_tasks(self):
        """Start background maintenance tasks."""
        # Stats collection
        stats_thread = threading.Thread(
            target=self._stats_loop,
            name='stats-collector'
        )
        stats_thread.daemon = True
        stats_thread.start()
        self._threads.append(stats_thread)

        # Auto-backup
        backup_thread = threading.Thread(
            target=self._backup_loop,
            name='auto-backup'
        )
        backup_thread.daemon = True
        backup_thread.start()
        self._threads.append(backup_thread)

        # Health monitor
        health_thread = threading.Thread(
            target=self._health_loop,
            name='health-monitor'
        )
        health_thread.daemon = True
        health_thread.start()
        self._threads.append(health_thread)

    def _stats_loop(self):
        """Collect statistics periodically."""
        while self.is_running:
            time.sleep(self.config.stats_interval)
            try:
                self.stats.peers_connected = len(self.node.peers)
                self.logger.debug(
                    f"Stats: height={self.blockchain.height}, "
                    f"peers={len(self.node.peers)}, "
                    f"mempool={len(self.tx_pool)}"
                )
            except Exception as e:
                self.logger.error(f"Stats error: {e}")

    def _backup_loop(self):
        """Auto-backup state periodically."""
        while self.is_running:
            time.sleep(self.config.backup_interval)
            try:
                self.save_state()
            except Exception as e:
                self.logger.error(f"Backup error: {e}")

    def _health_loop(self):
        """Monitor server health."""
        while self.is_running:
            time.sleep(30)
            try:
                # Check blockchain validity
                if not self.blockchain.validate_chain():
                    self.logger.error("Blockchain validation failed!")
                    self.stats.errors += 1

                # Check for stale blocks (no new block in 10 minutes)
                if self.stats.last_block_time > 0:
                    stale_time = time.time() - self.stats.last_block_time
                    if stale_time > 600:  # 10 minutes
                        self.logger.warning(
                            f"No new blocks in {int(stale_time)}s"
                        )

            except Exception as e:
                self.logger.error(f"Health check error: {e}")

    def _load_wallet(self):
        """Load the configured wallet."""
        if not self.config.wallet_name:
            return

        try:
            wallet_file = Path.home() / '.cpucoin' / 'wallets' / f'{self.config.wallet_name}.wallet'
            if wallet_file.exists():
                self.wallet = Wallet.load(self.config.wallet_name)
                self.logger.info(f"Loaded wallet: {self.config.wallet_name}")
            else:
                self.logger.warning(f"Wallet not found: {self.config.wallet_name}")
        except Exception as e:
            self.logger.error(f"Failed to load wallet: {e}")

    def start_mining(self):
        """Start mining."""
        if self.mining_active:
            return

        if not self.wallet:
            self._load_wallet()

        if not self.wallet:
            self.logger.error("Cannot start mining: no wallet loaded")
            return

        self.mining_active = True
        self._mining_thread = threading.Thread(
            target=self._mining_loop,
            name='miner'
        )
        self._mining_thread.daemon = True
        self._mining_thread.start()
        self.logger.info(f"Mining started with {self.config.mining_threads} threads")

    def stop_mining(self):
        """Stop mining."""
        if not self.mining_active:
            return

        self.mining_active = False
        if self.miner:
            self.miner.stop()
        self.logger.info("Mining stopped")

    def _mining_loop(self):
        """Mining loop."""
        self.miner = MultiThreadedMiner(
            blockchain=self.blockchain,
            wallet=self.wallet,
            coin_store=self.coin_store,
            num_threads=self.config.mining_threads
        )

        while self.mining_active and self.is_running:
            try:
                result = self.miner.mine_block()
                if result and result.block:
                    self.stats.blocks_mined += 1
                    self.stats.last_block_time = time.time()
                    self.stats.hash_rate = result.hash_rate

                    self.logger.info(
                        f"Mined block #{result.block.index} "
                        f"({result.hash_rate:.2f} H/s)"
                    )

                    # Broadcast to network
                    self.node.broadcast_block(result.block)

                    # Save state
                    self.save_state()

            except Exception as e:
                self.logger.error(f"Mining error: {e}")
                self.stats.errors += 1
                time.sleep(5)

    def _on_block_received(self, block: Block):
        """Handle received block."""
        self.stats.blocks_received += 1
        self.stats.last_block_time = time.time()
        self.logger.info(f"Received block #{block.index} from network")

        # Relay to other peers
        self.node.broadcast_block(block)

        # Save state
        self.save_state()

    def _on_tx_received(self, tx: Transaction):
        """Handle received transaction."""
        self.stats.transactions_received += 1
        self.logger.debug(f"Received transaction {tx.txid[:16]}...")

        # Relay to other peers
        self.node.broadcast_transaction(tx)
        self.stats.transactions_relayed += 1

    def _on_peer_connected(self, peer: Peer):
        """Handle new peer connection."""
        self.stats.total_connections += 1
        self.logger.info(f"Peer connected: {peer.address} (height={peer.height})")

    def run_forever(self):
        """Run the server until interrupted."""
        self.start()

        # Setup signal handlers
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, shutting down...")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Keep main thread alive
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='CPUCoin Central Control Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start basic server
  python -m cpucoin.coin_control_server

  # Start with mining enabled
  python -m cpucoin.coin_control_server --mine --wallet myserver

  # Start on custom ports
  python -m cpucoin.coin_control_server --port 9333 --api-port 9080

  # Start with seed nodes
  python -m cpucoin.coin_control_server --seed node1.example.com:8333

API Endpoints:
  GET  /              - Server status
  GET  /health        - Health check
  GET  /stats         - Detailed statistics
  GET  /blockchain    - List blocks
  GET  /block/<id>    - Get specific block
  GET  /peers         - Connected peers
  GET  /mempool       - Pending transactions
  GET  /balance/<addr> - Address balance
  GET  /mining        - Mining status
  POST /transaction   - Submit transaction
  POST /mining/start  - Start mining
  POST /mining/stop   - Stop mining
  POST /peer/connect  - Connect to peer
  POST /backup        - Manual backup
        """
    )

    parser.add_argument('--host', default='0.0.0.0',
                        help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8333,
                        help='P2P port (default: 8333)')
    parser.add_argument('--api-port', type=int, default=8080,
                        help='REST API port (default: 8080)')
    parser.add_argument('--wallet', type=str,
                        help='Wallet name for mining rewards')
    parser.add_argument('--mine', action='store_true',
                        help='Enable mining')
    parser.add_argument('--threads', type=int, default=4,
                        help='Mining threads (default: 4)')
    parser.add_argument('--data-dir', default='~/.cpucoin-server',
                        help='Data directory (default: ~/.cpucoin-server)')
    parser.add_argument('--log-file', type=str,
                        help='Log file path')
    parser.add_argument('--no-api', action='store_true',
                        help='Disable REST API')
    parser.add_argument('--seed', action='append', dest='seeds',
                        help='Seed node (host:port), can be specified multiple times')

    args = parser.parse_args()

    # Create config
    server_config = ServerConfig(
        host=args.host,
        p2p_port=args.port,
        api_port=args.api_port,
        data_dir=args.data_dir,
        wallet_name=args.wallet,
        enable_mining=args.mine,
        mining_threads=args.threads,
        enable_api=not args.no_api,
        log_file=args.log_file,
        seed_nodes=args.seeds or []
    )

    # Create and run server
    server = CoinControlServer(server_config)
    server.run_forever()


if __name__ == '__main__':
    main()
