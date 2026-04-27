# Architecture

## Overview

The marketplace agent uses a **Plan-Execute-Verify** architecture with a **four-layer memory system** and **named sessions**. It books rides reliably, recovers from crashes, remembers conversation history across sessions, and learns from user behavior over time.

```
┌──────────────────────────────────────────────────────────┐
│                         User                             │
└──────────────────────────┬───────────────────────────────┘
                           │
                    [Input Guardrail]
                    Always on. Blocks injection.
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                    MEMORY SYSTEM                         │
│                                                         │
│  Short-term     Working        Episodic      Semantic   │
│  (messages)     (active IDs)   (past rides)  (prefs)    │
│  in-memory      SQLite         SQLite        SQLite     │
│  auto-pruned    crash-safe     100 entries   permanent  │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                    AGENT LOOP                            │
│                                                         │
│  1. PLAN    Build system prompt with memory context      │
│             Send to Claude with tool definitions         │
│                                                         │
│  2. EXECUTE Validate inputs (addresses, IDs)             │
│             Check confirmation gates (book/cancel)       │
│             Run tool handler with retry on failure       │
│                                                         │
│  3. VERIFY  Update working memory from structured data   │
│             Record episode (rides, errors, cancels)      │
│             Learn patterns (car prefs, routes)           │
│             Persist all state to SQLite                  │
│             Log to conversation history for replay       │
└──────────────────────────┬───────────────────────────────┘
                           │
                    [Output Guardrail]
                    Blocks leaked internals.
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                         User                             │
└──────────────────────────────────────────────────────────┘
```

## Memory System

### Why Four Layers?

A flat message list doesn't work for agents. It grows unboundedly, loses context on crashes, and can't learn. Each layer solves a specific problem:

| Layer | Problem | Storage | Lifetime |
|---|---|---|---|
| **Short-term** | Claude needs conversation context | In-memory list | Current session (pruned at 120K tokens) |
| **Working** | Agent needs active ride/estimate IDs | SQLite | Persists across crashes |
| **Episodic** | Agent benefits from past ride history | SQLite | Last 100 events |
| **Semantic** | Agent should learn user preferences | SQLite | Permanent |

### Short-term Memory

The conversation messages sent to Claude. Not just a raw list:

- **Auto-pruned** when token estimate exceeds 120K (at ~4 chars/token)
- **Summarized before pruning** — old messages condensed into a context summary
- Keeps first 2 messages (session start) and last 6 (current turn)
- Summary preserves key state (IDs, last actions) so the agent doesn't lose track

### Working Memory

Active entities the agent is manipulating:

```python
@dataclass
class WorkingMemory:
    active_ride_id: str | None
    last_estimate_id: str | None
    last_quote_id: str | None
    ride_status: str | None
    pending_action: str | None
    last_error: str | None
```

Updated from **structured tool result data** — not string parsing. Persisted to SQLite on every tool call. On crash recovery, the agent checks if the ride still exists on the server and either resumes or clears stale state.

### Episodic Memory

Past events the agent can reference:

- `ride_booked` — "Booked Uber Comfort for $42.80 from 1350 S Bascom Ave"
- `ride_completed` — "Ride completed. Final fare: $42.80"
- `ride_canceled` — "Canceled ride. Fee: $0.00, Refund: $42.80"
- `error` — "Quote expired before booking"
- `gate_denied` — "User denied booking"

Injected into the system prompt as ride history. Claude can reference past rides naturally.

### Semantic Memory

Learned patterns stored as key-value pairs with confidence:

- `preferred_car_type` = "Comfort" (0.8 confidence — learned from bookings)
- `explicit_pref_always_confirm` = "true" (1.0 — explicitly set by user)

Updated automatically:
- First booking of a car type → stored at 0.6 confidence
- Switching car types → updated at 0.8 confidence
- Explicit preference via conversation → stored at 1.0 confidence

### Conversation Log

All user and assistant messages are persisted to SQLite's `conversation_log` table. On session resume, the last 10 messages are displayed so you can see where you left off. This is separate from short-term memory — the log is for display, short-term memory is for Claude's API context.

