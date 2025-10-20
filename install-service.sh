#!/bin/bash

# KlatreBot Service Installation Script
# Run this script as root or with sudo

set -e

echo "Installing KlatreBot as a systemd service..."

# Configuration
SERVICE_NAME="klatrebot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_DIR="/etc/klatrebot"
ENV_FILE="${ENV_DIR}/klatrebot.env"

# Detect current user and project directory
if [ -n "$SUDO_USER" ]; then
    USER="$SUDO_USER"
else
    USER="$(whoami)"
fi

PROJECT_DIR="/home/${USER}/KlatreBot/KlatreBot_Public"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
   echo "This script must be run as root or with sudo"
   exit 1
fi

# Check if project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "Error: Project directory $PROJECT_DIR does not exist"
    echo "Please ensure KlatreBot is cloned to the correct location"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "Error: Virtual environment not found at $PROJECT_DIR/.venv"
    echo "Please create the virtual environment first:"
    echo "  cd $PROJECT_DIR"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Create environment directory
mkdir -p "$ENV_DIR"

# Copy service file
cp "$PROJECT_DIR/klatrebot.service" "$SERVICE_FILE"

# Copy environment template
cp "$PROJECT_DIR/klatrebot.env" "$ENV_FILE"

# Set proper permissions
chown root:root "$SERVICE_FILE"
chmod 644 "$SERVICE_FILE"
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"

# Service file is already configured to use EnvironmentFile

# Reload systemd
systemctl daemon-reload

# Enable service
systemctl enable "$SERVICE_NAME"

echo "Service installed successfully!"
echo ""
echo "Next steps:"
echo "1. Edit $ENV_FILE with your Discord and OpenAI keys"
echo "2. Start the service: sudo systemctl start $SERVICE_NAME"
echo "3. Check status: sudo systemctl status $SERVICE_NAME"
echo "4. View logs: sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "Service management commands:"
echo "  Start:   sudo systemctl start $SERVICE_NAME"
echo "  Stop:    sudo systemctl stop $SERVICE_NAME"
echo "  Restart: sudo systemctl restart $SERVICE_NAME"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
