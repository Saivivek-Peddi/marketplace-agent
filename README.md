# Marketplace Agent

An AI agent that books rides end-to-end — discover options, compare prices, book, track, and cancel. Built with a Plan-Execute-Verify architecture, multi-layer memory system, swappable adapter pattern, confirmation gates, and guardrails.

## Quick Start

```bash
# 1. Set your Anthropic API key
export ANTHROPIC_API_KEY="sk-ant-..."

# 2. Run the agent
./start-agent.sh
```

The script installs dependencies via `uv`, starts the mock Uber API, and launches the agent. You'll be prompted to choose a model (Sonnet, Opus, or Haiku).

## What It Does

```
You: Take me from home to work

Agent: Here are your options from 2111 7th Ave, Seattle to Salesforce Tower, SF:
       - UberX: $12-$16, ETA 4min
       - Comfort: $18-$22, ETA 6min
       - UberXL: $22-$27, ETA 9min
       - Black: $35-$42, ETA 7min
       Want me to get a quote?

You: UberX

Agent: Locked in at $13.20. Book it?

You: Yes

  ══════════════════════════════════════════
    CONFIRMATION REQUIRED: book_ride
    The agent wants to BOOK this ride.
    Approve? (yes/no): yes
    -> Approved.
  ══════════════════════════════════════════

Agent: Ride booked! Driver James (4.9) in a Silver Toyota Camry,
       arriving in 4 minutes.
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.

```
User Input
  -> Input Guardrail (always on, blocks prompt injection)
  -> Memory System (context, state recovery, learned preferences)
  -> Agent Loop (Plan-Execute-Verify)
       -> Planner: Claude API with system prompt + memory context
       -> Executor: Tool dispatch with validation + retry
       -> Verifier: State update + episode recording + pattern learning
  -> Output Guardrail (blocks leaked internals)
  -> User sees clean response
```

## Project Structure

```
marketplace-agent/
|
|-- agent/                     # The AI agent
|   |-- main.py                # Agent class -- Plan-Execute-Verify loop
|   |-- memory.py              # Multi-layer memory (short-term, working, episodic, semantic)
|   |-- config.py              # System prompt, tool definitions, constants
|   |-- tools.py               # Tool handlers returning structured ToolResult
|   |-- gates.py               # Confirmation gates (book/cancel)
|   |-- validation.py          # Input validation (addresses, IDs)
|   |-- retry.py               # Retry with exponential backoff
|   |-- display.py             # Output with guardrail filtering
|   |-- state.py               # Deprecated -- re-exports from memory.py
|
|-- mcp_server/                # Platform layer
|   |-- adapter.py             # Abstract RideAdapter + dataclasses
|   |-- adapters/
|   |   |-- uber.py            # Uber implementation
|   |-- guardrails.py          # Input/output pattern filters
|   |-- action_log.py          # Append-only audit trail
|   |-- profile.py             # Saved places, preferences, ride history
|   |-- server.py              # MCP server (for Claude Code integration)
|
|-- server/                    # Mock Uber API
|   |-- app.py                 # FastAPI endpoints with async locks + health check
|   |-- models.py              # Pydantic schemas + state machine
|   |-- simulation.py          # Geocoding, OSRM routing, pricing, drivers
|
|-- tests/                     # Test suite
|   |-- test_memory.py         # Memory system tests (47 tests)
|   |-- test_tools.py          # Tool handlers + validation tests
|   |-- test_simulation.py     # State machine + store tests
|
|-- transcripts/               # Example conversations (7 scenarios)
|-- docs/                      # Additional documentation
|-- start-agent.sh             # Launch script
|-- pyproject.toml             # Dependencies (managed with uv)
```

## Key Features

### Memory System
Four-layer memory with SQLite persistence. See [ARCHITECTURE.md](ARCHITECTURE.md#memory-system) for details.
- **Short-term**: Conversation messages with automatic pruning and summarization
- **Working**: Active ride IDs, estimate IDs, current status -- survives crashes
- **Episodic**: Past rides, cancellations, errors -- builds history
- **Semantic**: Learned preferences and patterns -- gets smarter over time

### Plan-Execute-Verify Loop
The agent doesn't just call tools in a loop. Each turn:
1. **Plans**: Claude receives working memory, episodic history, and learned preferences in the system prompt
2. **Executes**: Tools return structured `ToolResult` with both display text and machine-readable data
3. **Verifies**: Working memory updates, episodes are recorded, patterns are learned

### Adapter Pattern
Swap Uber for Lyft by implementing one file. The agent, tools, gates, guardrails, and memory stay identical.

### Confirmation Gates
Book and cancel operations require explicit user approval -- enforced in code, not model instructions.

### Guardrails (Always On)
- **Input guard**: Blocks prompt injection, instruction extraction, role hijack
- **Output guard**: Catches leaked tool names, file paths, API details

### Structured Tool Results
Tools return `ToolResult(display, data)` instead of raw strings. State tracking uses structured data, not string parsing.

### Retry with Backoff
All external calls (Claude API, ride service, geocoding) have retry with exponential backoff.

### Concurrency Safety
Server uses `asyncio.Lock` on the Store. Background tasks (driver matching) are tracked and cancelled on shutdown.

### Health Check
`GET /health` returns active ride count, estimate/quote counts, and background task status.

## Running Tests

```bash
uv run pytest tests/ -v
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `AGENT_MODEL` | `claude-sonnet-4-6` | Model override |
| `UBER_API_BASE` | `http://localhost:8000` | Mock API URL |
| `AGENT_DEBUG` | unset | Set to `1` for debug output |

## Mock API

```
POST /v1/estimates            Search rides (geocoded, OSRM validated)
POST /v1/quotes               Lock exact price (2 min TTL)
POST /v1/rides                Book ride (async driver matching)
GET  /v1/rides/{id}           Status + driver + live fare
GET  /v1/rides/{id}/cancel-fee  Preview cancel cost
POST /v1/rides/{id}/cancel    Execute cancel
GET  /health                  Health check
```

Ride states: `processing -> matched -> arriving -> in_progress -> completed`

Test scenarios via `X-Scenario` header: `surge`, `no-drivers`, `driver-cancels`, `quote-expire`, `slow`.