## Sessions

Each session is a separate SQLite database in `sessions/`:

```
sessions/
├── default.db           # default session
├── morning-commute.db   # named session
└── airport-trip.db      # another named session
```

Each database contains:
- `conversation_log` — full message history for replay
- `working_state` — active ride/estimate/quote IDs
- `episodic` — past events
- `semantic` — learned preferences
- `conversation_summary` — pruned conversation context

Session management:
```bash
python -m agent                           # default session
python -m agent --new morning-commute     # create named session
python -m agent --session morning-commute # resume with history
python -m agent --sessions               # list all
python -m agent --clear                  # delete all sessions
```

On resume, the agent:
1. Loads conversation history and prints last 10 messages
2. Shows session stats (message count, events, last active time)
3. Checks for active rides and verifies they still exist on the server
4. Loads learned preferences into the system prompt
5. Continues the conversation with full context

## Tool Architecture

### Structured Results

Every tool returns a `ToolResult` with separate display and data:

```python
@dataclass
class ToolResult:
    display: str   # Human-readable text sent to Claude
    data: dict     # Machine-readable data for state tracking
```

This replaced string parsing:

```python
# Before (fragile — any format change breaks state tracking)
for line in result.split("\n"):
    if line.startswith("Estimate ID:"):
        self.last_estimate = line.split(": ", 1)[1]

# After (structured — state updates from typed data)
self.working.update_from_tool("search_rides", result.data)
# result.data = {"estimate_id": "est_abc123", "pickup": "...", ...}
```

### Input Validation

All tool inputs validated before execution:

- **Addresses**: Non-empty, stripped, max 200 chars
- **IDs**: Non-empty, stripped, max 64 chars
- Validation errors return a `ToolResult` with error data — not exceptions

### Error Recovery

Tools catch adapter errors and return recovery hints:

- `QUOTE_EXPIRED` → "Try getting a new quote with the same estimate_id"
- `ESTIMATE_EXPIRED` → "Try searching for rides again"
- Connection errors → "Could not connect to ride service"

Claude sees the hint and self-corrects.

### Ride History at Booking

Rides save to the user profile at booking time (not just completion). This means even if the server restarts or the ride never completes, it still appears in ride history with a status indicator:

- ⏳ Processing / in progress
- ✅ Completed
- ❌ Canceled

## User Profile

Persisted in `user_profile.json`. Managed through natural conversation:

```
"Save gym as 200 Oak Ave"        → profile.save_place("gym", "200 Oak Ave")
"Change my home to 500 Main St"  → profile.save_place("home", "500 Main St")
"Set default car to UberX"       → profile.save_preference("default_car_type", "uberx")
"Take me from home to gym"       → resolves "home" and "gym" to real addresses
```

Shown on startup:
```
Your Places:
  🏠  home → 1350 S Bascom Ave, San Jose, CA
  🏢  work → Stanford Health Center, Palo Alto, CA
Default car: comfort  │  Confirm before booking: yes
```

## Concurrency Model

### Server (FastAPI)

The mock API uses an in-memory `Store` for ride state. Concurrent access protected by `asyncio.Lock`:

```python
class Store:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.rides = {}
```

All critical sections acquire the lock:

```python
async with store.lock:
    ride.transition(RideStatus.MATCHED)
```

### Background Tasks

Driver matching runs as background `asyncio.Task`s:

- **Tracked** in a global set (not fire-and-forget)
- **Cancelled on shutdown** via FastAPI lifespan handler
- **Lock-aware** — each state transition acquires `store.lock`

### State Machine

Ride transitions validated against an explicit table:

```python
VALID_TRANSITIONS = {
    PROCESSING: [MATCHED, NO_DRIVERS, CANCELED],
    MATCHED:    [ARRIVING, CANCELED, PROCESSING],  # PROCESSING = driver cancel
    ARRIVING:   [IN_PROGRESS, CANCELED],
    IN_PROGRESS:[COMPLETED, CANCELED],
    COMPLETED:  [],
    CANCELED:   [],
    NO_DRIVERS: [],
}
```

