"""
CPUCoin P2P Node

Simple peer-to-peer networking for:
- Block propagation
- Transaction broadcasting
- Coin file synchronization
- Peer discovery
"""

import os
import json
import socket
import threading
import time
from typing import Dict, Any, List, Optional, Set, Callable
from dataclasses import dataclass
from pathlib import Path

from . import config
from .blockchain import Block, Blockchain
from .coin import Coin, CoinStore
from .transaction import Transaction, TransactionPool


@dataclass
class Peer:
    """Information about a network peer."""
    host: str
    port: int
    last_seen: float = 0.0
    version: str = ""
    height: int = 0

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


class Message:
    """Network message types."""
    HELLO = "hello"
    PING = "ping"
    PONG = "pong"
    GET_BLOCKS = "get_blocks"
    BLOCKS = "blocks"
    NEW_BLOCK = "new_block"
    NEW_TX = "new_tx"
    GET_PEERS = "get_peers"
    PEERS = "peers"
    GET_COINS = "get_coins"
    COINS = "coins"


class Node:
    """
    CPUCoin P2P Node.

    Handles network communication with other nodes for:
    - Synchronizing the blockchain
    - Broadcasting new blocks and transactions
    - Sharing coin files
    - Peer discovery
    """

    VERSION = "1.0.0"

    def __init__(self, host: str = "0.0.0.0", port: int = config.DEFAULT_PORT,
                 blockchain: Optional[Blockchain] = None,
                 coin_store: Optional[CoinStore] = None):
        """
        Initialize the node.

        Args:
            host: Host to bind to
            port: Port to listen on
            blockchain: Blockchain instance
            coin_store: Coin storage instance
        """
        self.host = host
        self.port = port
        self.blockchain = blockchain or Blockchain()
        self.coin_store = coin_store or CoinStore()
        self.tx_pool = TransactionPool()

        # Networking
        self.peers: Dict[str, Peer] = {}
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False

        # Threading
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

        # Callbacks
        self.on_block_received: Optional[Callable[[Block], None]] = None
        self.on_tx_received: Optional[Callable[[Transaction], None]] = None
        self.on_peer_connected: Optional[Callable[[Peer], None]] = None

    def start(self):
        """Start the node server."""
        self.is_running = True

        # Start server thread
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(config.MAX_PEERS)

        server_thread = threading.Thread(target=self._accept_connections)
        server_thread.daemon = True
        server_thread.start()
        self._threads.append(server_thread)

        # Start maintenance thread
        maint_thread = threading.Thread(target=self._maintenance_loop)
        maint_thread.daemon = True
        maint_thread.start()
        self._threads.append(maint_thread)

        print(f"Node started on {self.host}:{self.port}")

    def stop(self):
        """Stop the node."""
        self.is_running = False
        if self.server_socket:
            self.server_socket.close()
        print("Node stopped")

    def _accept_connections(self):
        """Accept incoming connections."""
        while self.is_running:
            try:
                client_socket, address = self.server_socket.accept()
                handler = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, address)
                )
                handler.daemon = True
                handler.start()
            except Exception as e:
                if self.is_running:
                    print(f"Error accepting connection: {e}")

    def _handle_client(self, client_socket: socket.socket, address):
        """Handle a client connection."""
        try:
            while self.is_running:
                data = self._receive_message(client_socket)
                if not data:
                    break

                response = self._handle_message(data, address)
                if response:
                    self._send_message(client_socket, response)
        except Exception as e:
            print(f"Error handling client {address}: {e}")
        finally:
            client_socket.close()

    def _receive_message(self, sock: socket.socket) -> Optional[Dict[str, Any]]:
        """Receive a JSON message from socket."""
        try:
            # First receive message length (4 bytes)
            length_data = sock.recv(4)
            if not length_data:
                return None
            length = int.from_bytes(length_data, 'big')

            # Receive message data
            data = b''
            while len(data) < length:
                chunk = sock.recv(min(4096, length - len(data)))
                if not chunk:
                    return None
                data += chunk

            return json.loads(data.decode('utf-8'))
        except Exception:
            return None

    def _send_message(self, sock: socket.socket, message: Dict[str, Any]):
        """Send a JSON message to socket."""
        try:
            data = json.dumps(message).encode('utf-8')
            length = len(data).to_bytes(4, 'big')
            sock.sendall(length + data)
        except Exception as e:
            print(f"Error sending message: {e}")

    def _handle_message(self, message: Dict[str, Any], address) -> Optional[Dict[str, Any]]:
        """Handle an incoming message."""
        msg_type = message.get('type')

        if msg_type == Message.HELLO:
            # New peer introduction
            peer = Peer(
                host=address[0],
                port=message.get('port', config.DEFAULT_PORT),
                version=message.get('version', ''),
                height=message.get('height', 0),
                last_seen=time.time()
            )
            self.peers[peer.address] = peer

            if self.on_peer_connected:
                self.on_peer_connected(peer)

            return {
                'type': Message.HELLO,
                'version': self.VERSION,
                'height': self.blockchain.height,
                'port': self.port
            }

        elif msg_type == Message.PING:
            return {'type': Message.PONG, 'timestamp': time.time()}

        elif msg_type == Message.GET_BLOCKS:
            # Send blocks from specified height
            start = message.get('start', 0)
            blocks = [b.to_dict() for b in self.blockchain.chain[start:start + 100]]
            return {'type': Message.BLOCKS, 'blocks': blocks}

        elif msg_type == Message.NEW_BLOCK:
            # New block announcement
            block = Block.from_dict(message.get('block', {}))
            if self.blockchain.add_block(block):
                if self.on_block_received:
                    self.on_block_received(block)
            return None

        elif msg_type == Message.NEW_TX:
            # New transaction
            tx = Transaction.from_dict(message.get('transaction', {}))
            if self.tx_pool.add(tx):
                if self.on_tx_received:
                    self.on_tx_received(tx)
            return None

        elif msg_type == Message.GET_PEERS:
            peers = [{'host': p.host, 'port': p.port} for p in self.peers.values()]
            return {'type': Message.PEERS, 'peers': peers}

        return None

    def connect_to_peer(self, host: str, port: int) -> bool:
        """Connect to a peer node."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))

            # Send hello
            hello = {
                'type': Message.HELLO,
                'version': self.VERSION,
                'height': self.blockchain.height,
                'port': self.port
            }
            self._send_message(sock, hello)

            # Receive response
            response = self._receive_message(sock)
            if response and response.get('type') == Message.HELLO:
                peer = Peer(
                    host=host,
                    port=port,
                    version=response.get('version', ''),
                    height=response.get('height', 0),
                    last_seen=time.time()
                )
                self.peers[peer.address] = peer
                print(f"Connected to peer: {peer.address}")
                return True

        except Exception as e:
            print(f"Failed to connect to {host}:{port}: {e}")

        return False

    def broadcast_block(self, block: Block):
        """Broadcast a new block to all peers."""
        message = {
            'type': Message.NEW_BLOCK,
            'block': block.to_dict()
        }
        self._broadcast(message)

    def broadcast_transaction(self, tx: Transaction):
        """Broadcast a new transaction to all peers."""
        message = {
            'type': Message.NEW_TX,
            'transaction': tx.to_dict()
        }
        self._broadcast(message)

    def _broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all peers."""
        for peer in list(self.peers.values()):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect((peer.host, peer.port))
                self._send_message(sock, message)
                sock.close()
            except Exception:
                pass  # Peer unavailable

    def sync_blockchain(self):
        """Synchronize blockchain with peers."""
        for peer in list(self.peers.values()):
            if peer.height > self.blockchain.height:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(30)
                    sock.connect((peer.host, peer.port))

                    # Request blocks
                    request = {
                        'type': Message.GET_BLOCKS,
                        'start': self.blockchain.height
                    }
                    self._send_message(sock, request)

                    response = self._receive_message(sock)
                    if response and response.get('type') == Message.BLOCKS:
                        for block_data in response.get('blocks', []):
                            block = Block.from_dict(block_data)
                            self.blockchain.add_block(block)

                    sock.close()
                    print(f"Synced to height {self.blockchain.height}")

                except Exception as e:
                    print(f"Sync failed with {peer.address}: {e}")

    def _maintenance_loop(self):
        """Periodic maintenance tasks."""
        while self.is_running:
            time.sleep(config.SYNC_INTERVAL)

            # Ping peers
            dead_peers = []
            for address, peer in list(self.peers.items()):
                if time.time() - peer.last_seen > 60:
                    dead_peers.append(address)

            for address in dead_peers:
                del self.peers[address]

            # Sync blockchain
            if self.peers:
                self.sync_blockchain()

    def get_info(self) -> Dict[str, Any]:
        """Get node information."""
        return {
            'version': self.VERSION,
            'host': self.host,
            'port': self.port,
            'peers': len(self.peers),
            'blockchain_height': self.blockchain.height,
            'pending_transactions': len(self.tx_pool),
            'is_running': self.is_running
        }
