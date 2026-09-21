#!/usr/bin/env bash
# Run this ONCE on a fresh GCP e2-micro (Ubuntu) instance, over SSH, to
# prepare it to run the job engine continuously via Docker.
#
#   chmod +x deploy/gcp_vm_setup.sh
#   ./deploy/gcp_vm_setup.sh
#
# It installs Docker + the compose plugin, and adds a 2GB swapfile --
# e2-micro only has 1GB RAM, and a small headroom swapfile keeps the
# instance from getting OOM-killed under a brief memory spike.
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

echo "==> Setting up a 2GB swapfile (e2-micro only has 1GB RAM)"
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
else
    echo "Swapfile already exists, skipping."
fi

echo ""
echo "==> Done. Next steps:"
echo "  1. git clone <your repo url> (or scp the project over)"
echo "  2. cd JobApplicationEngine"
echo "  3. cp .env.example .env && nano .env   # fill in your credentials"
echo "  4. mkdir -p data && put your resume at data/resume.pdf"
echo "  5. docker compose run --rm job-engine   # first run: interactive Telethon phone-code login"
echo "  6. docker compose up -d                 # then run continuously"
