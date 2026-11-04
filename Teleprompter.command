#!/bin/bash
# Eyeline teleprompter only: double-click in Finder. Opens http://localhost:5317 in Chrome or Edge if installed.
# Keep this window open while you record; close it to stop the teleprompter.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
python3 apps/teleprompter/server.py &
server=$!
trap 'kill $server 2>/dev/null' EXIT
for _ in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:5317/ && break; sleep 0.25; done
if [ -d "/Applications/Google Chrome.app" ]; then open -a "Google Chrome" http://localhost:5317/
elif [ -d "/Applications/Microsoft Edge.app" ]; then open -a "Microsoft Edge" http://localhost:5317/
else open http://localhost:5317/; fi
wait $server
