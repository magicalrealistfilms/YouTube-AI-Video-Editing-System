#!/bin/bash
# Eyeline Edit only: double-click in Finder. Opens the last project at http://localhost:5320.
# Keep this window open while you edit; close it to stop the editor.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "The editor needs uv. Install it from https://docs.astral.sh/uv/getting-started/installation/ and try again."
  read -r -p "Press Enter to close this window. "
  exit 1
fi
uv run apps/eyeline-edit/edit_server.py &
server=$!
trap 'kill $server 2>/dev/null' EXIT
for _ in $(seq 1 600); do curl -s -o /dev/null http://127.0.0.1:5320/ && break; sleep 0.25; done
open http://localhost:5320/
wait $server
