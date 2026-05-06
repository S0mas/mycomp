#!/usr/bin/env bash
# Start the mycomp MCP server and expose it via a cloudflare quick tunnel.
#
# Requires: cloudflared binary in the project root
#   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
#
# Usage:
#   ./scripts/start_mcp.sh [PORT]        (default: 8000)

set -uo pipefail

PORT=${1:-8000}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Kill anything already on the port ────────────────────────────────────────
EXISTING_PID=$(lsof -ti:"$PORT" 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
    echo "Port $PORT in use (PID $EXISTING_PID) — stopping it..."
    kill -9 $EXISTING_PID 2>/dev/null || true
    sleep 1
fi

# ── Start MCP server ──────────────────────────────────────────────────────────
echo "Starting MCP server on port $PORT..."
"$PROJECT_DIR/.venv/bin/python" -m aicompany.mcp_server --sse --port "$PORT" &
SERVER_PID=$!

sleep 1
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "ERROR: MCP server failed to start." >&2
    exit 1
fi
echo "MCP server running (PID $SERVER_PID)"

# ── Start cloudflare tunnel ───────────────────────────────────────────────────
echo ""
echo "Starting cloudflare tunnel — waiting for URL..."

TUNNEL_LOG=$(mktemp)
"$PROJECT_DIR/cloudflared" tunnel --url "http://localhost:$PORT" >"$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

# ── Extract and display the tunnel URL clearly ────────────────────────────────
TUNNEL_URL=""
for _ in $(seq 1 25); do
    TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
    [ -n "$TUNNEL_URL" ] && break
    sleep 1
done
rm -f "$TUNNEL_LOG"

echo ""
if [ -z "$TUNNEL_URL" ]; then
    echo "WARNING: Could not detect tunnel URL after 25s." >&2
    echo "Check cloudflared output or re-run the script." >&2
else
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Tunnel ready. Copy and run this in your project terminal:"
    echo ""
    echo "  export AICOMPANY_MCP_SERVERS='[{\"type\":\"url\",\"url\":\"${TUNNEL_URL}/mcp\",\"name\":\"mycomp\"}]'"
    echo ""
    echo "  Then: ./mycomp run <project-id>"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Press Ctrl+C to stop."
fi

# ── Keep alive until Ctrl+C ───────────────────────────────────────────────────
trap "echo ''; echo 'Shutting down...'; kill $SERVER_PID $TUNNEL_PID 2>/dev/null; exit 0" INT TERM EXIT

wait $SERVER_PID
