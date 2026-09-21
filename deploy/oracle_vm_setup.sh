#!/usr/bin/env bash
# Run this ONCE on a fresh Oracle Cloud Always Free instance (Ubuntu), over
# SSH, to prepare it to run the job engine continuously via Docker.
#
#   chmod +x deploy/oracle_vm_setup.sh
#   ./deploy/oracle_vm_setup.sh
#
# Works on both Oracle's free shapes: the AMD "VM.Standard.E2.1.Micro"
# (1GB RAM, needs the swapfile below) and the Ampere A1 ARM shape (up to
# 24GB RAM, where swap is just cheap insurance, not strictly required).
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
    echo "==> Low-RAM shape detected, setting up a 2GB swapfile"
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
echo "==> Oracle's default security list only allows inbound SSH (22)."
echo "    This app makes outbound-only connections (Telegram/Groq/SMTP), so no"
echo "    extra ingress rules are needed -- nothing to open."
echo ""
echo "==> Done. Next steps:"
echo "  1. git clone <your repo url> (or scp the project over)"
echo "  2. cd JobApplicationEngine"
echo "  3. cp .env.example .env && nano .env   # fill in your credentials"
echo "  4. mkdir -p data && put your resume at data/resume.pdf"
echo "  5. docker compose run --rm job-engine   # first run: interactive Telethon phone-code login"
echo "  6. docker compose up -d                 # then run continuously"
