# Marketplace Agent

An AI agent that books rides end-to-end through natural conversation — discover options, compare prices, book, track, and cancel. Built with a Plan-Execute-Verify architecture, four-layer memory system, named sessions, swappable adapter pattern, and always-on guardrails.

![Demo](demo.gif)
<!-- Replace demo.gif with your recorded terminal session -->

## Quick Start

```bash
# 1. Set up your API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 2. Run the agent
./start-agent.sh
```

The script installs dependencies via `uv`, starts the mock ride API, and launches an interactive chat in your terminal.

## What It Does

You talk to it like a person. It figures out the rest.

```
You ➤  Take me from home to work

  🔍 search_rides

Agent ➤  Here are your options from 1350 S Bascom Ave to Stanford Health Center:
         - UberX: $28-$38, ETA 4min, trip ~32min
         - Comfort: $38-$52, ETA 6min, trip ~32min
         - UberXL: $42-$56, ETA 9min, trip ~32min

You ➤  Comfort is good

  💰 get_quote

Agent ➤  Locked in at $42.80. Want me to book it?

You ➤  Yes

  ╭────────────────────────────────────────────────╮
  │  🚗  CONFIRMATION REQUIRED                     │
  │  The agent wants to BOOK this ride.            │
  │  Approve? (yes/no): yes                        │
  │  ✓ Approved                                    │
  ╰────────────────────────────────────────────────╯

Agent ➤  Ride booked! Driver Marcus (4.8★) in a White Honda Accord,
         arriving in 6 minutes.
```

On startup, you see your saved places, preferences, and ride history:

```
  Your Places:
    🏠  home → 1350 S Bascom Ave, San Jose, CA
    🏢  work → Stanford Health Center, Palo Alto, CA
  Default car: comfort  │  Confirm before booking: yes

  Recent Rides:
    ✅  1350 S Bascom Ave → Stanford Health Center (Uber Comfort, $42.80)
    ⏳  Stanford Health Center → 1350 S Bascom Ave (UberX, $31.20)
```

## Sessions

Each conversation is a named session with its own memory. Resume where you left off, or start fresh.

```bash
./start-agent.sh                            # default session
./start-agent.sh --new morning-commute      # new named session
./start-agent.sh --session morning-commute  # resume (prints history)
./start-agent.sh --sessions                 # list all sessions
./start-agent.sh --clear                    # delete all sessions
```

When you resume a session, you see your conversation history:

```
  Conversation History: (10 messages, 3 events, last active 2h ago)

    You ➤  Take me from home to work
    Agent ➤  Here are your options...
    You ➤  Book comfort
    Agent ➤  Ride booked! Driver arriving in 6 minutes.

  ──────────────────────────────────────────────────
  Resuming conversation...
```

## Natural Language for Everything

Manage places, preferences, and rides through conversation:

```
You ➤  Save gym as 200 Oak Ave, San Jose
Agent ➤  Saved! Your places: home, work, gym

You ➤  Change my default car to UberX
Agent ➤  Preference saved: default_car_type = uberx

You ➤  Take me from gym to home
Agent ➤  Here are your options from 200 Oak Ave to 1350 S Bascom Ave...

You ➤  What were my recent rides?
Agent ➤  Here are your last 3 rides...
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.

```
User Input
  → Input Guardrail (always on, blocks injection)
  → Memory System
      Short-term   Working       Episodic      Semantic
      (messages)   (active IDs)  (past rides)  (learned prefs)
      in-memory    SQLite        SQLite        SQLite
  → Agent Loop (Plan-Execute-Verify)
      Plan:    Build prompt with memory context → Claude API
      Execute: Validate → Gate check → Tool dispatch → Retry on failure
      Verify:  Update state → Record episode → Learn patterns → Persist
  → Output Guardrail (blocks leaked internals)
  → User
