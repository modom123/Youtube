#!/usr/bin/env bash
set -e

echo "==> Installing Python dependencies"
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Build complete"
