# Architecture

## Overview

The marketplace agent uses a **Plan-Execute-Verify** architecture with a **four-layer memory system**. It's designed to book rides reliably, recover from errors, and learn from user behavior over time.

```
+----------------------------------------------------------+
|                        User                               |
+---------------------------+------------------------------+
                            |
                     [Input Guardrail]
                     Blocks injection, off-topic
                            |
                            v
+----------------------------------------------------------+
|                    MEMORY SYSTEM                          |
|                                                          |
|  Short-term    Working       Episodic      Semantic       |
|  (messages)    (active IDs)  (past rides)  (preferences) |
|  in-memory     SQLite        SQLite        SQLite        |
+---------------------------+------------------------------+
                            |
                            v
+----------------------------------------------------------+
|                    AGENT LOOP                             |
|                                                          |
|  1. PLAN    - Build system prompt with memory context     |
|             - Send to Claude with tool definitions        |
|                                                          |
|  2. EXECUTE - Validate inputs                            |
|             - Check confirmation gates (book/cancel)      |
|             - Run tool handler                           |
|             - Retry on transient failures                |
|                                                          |
|  3. VERIFY  - Update working memory from structured data  |
|             - Record episodes (rides, errors, cancels)    |
|             - Learn patterns (car preferences, routes)    |
|             - Persist state to SQLite                    |
+---------------------------+------------------------------+
                            |
                     [Output Guardrail]
                     Blocks leaked internals
                            |
                            v
+----------------------------------------------------------+
|                        User                               |
+----------------------------------------------------------+
```

## Memory System

### Why Four Layers?

A flat message list doesn't work for agents. It grows unboundedly, loses context on crashes, and can't learn. Each memory layer solves a specific problem:

| Layer | Problem It Solves | Storage | Lifetime |
|---|---|---|---|
| **Short-term** | Claude needs conversation context | In-memory list | Current session (pruned) |
| **Working** | Agent needs to know active ride IDs and status | SQLite | Persists across crashes |
| **Episodic** | Agent benefits from knowing what happened before | SQLite | Last 100 events |
| **Semantic** | Agent should learn user preferences over time | SQLite | Permanent |

### Short-term Memory

The conversation message list sent to Claude. Unlike a naive approach:

- **Pruned automatically** when token count exceeds 120K (estimated at ~4 chars/token)
- **Summarized before pruning** -- old messages are condensed into a summary injected at the start
- Keeps first 2 messages (session start) and last 6 (current turn)
- Summary includes key state (IDs, last actions) so the agent doesn't lose track

### Working Memory

Active entities the agent is manipulating right now:

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

Updated from **structured tool results** (not string parsing). Persisted to SQLite on every tool call. On crash recovery, the agent knows it has an active ride and can resume.

### Episodic Memory

Past events the agent can reference:

- `ride_completed` -- "Downtown to Airport, $35, UberX"
- `ride_canceled` -- "Canceled at matched stage, fee $0"
- `error` -- "Quote expired before booking"
- `gate_denied` -- "User denied booking"

Injected into the system prompt as ride history. The agent can reference past rides naturally ("last time you went to the airport it was $35").

### Semantic Memory

Learned patterns stored as key-value pairs:

- `preferred_car_type` = "Comfort" (learned from booking patterns)
- `explicit_pref_always_confirm` = "true" (explicitly set by user)

Updated automatically:
- First booking of a car type -> stored with 0.6 confidence
- Switching car types -> updated with 0.8 confidence
- Explicit user preference -> stored with 1.0 confidence

## Tool Architecture

### Structured Results

Every tool returns a `ToolResult` with separate display and data:

```python
@dataclass
class ToolResult:
    display: str   # Human-readable text sent to Claude
    data: dict     # Machine-readable data for state tracking
```

This replaces the old approach of parsing strings like `"Estimate ID: est_abc123"` with brittle regex. Now:

```python
# Old (fragile)
for line in result.split("\n"):
    if line.startswith("Estimate ID:"):
        self.last_estimate = line.split(": ", 1)[1]

# New (structured)
self.working.update_from_tool("search_rides", result.data)
# result.data = {"estimate_id": "est_abc123", "pickup": "...", ...}
```

### Dispatch Table

Tools are registered in a dispatch table and executed through a single `execute()` function:

```
search_rides  -> _search_rides()  -> ToolResult
get_quote     -> _get_quote()     -> ToolResult
book_ride     -> _book_ride()     -> ToolResult
check_status  -> _check_status()  -> ToolResult
cancel_ride   -> _cancel_ride()   -> ToolResult
save_place    -> _save_place()    -> ToolResult
...
```

### Input Validation

All tool inputs are validated before execution:

- **Addresses**: Non-empty, stripped, max 200 chars
- **IDs**: Non-empty, stripped, max 64 chars
- Validation errors return a `ToolResult` with error data, not exceptions

### Error Recovery

Tools catch `AdapterError` and return recovery hints:

