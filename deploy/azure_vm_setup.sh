#!/usr/bin/env bash
# Run this ONCE on a fresh Azure VM (Ubuntu), over SSH, to prepare it to
# run the job engine continuously via Docker.
#
#   chmod +x deploy/azure_vm_setup.sh
#   ./deploy/azure_vm_setup.sh
set -euo pipefail

echo "==> Updating packages"
sudo apt-get update -y
sudo apt-get upgrade -y

echo "==> Installing Docker"
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "Added $USER to the docker group -- log out and back in (or run 'newgrp docker') for it to take effect."
else
    echo "Docker already installed, skipping."
fi

TOTAL_MEM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if [ "$TOTAL_MEM_KB" -lt 2097152 ]; then
    echo "==> Low-RAM VM detected (< 2GB), setting up a 2GB swapfile"
    if [ ! -f /swapfile ]; then
        sudo fallocate -l 2G /swapfile
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile
        sudo swapon /swapfile
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    else
        echo "Swapfile already exists, skipping."
    fi
else
    echo "==> Plenty of RAM detected, skipping swapfile"
fi

echo ""
echo "==> Done. Next steps (see deploy/azure-setup.md for the full walkthrough):"
echo "  1. git clone <your repo url>"
echo "  2. cd JobApplicationEngine"
echo "  3. cp .env.example .env && nano .env   # fill in your credentials"
echo "  4. Copy your already-authenticated data/ folder up from your Mac (see guide)"
echo "  5. docker compose up -d"
