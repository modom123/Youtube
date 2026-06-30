#!/usr/bin/env bash
set -e

echo "==> Installing system dependencies"
apt-get update -qq
apt-get install -y -qq ffmpeg libsm6 libxext6 fonts-liberation

echo "==> Installing Python dependencies"
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Installing Higgsfield CLI"
curl -fsSL https://raw.githubusercontent.com/higgsfield-ai/cli/main/install.sh | sh

echo "==> Build complete"