```

## Project Structure

```
marketplace-agent/
├── agent/                      # The AI agent
│   ├── main.py                 # Plan-Execute-Verify loop with memory
│   ├── memory.py               # Four-layer memory system (SQLite)
│   ├── ui.py                   # Terminal UI — colors, boxes, formatting
│   ├── config.py               # System prompt, tool definitions, constants
│   ├── tools.py                # Tool handlers → structured ToolResult
│   ├── gates.py                # Confirmation gates (book/cancel)
│   ├── validation.py           # Input validation (addresses, IDs)
│   ├── retry.py                # Exponential backoff decorator
│   └── __main__.py             # CLI entry point with session management
│
├── mcp_server/                 # Platform layer
│   ├── adapter.py              # Abstract RideAdapter interface
│   ├── adapters/uber.py        # Uber implementation
│   ├── guardrails.py           # Input/output pattern filters
│   ├── action_log.py           # Append-only audit trail
│   ├── profile.py              # Saved places, preferences, ride history
│   └── server.py               # MCP server (Claude Code integration)
│
├── server/                     # Mock Ride API
│   ├── app.py                  # FastAPI — 6 endpoints + health check
│   ├── models.py               # Pydantic schemas + state machine
│   └── simulation.py           # Geocoding, routing, pricing, drivers
│
├── tests/                      # 47 tests
│   ├── test_memory.py          # Memory system (25 tests)
│   ├── test_tools.py           # Tools + validation (12 tests)
│   └── test_simulation.py      # State machine + store (10 tests)
│
├── sessions/                   # Session databases (gitignored)
├── transcripts/                # Example conversations
├── start-agent.sh              # Launch script (uv-based)
├── .env.example                # API key template
└── pyproject.toml              # Dependencies
```

## Key Features

### Four-Layer Memory
| Layer | What It Stores | Persistence | Purpose |
|---|---|---|---|
| **Short-term** | Conversation messages | In-memory (pruned) | Context for Claude |
| **Working** | Active ride/estimate/quote IDs | SQLite | Crash recovery |
| **Episodic** | Past rides, errors, cancellations | SQLite | History and learning |
| **Semantic** | Preferred car type, frequent routes | SQLite | Gets smarter over time |

### Plan-Execute-Verify
Not a naive tool loop. Each turn:
1. **Plan** — Claude receives working memory, ride history, and learned preferences
2. **Execute** — Tools validate inputs, check gates, return structured results, retry on failure
3. **Verify** — State updates, episodes recorded, patterns learned, all persisted to SQLite

### Adapter Pattern
Swap Uber for Lyft by implementing one file. Agent, tools, gates, guardrails, and memory stay identical.

### Confirmation Gates
Book and cancel require explicit user approval — enforced in code, not model instructions. The agent literally cannot execute without typing "yes".

### Guardrails (Always On)
- **Input**: Blocks prompt injection, instruction extraction, role hijack
- **Output**: Catches leaked tool names, file paths, API details

### Structured Tool Results
Tools return `ToolResult(display, data)` — display text for the user, structured data for the state machine. No string parsing.

### Retry with Backoff
Claude API, ride service, and geocoding all retry with exponential backoff on transient failures.

### Concurrency Safety
`asyncio.Lock` on the ride store. Background tasks tracked and cancelled on graceful shutdown.

## Running Tests

```bash
uv run pytest tests/ -v
```

47 tests covering memory persistence, crash recovery, tool validation, state machine transitions, and concurrency safety.

## Configuration

Create `.env` from the template:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `UBER_API_BASE` | `http://localhost:8000` | Ride API URL |
| `AGENT_DEBUG` | unset | `1` for debug output |

## Mock Ride API

6 endpoints simulating a full ride lifecycle:

```
POST /v1/estimates              Search rides (geocoded, OSRM routed)
POST /v1/quotes                 Lock exact price (2 min TTL)
POST /v1/rides                  Book ride (async driver matching)
GET  /v1/rides/{id}             Status + driver + live fare
GET  /v1/rides/{id}/cancel-fee  Preview cancel cost
POST /v1/rides/{id}/cancel      Execute cancellation
GET  /health                    Health check
```

State machine: `processing → matched → arriving → in_progress → completed`

Test scenarios via `X-Scenario` header: `surge`, `no-drivers`, `driver-cancels`, `quote-expire`, `slow`.
