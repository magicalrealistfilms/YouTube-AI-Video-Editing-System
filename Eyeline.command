#!/bin/bash
# Eyeline Home: double-click in Finder. Opens one page to record, prepare and edit.
# Keep this window open while you work; close it to stop Eyeline.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Eyeline needs uv. Install it from https://docs.astral.sh/uv/getting-started/installation/ and try again."
  read -r -p "Press Enter to close this window. "
  exit 1
fi
uv run apps/home/home_server.py