The `MATCHED → PROCESSING` transition handles the driver-cancel scenario — driver accepts, then cancels, and the system re-matches.

## Guardrails

Always active. Not configurable.

### Input Guard
Regex patterns that block:
- Prompt injection ("ignore previous instructions")
- Instruction extraction ("what is your system prompt")
- Role hijacking ("pretend you are")

Blocked inputs get: "I'm a ride booking assistant. Where would you like to go?"

### Output Guard
Catches leaked internals in Claude's responses:
- Tool names, file paths, API URLs
- System prompt content
- Technical jargon

### Confirmation Gates
Book and cancel gated at the code level. Claude cannot bypass — the user must type "yes" in a styled confirmation box.

## Terminal UI

The agent uses ANSI colors and box drawing for a polished terminal experience:

- Colored banner on startup
- Model selector with icons (✨ Sonnet, 🧠 Opus, ⚡ Haiku)
- Green `You ➤` prompt, blue `Agent ➤` responses
- Tool call indicators (🔍 search, 💰 quote, 🚗 book, 📍 status)
- Yellow bordered confirmation boxes
- Thinking spinner during API calls
- Session info, saved places, and ride history on startup
- Conversation history replay on session resume

## Retry Logic

All external calls have retry with exponential backoff:

| Call | Max Attempts | Retryable Errors |
|---|---|---|
| Claude API | 3 | ConnectionError, RateLimitError, InternalServerError |
| Ride adapter | 3 | RequestError, TimeoutException |
| Geocoding | 3 | Network errors |

Not retried: auth errors, validation errors, business logic errors (expired quotes, bad addresses).

## Adapter Pattern

The agent talks to rides through an abstract `RideAdapter`:

```python
class RideAdapter(ABC):
    def search(pickup, dropoff) -> SearchResult
    def quote(estimate_id, car_type_id) -> QuoteResult
    def book(quote_id) -> BookResult
    def status(ride_id) -> StatusResult
    def cancel(ride_id) -> CancelResult
    def cancel_fee(ride_id) -> CancelFeeResult
```

To add Lyft: create `mcp_server/adapters/lyft.py`, implement `RideAdapter`, change one line in config. Everything else stays identical.

## Testing

47 tests across three modules:

```bash
uv run pytest tests/ -v
```

| Module | Tests | Covers |
|---|---|---|
| `test_memory.py` | 25 | All four memory layers, persistence, recovery, pruning, sessions |
| `test_tools.py` | 12 | Validation, dispatch, error handling, structured results |
| `test_simulation.py` | 10 | State machine transitions, store locking, ID generation |

## Data Flow: Search → Quote → Book

```
User: "Take me from home to work"

1. Input guardrail passes
2. Message added to short-term memory + conversation log
3. System prompt built with:
   - Working memory (no active ride)
   - Episodic history (last 5 rides)
   - Semantic memory (prefers Comfort)
4. Claude calls search_rides(pickup="home", dropoff="work")
5. "home" resolved to "1350 S Bascom Ave" via profile
6. Input validated (non-empty, length OK)
7. Adapter calls mock API (with retry)
8. ToolResult returned:
   display: "UberX: $28-38, Comfort: $38-52..."
   data: {estimate_id: "est_abc", options: [...]}
9. Working memory: last_estimate_id = "est_abc"
10. Persisted to SQLite

... (quote similar) ...

11. book_ride triggers confirmation gate
12. User types "yes" in styled box
13. Booking succeeds → ToolResult with ride_id
14. Ride saved to profile.recent_rides immediately
15. Episode recorded: "ride_booked"
16. Semantic: preferred_car_type updated
17. Working: active_ride_id set
18. All persisted to SQLite
```

## Crash Recovery

```
Agent crashes mid-ride

1. User restarts: ./start-agent.sh --session morning-commute
2. MemoryStore loads SQLite
3. Conversation history printed (last 10 messages)
4. recover_state() finds active_ride_id = "ride_123"
5. Agent checks with server: does ride_123 still exist?
   - Yes → prints "Recovered active ride" → user continues
   - No → clears stale state → prints "Previous ride cleared"
6. Conversation resumes with full context
```
