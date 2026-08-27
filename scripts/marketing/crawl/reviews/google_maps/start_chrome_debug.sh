#!/bin/bash
# Start Chrome with remote debugging for Google Maps crawler
# Usage: ./scripts/marketing/crawl/reviews/google_maps/start_chrome_debug.sh

# Configuration
DEBUG_PORT=9227
USER_DATA_DIR="/tmp/chrome-codex-google-maps"

echo "🚀 Starting Chrome with remote debugging..."
echo "   Port: $DEBUG_PORT"
echo "   User Data: $USER_DATA_DIR"
echo ""

# Kill any existing Chrome on this port
lsof -ti:$DEBUG_PORT | xargs kill -9 2>/dev/null || true

# Remove old user data to avoid conflicts
rm -rf "$USER_DATA_DIR" 2>/dev/null || true
mkdir -p "$USER_DATA_DIR"

# Start Chrome with debugging
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=$DEBUG_PORT \
  --user-data-dir="$USER_DATA_DIR" \
  --disable-blink-features=AutomationControlled \
  --disable-dev-shm-usage \
  --no-first-run \
  --no-default-browser-check \
  --lang=vi-VN \
  --accept-lang=vi-VN,vi \
  "https://www.google.com/maps?hl=vi" \
  2>&1 | tee /tmp/chrome-debug.log &

CHROME_PID=$!

echo "✓ Chrome started (PID: $CHROME_PID)"
echo "✓ Remote debugging on 127.0.0.1:$DEBUG_PORT"
echo ""
echo "📍 Navigate to your first location in Chrome, then run:"
echo "   PYTHONPATH=src python3 scripts/marketing/crawl/reviews/google_maps/google_maps_review_runner.py"
echo ""
echo "🛑 To stop Chrome:"
echo "   kill $CHROME_PID"
