#!/bin/bash
# GridWatcher Orange Pi PC+ Automated Setup Script
set -e

echo "=================================================="
echo "   GridWatcher Automated Orange Pi Setup Script   "
echo "=================================================="

echo "[1/4] Installing Docker..."
curl -fsSL https://get.docker.com | sh

echo "[2/4] Enabling Docker Service..."
systemctl enable --now docker

echo "[3/4] Creating GridWatcher Docker Compose Configuration..."
mkdir -p ~/gridwatcher && cd ~/gridwatcher

cat << 'EOF' > docker-compose.yml
version: '3.8'

services:
  homeassistant:
    container_name: homeassistant
    image: ghcr.io/home-assistant/home-assistant:stable
    volumes:
      - ./config/homeassistant:/config
      - /etc/localtime:/etc/localtime:ro
    restart: always
    network_mode: host

  esphome:
    container_name: esphome
    image: ghcr.io/esphome/esphome
    volumes:
      - ./config/esphome:/config
      - /etc/localtime:/etc/localtime:ro
    restart: always
    network_mode: host
EOF

echo "[4/4] Spinning up Home Assistant & ESPHome Containers..."
docker compose up -d

echo "=================================================="
echo "   SUCCESS! GridWatcher Home Server is LIVE!      "
echo "=================================================="
echo "Home Assistant Web UI: http://$(hostname -I | awk '{print $1}'):8123"
echo "ESPHome Web UI:        http://$(hostname -I | awk '{print $1}'):6052"
echo "=================================================="
