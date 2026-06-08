#!/usr/bin/env bash
# Install + enable the daily Lidl summary timer (user scope).
# Prereq: the project venv exists and chromium is installed for scraping:
#   python -m venv .venv && .venv/bin/pip install -e . && .venv/bin/playwright install chromium
set -euo pipefail
cd "$(dirname "$0")/.."
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
cp systemd/little-lidl-summary.service systemd/little-lidl-summary.timer "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now little-lidl-summary.timer
echo "enabled. upcoming run:"
systemctl --user list-timers little-lidl-summary.timer --no-pager
