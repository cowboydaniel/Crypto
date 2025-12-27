#!/usr/bin/env python3
"""
CPUCoin Command Line Interface

Block Shares Mining System:
- Each block contains 1000 shares (coinlets) worth ~2.38095238 CPU each initially
- Mine individual shares quickly, or find full blocks for bonus shares
- Full blocks take ~15 minutes on powerful CPUs

Usage:
    cpucoin mine [--shares=<n>] [--wallet=<name>] [--threads=<n>]
    cpucoin wallet create <name> [--password=<pwd>]
    cpucoin wallet info [<name>]
    cpucoin wallet list
    cpucoin wallet balance [<name>]
    cpucoin send <recipient> <amount> [--wallet=<name>]
    cpucoin coins list [--all]
    cpucoin coins info <coin_id>
    cpucoin coins export <coin_id> <filepath>
    cpucoin coins import <filepath>
    cpucoin blockchain info
    cpucoin server start [--port=<port>]
    cpucoin server info <url>
    cpucoin node start [--port=<port>]
    cpucoin node connect <host:port>

Server-based Mining (recommended for multi-user):
    cpucoin mine --server http://your-server:8333 --shares 10
"""

import os
import sys
import argparse
import getpass
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cpucoin.blockchain import Blockchain
from cpucoin.wallet import Wallet, list_wallets, DEFAULT_WALLET_DIR
from cpucoin.coin import Coin, CoinStore, DEFAULT_COIN_DIR
from cpucoin.miner import ShareMiner, MultiThreadedShareMiner, quick_mine
from cpucoin.mining_client import MiningClient, ServerShareMiner
from cpucoin.server import run_server
from cpucoin.node import Node
from cpucoin import config


def print_header():
    """Print the CPUCoin header."""
    print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     ██████╗██████╗ ██╗   ██╗ ██████╗ ██████╗ ██╗███╗   ██╗║
