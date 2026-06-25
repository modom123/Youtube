#!/usr/bin/env bash
set -e

echo "==> Installing system dependencies"
apt-get update -qq
apt-get install -y -qq ffmpeg libsm6 libxext6 fonts-liberation

echo "==> Installing Python dependencies"
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Generating PWA icons"
python scripts/generate_icons.py

echo "==> Build complete"
echo ""
echo "Platform targets:"
echo "  Web (PWA)  — served by Flask; installable on any browser"
echo "  Desktop    — see desktop/ (Electron: macOS, Windows, Linux)"
echo "  Mobile     — see mobile/  (Expo: iOS + Android via EAS Build)"
