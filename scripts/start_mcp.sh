#!/usr/bin/env bash
# Start the mycomp MCP server and expose it via a cloudflare quick tunnel.
#
# Usage:
#   ./scripts/start_mcp.sh [--port 8000]
#
# After startup, copy the tunnel URL from the output and set:
#   AICOMPANY_MCP_SERVERS='[{"type":"url","url":"https://<tunnel>.trycloudflare.com/sse","name":"mycomp"}]'
# or add it to .claude/settings.local.json under "env".

set -euo pipefail

PORT=${1:-8000}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Starting mycomp MCP server on port $PORT..."
"$PROJECT_DIR/.venv/bin/python" -m aicompany.mcp_server --sse --port "$PORT" &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

# Give the server a moment to bind
sleep 1

echo ""
echo "Starting cloudflare tunnel..."
echo "(Look for the trycloudflare.com URL below — that's your MCP server URL)"
echo ""
"$PROJECT_DIR/cloudflared" tunnel --url "http://localhost:$PORT" &
TUNNEL_PID=$!

trap "kill $SERVER_PID $TUNNEL_PID 2>/dev/null; exit" INT TERM EXIT

wait $SERVER_PID
