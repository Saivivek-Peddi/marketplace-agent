#!/bin/bash
# Start the mock Uber API server and the agent harness
set -e

cd "$(dirname "$0")"

# Load .env if present
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set."
    echo "Create a .env file: cp .env.example .env"
    echo "Or export it: export ANTHROPIC_API_KEY=sk-..."
    exit 1
fi

# Install deps if needed
if [ ! -f "uv.lock" ]; then
    echo "Installing dependencies..."
    uv sync --all-extras
fi

# Check if port 8000 is in use
PORT=8000
if lsof -ti:$PORT > /dev/null 2>&1; then
    echo "Port $PORT is already in use."
    read -p "Kill the existing process? (yes/no): " answer
    if [ "$answer" = "yes" ] || [ "$answer" = "y" ]; then
        lsof -ti:$PORT | xargs kill -15 2>/dev/null || true
        sleep 1
        echo "Killed."
    else
        read -p "Enter a different port: " PORT
    fi
fi

# Start mock Uber API in background
export UBER_API_BASE="http://localhost:$PORT"
printf "  \033[38;5;245mStarting ride service on port $PORT...\033[0m"
uv run uvicorn server.app:app --port "$PORT" --log-level warning &
SERVER_PID=$!

# Wait for server to be ready
for i in {1..10}; do
    if curl -s "http://localhost:$PORT/docs" > /dev/null 2>&1; then
        printf "\r  \033[38;5;78m✓\033[0m \033[38;5;245mRide service ready on port $PORT\033[0m\n"
        break
    fi
    sleep 0.5
done

# Cleanup server on exit (graceful SIGTERM, not SIGKILL)
trap "printf '\n  \033[38;5;245mStopping ride service...\033[0m\n'; kill -15 $SERVER_PID 2>/dev/null" EXIT

# Start agent (pass through any args like --session, --new, --sessions)
uv run python -m agent "$@"