║    ██╔════╝██╔══██╗██║   ██║██╔════╝██╔═══██╗██║████╗  ██║║
║    ██║     ██████╔╝██║   ██║██║     ██║   ██║██║██╔██╗ ██║║
║    ██║     ██╔═══╝ ██║   ██║██║     ██║   ██║██║██║╚██╗██║║
║    ╚██████╗██║     ╚██████╔╝╚██████╗╚██████╔╝██║██║ ╚████║║
║     ╚═════╝╚═╝      ╚═════╝  ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝║
║                                                           ║
║           CPU-Minable Cryptocurrency v2.0.0               ║
║     Block Shares • Physical coins • Multi-user mining     ║
╚═══════════════════════════════════════════════════════════╝
    """)


def cmd_mine(args):
    """Mine shares (and occasionally find blocks for bonus)."""
    print_header()

    wallet_name = args.wallet or "default"
    password = args.password or ""
    num_shares = args.shares or 0
    num_threads = args.threads or 0
    server_url = args.server

    # Load or create wallet
    if wallet_name in list_wallets():
        if not password and args.password is None:
            password = getpass.getpass(f"Wallet password (or enter for none): ")
        try:
            wallet = Wallet.load(wallet_name, password)
        except Exception as e:
            print(f"Error loading wallet: {e}")
            return 1
    else:
        print(f"Creating new wallet: {wallet_name}")
        wallet = Wallet.create(wallet_name, password)

    print(f"\n📁 Wallet: {wallet.name}")
    print(f"📍 Address: {wallet.address}")
    print(f"💰 Current balance: {wallet.get_balance():.8f} CPU")

    # Server-based mining
    if server_url:
        return cmd_mine_server(wallet, server_url, num_shares)

    # Local mining (legacy mode)
    blockchain_path = os.path.expanduser("~/.cpucoin/blockchain.json")
    if os.path.exists(blockchain_path):
        blockchain = Blockchain.load(blockchain_path)
        print(f"📦 Blockchain loaded: height {blockchain.height}")
    else:
        blockchain = Blockchain()
        print(f"📦 New blockchain created")

    # Show share info
    print(f"\n📋 Share Mining Info:")
    print(f"   Shares per block: {config.SHARES_PER_BLOCK}")
    print(f"   Share value: {config.SHARE_VALUE:.8f} CPU")
    print(f"   Share difficulty: {blockchain.share_difficulty}")
    print(f"   Block difficulty: {blockchain.block_difficulty} (bonus shares!)")

    # Create miner
    if num_threads > 1:
        miner = MultiThreadedShareMiner(wallet, blockchain, num_threads=num_threads)
    else:
        miner = ShareMiner(wallet, blockchain)

    try:
        if num_shares > 0:
            print(f"\n⛏️  Mining {num_shares} share(s)...\n")
        else:
            print(f"\n⛏️  Mining continuously (Ctrl+C to stop)...\n")

        results = miner.mine_continuous(num_shares=num_shares, verbose=True)

        # Save blockchain
        blockchain.save(blockchain_path)
        print(f"\n💾 Blockchain saved to {blockchain_path}")

        # Summary
        successful = [r for r in results if r.success]
        blocks_found = sum(1 for r in successful if r.is_block_find)
        total_earned = sum(r.coin.value for r in successful if r.coin)

        print(f"\n📊 Session Summary:")
        print(f"   Shares mined: {len(successful)}")
        print(f"   Blocks found: {blocks_found}")
        print(f"   Total earned: {total_earned:.8f} CPU")
        print(f"   Wallet balance: {wallet.get_balance():.8f} CPU")

    except KeyboardInterrupt:
        print("\n\n⏹️  Mining stopped by user")
        miner.stop()
        blockchain.save(blockchain_path)

    return 0


def cmd_mine_server(wallet, server_url: str, num_shares: int):
    """Mine shares using a remote server."""
    print(f"\n🌐 Connecting to server: {server_url}")

    # Check server connection
    client = MiningClient(server_url)
    info = client.get_server_info()

    if not info:
        print(f"❌ Failed to connect to server: {client.last_error}")
        return 1

    print(f"✅ Connected to {info.get('name', 'CPUCoin Server')}")
    print(f"   Blockchain height: {info.get('blockchain_height', 0)}")
    print(f"   Share difficulty: {info.get('share_difficulty', 0)}")
    print(f"   Block difficulty: {info.get('block_difficulty', 0)}")
    print(f"   Share value: {info.get('share_value', 0):.8f} CPU")

    # Create server-connected miner
    miner = ServerShareMiner(wallet, server_url)

    try:
        if num_shares > 0:
            print(f"\n⛏️  Mining {num_shares} share(s)...\n")
        else:
            print(f"\n⛏️  Mining continuously (Ctrl+C to stop)...\n")

        results = miner.mine_continuous(num_shares=num_shares, verbose=True)

        # Summary
        successful = [r for r in results if r.success]
        blocks_found = sum(1 for r in successful if r.is_block_find)
        bonus_shares = sum(r.bonus_shares for r in successful)

        print(f"\n📊 Session Summary:")
        print(f"   Shares mined: {len(successful)}")
        print(f"   Blocks found: {blocks_found}")
        print(f"   Bonus shares: {bonus_shares}")
        print(f"   Wallet balance: {wallet.get_balance():.8f} CPU")

    except KeyboardInterrupt:
        print("\n\n⏹️  Mining stopped by user")
        miner.stop()

    return 0


def cmd_wallet_create(args):
    """Create a new wallet."""
    name = args.name
    password = args.password

    if not password:
        password = getpass.getpass("Enter wallet password (or enter for none): ")
        if password:
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Passwords don't match!")
                return 1

    if name in list_wallets():
        print(f"Wallet '{name}' already exists!")
        return 1

    wallet = Wallet.create(name, password)

    print(f"\n✅ Wallet created successfully!")
    print(f"\n📁 Name: {wallet.name}")
    print(f"📍 Address: {wallet.address}")
    print(f"🔑 Public Key: {wallet.public_key}")
    print(f"\n⚠️  IMPORTANT: Keep your password safe! Lost passwords cannot be recovered.")

    return 0


def cmd_wallet_info(args):
    """Show wallet information."""
    name = args.name or "default"
    password = args.password or ""

    if name not in list_wallets():
        print(f"Wallet '{name}' not found!")
        return 1

    try:
        wallet = Wallet.load(name, password)
    except Exception as e:
        print(f"Error loading wallet: {e}")
        return 1

    info = wallet.get_info()
    print(f"\n📁 Wallet Information:")
    print("-" * 40)
    for key, value in info.items():
        print(f"  {key}: {value}")

    coins = wallet.list_coins()
    if coins:
        print(f"\n💰 Coins ({len(coins)}):")
        print("-" * 40)
        for coin in coins[:10]:
            print(f"  {coin.coin_id[:24]}... : {coin.value:.8f} CPU")
        if len(coins) > 10:
            print(f"  ... and {len(coins) - 10} more")

    return 0


def cmd_wallet_list(args):
    """List all wallets."""
    wallets = list_wallets()

    if not wallets:
        print("No wallets found. Create one with: cpucoin wallet create <name>")
        return 0

    print(f"\n📁 Wallets ({len(wallets)}):")
    print("-" * 40)
    for name in wallets:
        try:
            wallet = Wallet.load(name, "")
            print(f"  {name}: {wallet.get_balance():.8f} CPU")
        except Exception:
            print(f"  {name}: (encrypted)")

    return 0


def cmd_wallet_balance(args):
    """Show wallet balance."""
    name = args.name or "default"
    password = args.password or ""

    if name not in list_wallets():
        print(f"Wallet '{name}' not found!")
        return 1

    try:
        wallet = Wallet.load(name, password)
        print(f"\n💰 Balance: {wallet.get_balance():.8f} CPU")
        print(f"   Coins: {len(wallet.list_coins())}")
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


def cmd_send(args):
    """Send coins to another address."""
    wallet_name = args.wallet or "default"
    password = args.password or ""
    recipient = args.recipient
    amount = float(args.amount)

    try:
        wallet = Wallet.load(wallet_name, password)
    except Exception as e:
        print(f"Error loading wallet: {e}")
        return 1

    balance = wallet.get_balance()
    if balance < amount:
        print(f"Insufficient funds! Balance: {balance:.8f} CPU, Required: {amount:.8f} CPU")
        return 1

    print(f"\n📤 Sending {amount:.8f} CPU")
    print(f"   From: {wallet.address[:30]}...")
    print(f"   To: {recipient[:30]}...")

    result = wallet.send(recipient, amount)

    if result:
        print(f"\n✅ Transaction successful!")
        print(f"   New balance: {wallet.get_balance():.8f} CPU")
        for coin in result:
            print(f"   Created coin: {coin.coin_id}")
    else:
        print(f"\n❌ Transaction failed!")
        return 1

    return 0


def cmd_coins_list(args):
    """List all coins (shares)."""
    coin_store = CoinStore()
    include_spent = args.all

    coins = coin_store.list_coins(include_spent=include_spent)

    if not coins:
        print("No coins found. Mine some with: cpucoin mine")
        return 0

    print(f"\n💰 Coins/Shares ({len(coins)}):")
    print("-" * 60)
    for coin in coins:
        status = "SPENT" if coin.is_spent else "VALID"

        # Determine coin type
        if coin.data.is_bonus_share:
            coin_type = "BONUS"
        elif coin.data.is_block_finder:
            coin_type = "BLOCK"
        else:
            coin_type = "SHARE"

        print(f"  {coin.coin_id[:32]}...")
        print(f"    Value: {coin.value:.8f} CPU | Type: {coin_type} | Status: {status}")
        print(f"    Block: #{coin.data.block_height} | Share: #{coin.data.share_index}")
        print()

    stats = coin_store.stats()
    print(f"📊 Statistics:")
    print(f"   Total files: {stats['total_files']}")
    print(f"   Unspent: {stats['unspent_coins']} ({stats['total_unspent_value']:.8f} CPU)")
    print(f"   Spent: {stats['spent_coins']}")

    return 0


def cmd_coins_info(args):
    """Show coin information."""
    coin_store = CoinStore()
    coin = coin_store.get_coin(args.coin_id)

    if not coin:
        print(f"Coin not found: {args.coin_id}")
        return 1

    info = coin.get_info()
    print(f"\n💰 Coin Information:")
    print("-" * 40)
    for key, value in info.items():
        print(f"  {key}: {value}")

    print(f"\n📜 History:")
    for i, h in enumerate(coin.data.history):
        print(f"  {i + 1}. {h.get('action', 'unknown')} at {h.get('timestamp', 0):.0f}")

    return 0


def cmd_coins_export(args):
    """Export a coin to a file."""
    coin_store = CoinStore()

    if coin_store.export_coin(args.coin_id, args.filepath):
        print(f"✅ Coin exported to: {args.filepath}")
        return 0
    else:
        print(f"❌ Failed to export coin: {args.coin_id}")
        return 1


def cmd_coins_import(args):
    """Import a coin from a file."""
    coin_store = CoinStore()

    coin = coin_store.import_coin(args.filepath)
    if coin:
        print(f"✅ Coin imported: {coin.coin_id}")
        print(f"   Value: {coin.value:.8f} CPU")
        return 0
    else:
        print(f"❌ Failed to import coin from: {args.filepath}")
        return 1


def cmd_blockchain_info(args):
    """Show blockchain information."""
    blockchain_path = os.path.expanduser("~/.cpucoin/blockchain.json")

    if os.path.exists(blockchain_path):
        blockchain = Blockchain.load(blockchain_path)
    else:
        blockchain = Blockchain()

    print(f"\n📦 Blockchain Information:")
    print("-" * 40)
    print(f"  Height: {blockchain.height}")
    print(f"  Share difficulty: {blockchain.share_difficulty}")
    print(f"  Block difficulty: {blockchain.block_difficulty}")
    print(f"  Block reward: {blockchain.get_block_reward():.8f} CPU")
    print(f"  Share value: {blockchain.get_share_value():.8f} CPU")
    print(f"  Shares per block: {config.SHARES_PER_BLOCK}")
    print(f"  Pending transactions: {len(blockchain.pending_transactions)}")

    # Show current open block info if any
    if blockchain.current_open_block:
        block = blockchain.current_open_block
        print(f"\n🔓 Current Open Block #{block.index}:")
        print(f"  Shares claimed: {len(block.claimed_shares)}/{config.SHARES_PER_BLOCK}")
        print(f"  Shares remaining: {block.shares_remaining()}")

    print(f"\n📋 Recent Blocks:")
    for block in blockchain.chain[-5:]:
        status = "CLOSED" if block.is_closed else "OPEN"
        shares = len(block.claimed_shares) if hasattr(block, 'claimed_shares') else "N/A"
        print(f"  #{block.index}: {block.hash[:24]}... (shares: {shares}, {status})")

    return 0


def cmd_server_start(args):
    """Start the mining server."""
    port = args.port or 8333
    host = args.host or "0.0.0.0"

    print_header()
    run_server(host=host, port=port)
    return 0


def cmd_server_info(args):
    """Show mining server information."""
    server_url = args.url

    client = MiningClient(server_url)
    info = client.get_blockchain_info()

    if not info:
        print(f"❌ Failed to connect to server: {client.last_error}")
        return 1

    print(f"\n🌐 Server: {server_url}")
    print("-" * 40)
    print(f"  Height: {info.get('height', 0)}")
    print(f"  Share difficulty: {info.get('share_difficulty', 0)}")
    print(f"  Block difficulty: {info.get('block_difficulty', 0)}")
    print(f"  Block reward: {info.get('block_reward', 0):.8f} CPU")
    print(f"  Share value: {info.get('share_value', 0):.8f} CPU")
    print(f"  Shares per block: {info.get('shares_per_block', 0)}")

    open_block = info.get('current_open_block')
    if open_block:
        print(f"\n🔓 Current Open Block #{open_block.get('index', 0)}:")
        print(f"  Shares claimed: {open_block.get('shares_claimed', 0)}/{info.get('shares_per_block', config.SHARES_PER_BLOCK)}")
        print(f"  Shares remaining: {open_block.get('shares_remaining', 0)}")

    recent = info.get('recent_blocks', [])
    if recent:
        print(f"\n📋 Recent Blocks:")
        for block in recent:
            status = "CLOSED" if block.get('is_closed') else "OPEN"
            print(f"  #{block.get('index')}: {block.get('hash', '?')} (shares: {block.get('shares', 0)}, {status})")

    return 0


def cmd_node_start(args):
    """Start a network node."""
    port = args.port or config.DEFAULT_PORT

    blockchain_path = os.path.expanduser("~/.cpucoin/blockchain.json")
    if os.path.exists(blockchain_path):
        blockchain = Blockchain.load(blockchain_path)
    else:
        blockchain = Blockchain()

    node = Node(port=port, blockchain=blockchain)

    print(f"Starting node on port {port}...")
    node.start()

    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping node...")
        node.stop()

    return 0


def cmd_node_connect(args):
    """Connect to a peer node."""
    host, port = args.address.split(':')
    port = int(port)

    node = Node()
    if node.connect_to_peer(host, port):
        print(f"Connected to {host}:{port}")
        node.sync_blockchain()
    else:
        print(f"Failed to connect to {host}:{port}")
        return 1

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="CPUCoin - CPU-minable cryptocurrency with physical coin files",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Mine command
    mine_parser = subparsers.add_parser('mine', help='Mine shares (block shares system)')
    mine_parser.add_argument('--shares', '-s', type=int, default=0,
                            help='Number of shares to mine (0 = infinite)')
    mine_parser.add_argument('--wallet', '-w', type=str, default='default',
                            help='Wallet name to use')
    mine_parser.add_argument('--password', '-p', type=str, default=None,
                            help='Wallet password')
    mine_parser.add_argument('--threads', '-t', type=int, default=1,
                            help='Number of mining threads')
    mine_parser.add_argument('--server', type=str, default=None,
                            help='Mining server URL (e.g., http://localhost:8333)')

    # Wallet commands
    wallet_parser = subparsers.add_parser('wallet', help='Wallet commands')
    wallet_sub = wallet_parser.add_subparsers(dest='wallet_cmd')

    create_parser = wallet_sub.add_parser('create', help='Create a new wallet')
    create_parser.add_argument('name', help='Wallet name')
    create_parser.add_argument('--password', '-p', type=str, default=None,
                              help='Wallet password')

    info_parser = wallet_sub.add_parser('info', help='Show wallet info')
    info_parser.add_argument('name', nargs='?', default='default', help='Wallet name')
    info_parser.add_argument('--password', '-p', type=str, default='',
                            help='Wallet password')

    wallet_sub.add_parser('list', help='List all wallets')

    balance_parser = wallet_sub.add_parser('balance', help='Show balance')
    balance_parser.add_argument('name', nargs='?', default='default', help='Wallet name')
    balance_parser.add_argument('--password', '-p', type=str, default='',
                               help='Wallet password')

    # Send command
    send_parser = subparsers.add_parser('send', help='Send coins')
    send_parser.add_argument('recipient', help='Recipient public key')
    send_parser.add_argument('amount', type=float, help='Amount to send')
    send_parser.add_argument('--wallet', '-w', type=str, default='default',
                            help='Wallet name')
    send_parser.add_argument('--password', '-p', type=str, default='',
                            help='Wallet password')

    # Coins commands
    coins_parser = subparsers.add_parser('coins', help='Coin file commands')
    coins_sub = coins_parser.add_subparsers(dest='coins_cmd')

    list_parser = coins_sub.add_parser('list', help='List coins')
    list_parser.add_argument('--all', '-a', action='store_true',
                            help='Include spent coins')

    info_parser = coins_sub.add_parser('info', help='Show coin info')
    info_parser.add_argument('coin_id', help='Coin ID')

    export_parser = coins_sub.add_parser('export', help='Export coin to file')
    export_parser.add_argument('coin_id', help='Coin ID')
    export_parser.add_argument('filepath', help='Export path')

    import_parser = coins_sub.add_parser('import', help='Import coin from file')
    import_parser.add_argument('filepath', help='Coin file path')

    # Blockchain commands
    blockchain_parser = subparsers.add_parser('blockchain', help='Blockchain commands')
    blockchain_sub = blockchain_parser.add_subparsers(dest='blockchain_cmd')
    blockchain_sub.add_parser('info', help='Show blockchain info')

    # Server commands
    server_parser = subparsers.add_parser('server', help='Mining server commands')
    server_sub = server_parser.add_subparsers(dest='server_cmd')

    server_start_parser = server_sub.add_parser('start', help='Start mining server')
    server_start_parser.add_argument('--port', '-p', type=int, default=8333,
                                     help='Port to listen on (default: 8333)')
    server_start_parser.add_argument('--host', type=str, default='0.0.0.0',
                                     help='Host to bind to (default: 0.0.0.0)')

    server_info_parser = server_sub.add_parser('info', help='Show server info')
    server_info_parser.add_argument('url', help='Server URL (e.g., http://localhost:8333)')

    # Node commands
    node_parser = subparsers.add_parser('node', help='Network node commands')
    node_sub = node_parser.add_subparsers(dest='node_cmd')

    start_parser = node_sub.add_parser('start', help='Start node')
    start_parser.add_argument('--port', '-p', type=int, default=config.DEFAULT_PORT,
                             help='Port to listen on')

    connect_parser = node_sub.add_parser('connect', help='Connect to peer')
    connect_parser.add_argument('address', help='Peer address (host:port)')

    args = parser.parse_args()

    if args.command == 'mine':
        return cmd_mine(args)
    elif args.command == 'wallet':
        if args.wallet_cmd == 'create':
            return cmd_wallet_create(args)
        elif args.wallet_cmd == 'info':
            return cmd_wallet_info(args)
        elif args.wallet_cmd == 'list':
            return cmd_wallet_list(args)
        elif args.wallet_cmd == 'balance':
            return cmd_wallet_balance(args)
        else:
            wallet_parser.print_help()
    elif args.command == 'send':
        return cmd_send(args)
    elif args.command == 'coins':
        if args.coins_cmd == 'list':
            return cmd_coins_list(args)
        elif args.coins_cmd == 'info':
            return cmd_coins_info(args)
        elif args.coins_cmd == 'export':
            return cmd_coins_export(args)
        elif args.coins_cmd == 'import':
            return cmd_coins_import(args)
        else:
            coins_parser.print_help()
    elif args.command == 'blockchain':
        if args.blockchain_cmd == 'info':
            return cmd_blockchain_info(args)
        else:
            blockchain_parser.print_help()
    elif args.command == 'server':
        if args.server_cmd == 'start':
            return cmd_server_start(args)
        elif args.server_cmd == 'info':
            return cmd_server_info(args)
        else:
            server_parser.print_help()
    elif args.command == 'node':
        if args.node_cmd == 'start':
            return cmd_node_start(args)
        elif args.node_cmd == 'connect':
            return cmd_node_connect(args)
        else:
            node_parser.print_help()
    else:
        print_header()
        parser.print_help()

    return 0


if __name__ == '__main__':
    sys.exit(main())
