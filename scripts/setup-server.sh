#!/bin/bash
#
# CPUCoin Server Setup Script
#
# This script helps set up a CPUCoin central control server on a fresh system.
# It handles:
#   - Installing dependencies
#   - Creating necessary directories
#   - Setting up the virtual environment
#   - Creating a wallet for mining
#   - Installing systemd service (optional)
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="/opt/cpucoin"
DATA_DIR="/var/lib/cpucoin"
LOG_DIR="/var/log/cpucoin"
SERVICE_USER="cpucoin"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

show_banner() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║         CPUCoin Central Control Server Setup                 ║"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  This script will set up your server for 24/7 operation      ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
}

check_root() {
    if [ "$EUID" -eq 0 ]; then
        return 0
    fi
    return 1
}

install_dependencies() {
    log_step "Installing system dependencies..."

    if command -v apt-get &> /dev/null; then
        # Debian/Ubuntu
        apt-get update
        apt-get install -y python3 python3-pip python3-venv git curl
    elif command -v yum &> /dev/null; then
        # CentOS/RHEL
        yum install -y python3 python3-pip git curl
    elif command -v dnf &> /dev/null; then
        # Fedora
        dnf install -y python3 python3-pip git curl
    elif command -v pacman &> /dev/null; then
        # Arch
        pacman -Sy --noconfirm python python-pip git curl
    else
        log_warn "Unknown package manager. Please install Python 3, pip, and git manually."
    fi

    log_info "Dependencies installed"
}

create_user() {
    log_step "Creating service user '$SERVICE_USER'..."

    if id "$SERVICE_USER" &>/dev/null; then
        log_info "User '$SERVICE_USER' already exists"
    else
        useradd --system --shell /bin/false --home-dir "$DATA_DIR" "$SERVICE_USER"
        log_info "Created user '$SERVICE_USER'"
    fi
}

create_directories() {
    log_step "Creating directories..."

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$DATA_DIR/.cpucoin/wallets"
    mkdir -p "$DATA_DIR/.cpucoin/coins"
    mkdir -p "$LOG_DIR"

    # Set permissions
    chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR"

    log_info "Directories created"
}

install_cpucoin() {
    log_step "Installing CPUCoin..."

    # Copy project files
    cp -r "$PROJECT_DIR"/* "$INSTALL_DIR/"

    # Create virtual environment
    cd "$INSTALL_DIR"
    python3 -m venv venv
    source venv/bin/activate

    # Install dependencies
    pip install --upgrade pip
    pip install -e .

    # Set permissions
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

    log_info "CPUCoin installed to $INSTALL_DIR"
}

create_wallet() {
    log_step "Creating server wallet..."

    cd "$INSTALL_DIR"
    source venv/bin/activate

    # Create wallet for the server
    export HOME="$DATA_DIR"
    python3 -c "
from cpucoin.wallet import Wallet
import os
os.makedirs('$DATA_DIR/.cpucoin/wallets', exist_ok=True)
wallet = Wallet.create('servernode')
print(f'Wallet created: {wallet.address}')
print(f'IMPORTANT: Save this address for receiving mining rewards!')
"

    chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/.cpucoin"
    log_info "Wallet 'servernode' created"
}

install_systemd_service() {
    log_step "Installing systemd service..."

    # Copy and configure service file
    cat > /etc/systemd/system/cpucoin-server.service << EOF
[Unit]
Description=CPUCoin Central Control Server
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment=HOME=$DATA_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$INSTALL_DIR/venv/bin/python -m cpucoin.coin_control_server \\
    --port 8333 \\
    --api-port 8080 \\
    --mine \\
    --wallet servernode \\
    --threads 4 \\
    --log-file $LOG_DIR/server.log
Restart=always
RestartSec=10
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd
    systemctl daemon-reload
    systemctl enable cpucoin-server

    log_info "Systemd service installed and enabled"
}

configure_firewall() {
    log_step "Configuring firewall..."

    if command -v ufw &> /dev/null; then
        ufw allow 8333/tcp comment "CPUCoin P2P"
        ufw allow 8080/tcp comment "CPUCoin API"
        log_info "UFW rules added"
    elif command -v firewall-cmd &> /dev/null; then
        firewall-cmd --permanent --add-port=8333/tcp
        firewall-cmd --permanent --add-port=8080/tcp
        firewall-cmd --reload
        log_info "Firewalld rules added"
    else
        log_warn "No supported firewall found. Please manually open ports 8333 and 8080"
    fi
}

show_summary() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    Setup Complete!                           ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Installation Summary:"
    echo "  - Install directory: $INSTALL_DIR"
    echo "  - Data directory:    $DATA_DIR"
    echo "  - Log directory:     $LOG_DIR"
    echo "  - Service user:      $SERVICE_USER"
    echo ""
    echo "Commands:"
    echo "  Start server:   sudo systemctl start cpucoin-server"
    echo "  Stop server:    sudo systemctl stop cpucoin-server"
    echo "  View status:    sudo systemctl status cpucoin-server"
    echo "  View logs:      sudo journalctl -u cpucoin-server -f"
    echo "  Tail log file:  tail -f $LOG_DIR/server.log"
    echo ""
    echo "API Endpoints (after starting):"
    echo "  Status:     http://localhost:8080/status"
    echo "  Health:     http://localhost:8080/health"
    echo "  Blockchain: http://localhost:8080/blockchain"
    echo "  Peers:      http://localhost:8080/peers"
    echo ""
    echo "To start the server now, run:"
    echo "  sudo systemctl start cpucoin-server"
    echo ""
}

# Quick start for non-root users
quick_start() {
    log_info "Running quick start for local user..."

    cd "$PROJECT_DIR"

    # Create virtual environment if needed
    if [ ! -d "venv" ]; then
        log_step "Creating virtual environment..."
        python3 -m venv venv
    fi

    source venv/bin/activate

    log_step "Installing dependencies..."
    pip install --upgrade pip
    pip install -e .

    log_step "Creating wallet..."
    python3 -c "
from cpucoin.wallet import Wallet
import os
wallet_dir = os.path.expanduser('~/.cpucoin/wallets')
os.makedirs(wallet_dir, exist_ok=True)
try:
    wallet = Wallet.load('server')
    print(f'Using existing wallet: {wallet.address}')
except:
    wallet = Wallet.create('server')
    print(f'Created new wallet: {wallet.address}')
"

    echo ""
    echo "Quick Start Complete!"
    echo ""
    echo "To start the server, run:"
    echo "  ./scripts/start-server.sh"
    echo ""
    echo "Or with mining enabled:"
    echo "  ./scripts/start-server.sh --mine --wallet server"
    echo ""
}

# Main
show_banner

if check_root; then
    log_info "Running as root - performing full installation"
    install_dependencies
    create_user
    create_directories
    install_cpucoin
    create_wallet
    install_systemd_service
    configure_firewall
    show_summary
else
    log_warn "Not running as root - performing quick start for local user"
    log_info "For full server installation, run: sudo $0"
    echo ""
    quick_start
fi
