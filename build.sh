#!/usr/bin/env bash
set -e

echo "==> Installing Python dependencies"
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Installing Higgsfield CLI"
curl -fsSL https://raw.githubusercontent.com/higgsfield-ai/cli/main/install.sh | sh

echo "==> Generating PWA icons"
python scripts/generate_icons.py

echo "==> Build complete"
echo ""
echo "Platform targets:"
echo "  Web (PWA)  — served by Flask; installable on any browser"
echo "  Desktop    — see desktop/ (Electron: macOS, Windows, Linux)"
echo "  Mobile     — see mobile/  (Expo: iOS + Android via EAS Build)"
