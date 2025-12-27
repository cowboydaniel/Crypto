#!/bin/bash
#
# CPUCoin Central Control Server - Startup Script
#
# This script provides a robust way to run the coin control server 24/7
# with automatic restart on failure and proper logging.
#
# Usage:
#   ./start-server.sh [OPTIONS]
#
# Options:
#   --mine          Enable mining
#   --wallet NAME   Wallet for mining rewards
#   --port PORT     P2P port (default: 8333)
#   --api-port PORT API port (default: 8080)
#   --daemon        Run in background
#   --help          Show this help
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/venv"
LOG_DIR="${LOG_DIR:-$HOME/.cpucoin-server/logs}"
PID_FILE="${PID_FILE:-$HOME/.cpucoin-server/server.pid}"

# Default settings
PORT=8333
API_PORT=8080
WALLET=""
MINE=false
DAEMON=false
THREADS=4

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    cat << EOF
CPUCoin Central Control Server - Startup Script

Usage: $0 [OPTIONS]

Options:
    --mine              Enable mining on the server
    --wallet NAME       Wallet name for mining rewards (required if --mine)
    --port PORT         P2P port (default: 8333)
    --api-port PORT     REST API port (default: 8080)
    --threads N         Mining threads (default: 4)
    --daemon            Run in background as daemon
    --stop              Stop running server
    --status            Check server status
    --logs              Tail server logs
    --help              Show this help

Examples:
    # Start basic server
    $0

    # Start with mining enabled
    $0 --mine --wallet myserver

    # Start as daemon with custom ports
    $0 --daemon --port 9333 --api-port 9080

    # Check status
    $0 --status

    # View logs
    $0 --logs

EOF
    exit 0
}

check_dependencies() {
    log_info "Checking dependencies..."

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed"
        exit 1
    fi

    # Check if virtual environment exists
    if [ -d "$VENV_DIR" ]; then
        source "$VENV_DIR/bin/activate"
    else
        log_warn "Virtual environment not found at $VENV_DIR"
        log_info "Attempting to use system Python..."
    fi

    # Check if cpucoin module is importable
    if ! python3 -c "import cpucoin" 2>/dev/null; then
        log_error "cpucoin module not found. Please install it first:"
        log_error "  cd $PROJECT_DIR && pip install -e ."
        exit 1
    fi

    log_info "Dependencies OK"
}

create_directories() {
    mkdir -p "$LOG_DIR"
    mkdir -p "$(dirname "$PID_FILE")"
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

is_running() {
    local pid=$(get_pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

stop_server() {
    if is_running; then
        local pid=$(get_pid)
        log_info "Stopping server (PID: $pid)..."
        kill -TERM "$pid" 2>/dev/null || true

        # Wait for graceful shutdown
        for i in {1..30}; do
            if ! is_running; then
                log_info "Server stopped"
                rm -f "$PID_FILE"
                return 0
            fi
            sleep 1
        done

        # Force kill if still running
        log_warn "Forcing shutdown..."
        kill -KILL "$pid" 2>/dev/null || true
        rm -f "$PID_FILE"
    else
        log_info "Server is not running"
    fi
}

show_status() {
    if is_running; then
        local pid=$(get_pid)
        log_info "Server is RUNNING (PID: $pid)"

        # Try to get status from API
        if command -v curl &> /dev/null; then
            echo ""
            curl -s "http://localhost:$API_PORT/status" 2>/dev/null | python3 -m json.tool 2>/dev/null || true
        fi
    else
        log_warn "Server is NOT RUNNING"
    fi
}

show_logs() {
    local log_file="$LOG_DIR/server.log"
    if [ -f "$log_file" ]; then
        tail -f "$log_file"
    else
        log_error "Log file not found: $log_file"
        exit 1
    fi
}

start_server() {
    if is_running; then
        log_warn "Server is already running (PID: $(get_pid))"
        exit 1
    fi

    create_directories
    check_dependencies

    # Build command
    CMD="python3 -m cpucoin.coin_control_server"
    CMD="$CMD --port $PORT"
    CMD="$CMD --api-port $API_PORT"
    CMD="$CMD --log-file $LOG_DIR/server.log"

    if [ "$MINE" = true ]; then
        if [ -z "$WALLET" ]; then
            log_error "--wallet is required when --mine is specified"
            exit 1
        fi
        CMD="$CMD --mine --wallet $WALLET --threads $THREADS"
    fi

    log_info "Starting CPUCoin Central Control Server..."
    log_info "P2P Port: $PORT"
    log_info "API Port: $API_PORT"
    log_info "Logs: $LOG_DIR/server.log"

    if [ "$MINE" = true ]; then
        log_info "Mining: ENABLED (wallet: $WALLET, threads: $THREADS)"
    else
        log_info "Mining: DISABLED"
    fi

    cd "$PROJECT_DIR"

    if [ "$DAEMON" = true ]; then
        # Run in background
        nohup $CMD >> "$LOG_DIR/server.log" 2>&1 &
        local pid=$!
        echo $pid > "$PID_FILE"

        # Wait a moment to check if it started
        sleep 2
        if is_running; then
            log_info "Server started in background (PID: $pid)"
            log_info "Use '$0 --logs' to view logs"
            log_info "Use '$0 --stop' to stop the server"
        else
            log_error "Server failed to start. Check $LOG_DIR/server.log for details"
            exit 1
        fi
    else
        # Run in foreground
        log_info "Starting in foreground (Ctrl+C to stop)..."
        exec $CMD
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --mine)
            MINE=true
            shift
            ;;
        --wallet)
            WALLET="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --api-port)
            API_PORT="$2"
            shift 2
            ;;
        --threads)
            THREADS="$2"
            shift 2
            ;;
        --daemon)
            DAEMON=true
            shift
            ;;
        --stop)
            stop_server
            exit 0
            ;;
        --status)
            show_status
            exit 0
            ;;
        --logs)
            show_logs
            exit 0
            ;;
        --help|-h)
            show_help
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            ;;
    esac
done

# Main
start_server
