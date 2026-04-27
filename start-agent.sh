#!/bin/bash
# Start the mock Uber API server and the agent harness
set -e

cd "$(dirname "$0")"

# Check venv exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -q ".[harness]"
fi

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set."
    echo "Export it first: export ANTHROPIC_API_KEY=sk-..."
    exit 1
fi

# Check if port 8000 is in use
PORT=8000
if lsof -ti:$PORT > /dev/null 2>&1; then
    echo "Port $PORT is already in use."
    read -p "Kill the existing process? (yes/no): " answer
    if [ "$answer" = "yes" ] || [ "$answer" = "y" ]; then
        lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
        echo "Killed."
    else
        read -p "Enter a different port: " PORT
    fi
fi

# Start mock Uber API in background
export UBER_API_BASE="http://localhost:$PORT"
echo "Starting mock Uber API on http://localhost:$PORT..."
.venv/bin/uvicorn server.app:app --port "$PORT" --log-level warning &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..10}; do
    if curl -s "http://localhost:$PORT/docs" > /dev/null 2>&1; then
        echo "Server ready."
        break
    fi
    sleep 0.5
done

# Cleanup server on exit
trap "echo 'Stopping server...'; kill $SERVER_PID 2>/dev/null" EXIT

# Start agent
echo ""
.venv/bin/python3 -m agent
