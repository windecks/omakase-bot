#!/bin/bash
# DigitalOcean Droplet User Data / Startup Script
# Paste this into: Create Droplet → Advanced Options → User Data
#
# What it does:
#   1. Installs Docker
#   2. Clones the omakase-bot repo
#   3. Creates a placeholder tasks.yaml for you to fill in
#   4. Pulls the base Docker image so first `docker compose up` is fast
#
# After droplet boots (~3 min), SSH in and:
#   cd /opt/omakase-bot
#   nano tasks.yaml        # fill in your targets + proxy
#   docker compose up -d --build

set -euo pipefail

REPO_URL="https://github.com/windecks/omakase-bot.git"  # ← your repo URL
INSTALL_DIR="/opt/omakase-bot"

export DEBIAN_FRONTEND=noninteractive

# ── 1. System updates ───────────────────────────────────────────────
apt-get update -qq
apt-get upgrade -y -qq

# ── 2. Install Docker ───────────────────────────────────────────────
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# ── 3. Clone repo ───────────────────────────────────────────────────
git clone "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"

# ── 4. Create tasks.yaml placeholder ────────────────────────────────
cat > tasks.yaml << 'EOF'
tasks:
  - mode: monitor
    email: "CHANGEME"
    password: "CHANGEME"
    restaurant_id: "CHANGEME"
    date: "2026-08-01"
    time: "18:00"
    party_size: 1
    auto_book: false
    discord_webhook_url: ""
    discord_user_id: ""
    proxy: "http://user:pass@host:port"
EOF

# ── 5. Pre-pull base image so first build is faster ─────────────────
docker pull mcr.microsoft.com/playwright/python:v1.60.0-noble

# ── 6. Pre-build the bot image ──────────────────────────────────────
docker compose build

# ── 7. Set timezone to JST ──────────────────────────────────────────
timedatectl set-timezone Asia/Tokyo

# ── 8. Done ─────────────────────────────────────────────────────────
echo "============================================="
echo "  omakase-bot ready at $INSTALL_DIR"
echo "  SSH in, edit tasks.yaml, then run:"
echo "    cd $INSTALL_DIR"
echo "    docker compose up -d"
echo "============================================="