- `QUOTE_EXPIRED` -> "Try getting a new quote with the same estimate_id"
- `ESTIMATE_EXPIRED` -> "Try searching for rides again"
- Connection errors -> "Could not connect to ride service"

The agent sees these hints and can self-correct without user intervention.

## Concurrency Model

### Server (FastAPI)

The mock API uses an in-memory `Store` for ride state. Concurrent access is protected by `asyncio.Lock`:

```python
class Store:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.rides = {}
        self.estimates = {}
        self.quotes = {}
```

All critical sections (ride creation, state transitions, cancellation) acquire the lock:

```python
async with store.lock:
    ride.transition(RideStatus.MATCHED)
```

### Background Tasks

Driver matching runs as background `asyncio.Task`s. These are:

- **Tracked** in a global set (not fire-and-forget)
- **Cancelled on shutdown** via the FastAPI lifespan handler
- **Lock-aware** -- each state transition acquires `store.lock`

### State Machine

Ride transitions are validated against an explicit transition table:

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

Invalid transitions raise `InvalidTransition`. The driver-cancel scenario (`MATCHED -> PROCESSING`) is explicitly allowed.

## Guardrails

Always active. Not configurable via environment variable.

### Input Guard

Regex-based pattern matching that blocks:

- Prompt injection ("ignore previous instructions", "you are now...")
- Instruction extraction ("what is your system prompt", "show me your tools")
- Role hijacking ("pretend you are", "act as")

Blocked inputs get a generic response: "I'm a ride booking assistant. Where would you like to go?"

### Output Guard

Catches leaked internal details in Claude's responses:

- Tool names, file paths, API URLs
- System prompt content, configuration details
- Technical jargon that shouldn't be user-facing

### Confirmation Gates

Book and cancel operations are gated at the code level:

```python
if tool_name in GATED_TOOLS:
    approved = confirmation_gate(tool_name, tool_input, adapter, log)
    if not approved:
        return "USER DENIED this action."
```

The agent cannot bypass this. Even if Claude decides to book, the code stops execution until the user types "yes".

## Retry Logic

All external calls have retry with exponential backoff:

| Call | Retries | Retryable Errors |
|---|---|---|
| Claude API | 3 | ConnectionError, RateLimitError, InternalServerError |
| Ride adapter (httpx) | 3 | RequestError, TimeoutException |
| Geocoding (Nominatim) | 3 | Network errors |

Not retried: authentication errors, validation errors, business logic errors (quote expired, bad address).

## Adapter Pattern

The agent talks to rides through an abstract `RideAdapter`:

```python
class RideAdapter(ABC):
    def search(self, pickup, dropoff) -> SearchResult
    def quote(self, estimate_id, car_type_id) -> QuoteResult
    def book(self, quote_id) -> BookResult
    def status(self, ride_id) -> StatusResult
    def cancel(self, ride_id) -> CancelResult
    def cancel_fee(self, ride_id) -> CancelFeeResult
```

To swap Uber for Lyft:
1. Create `mcp_server/adapters/lyft.py` implementing `RideAdapter`
2. Change one line in agent config: `adapter = LyftAdapter()`
3. Everything else (tools, gates, guardrails, memory) stays the same

## Data Flow

### Happy Path: Search -> Quote -> Book

```
User: "Take me from home to work"
  |
  v
1. Input guardrail passes
2. Message added to short-term memory
3. System prompt built with:
   - Working memory (no active ride)
   - Episodic history (last 5 rides)
   - Semantic memory (prefers Comfort)
4. Claude decides: call search_rides(pickup="home", dropoff="work")
5. Input validated (address length, non-empty)
6. "home" resolved to real address via profile
7. Adapter calls mock API
8. ToolResult returned:
   display: "Estimate ID: est_abc...\n- UberX: $12-$16..."
   data: {"estimate_id": "est_abc", "options": [...]}
9. Working memory updated: last_estimate_id = "est_abc"
10. Persisted to SQLite
11. Claude sees options, suggests quoting
12. ... (quote flow similar)
13. book_ride triggers confirmation gate
14. User approves
15. Booking succeeds
16. Episode recorded: "ride_booked"
17. Semantic: preferred_car_type updated
18. Working: active_ride_id set
```

### Crash Recovery

```
Agent crashes mid-ride
  |
  v
1. New agent starts
2. MemoryStore loads SQLite
3. recover_state() finds active_ride_id = "ride_123"
4. Prints: "[Recovered active ride: ride_123 (status: matched)]"
5. User can continue: "What's my ride status?"
6. Agent checks ride_123, resumes normally
```

## Testing

47 tests covering:

- **Memory system** (25 tests): All four layers, persistence, recovery, pruning
- **Tools** (12 tests): Validation, dispatch, error handling, structured results
- **Simulation** (10 tests): State machine transitions, store operations, concurrency safety

```bash
uv run pytest tests/ -v
```
