# Swapping Marketplaces: What Changes and What Breaks

## Two Very Different Swaps

"Plug in Lyft" and "plug in Zocdoc" sound similar but are fundamentally different problems.

**Lyft** is a same-domain swap — rides for rides. The adapter pattern handles this cleanly. One new file, everything else untouched.

**Zocdoc** is a cross-domain swap — rides for healthcare. The adapter interface itself doesn't fit. Almost everything rewrites.

---

## Lyft: Same Domain

### What changes

```
mcp_server/adapters/lyft.py    ← 1 new file
```

That's it. The `RideAdapter` interface was designed for rides. Lyft is rides. The adapter translates Lyft's API format into the same `SearchResult`, `QuoteResult`, `BookResult` dataclasses that Uber uses. The agent doesn't know the difference.

### What breaks first in production

**Minute 1: Auth fails.**
Our mock has no auth. Lyft uses OAuth2 with tokens that expire every 30-60 minutes. The adapter needs token refresh logic — retry on 401, get a new token, replay the request. Without this, nothing works.

**Minute 5: Rate limits hit.**
The surge advisor calls `adapter.search()` repeatedly. The status checker polls every few seconds. Lyft will throttle you. Add exponential backoff and request caching inside the adapter.

**Hour 1: Geocoding quality drops.**
We use Nominatim (free). Users type "Starbucks near me" — Nominatim fails, Google Maps would succeed. With a real platform, they geocode for you, but our `profile.resolve_address()` passes raw strings. If Lyft's geocoder is pickier, the same saved address might work on Uber and fail on Lyft.

**Hour 1: Quote model mismatch.**
Our flow: search → quote → book (3 steps). Lyft gives upfront pricing in the search response — no separate quote step. The adapter has to fake a quote by caching the search result:

```python
def quote(self, estimate_id, car_type_id):
    # No API call — price was already in search response
    cached = self._estimates[estimate_id]
    return QuoteResult(price=cached[car_type_id].price, ...)
```

This works but it's a leaky abstraction. The "quote expires in 2 minutes" concept doesn't apply — the price was never separately locked.

**Day 1: Webhook gap.**
`check_status` polls the API every time the user asks. Real platforms push updates via webhooks. Polling at scale = rate limit death. This isn't an adapter fix — it's an architecture change (webhook receiver + cache layer).

**Week 1: Concurrent users collide.**
Mock server has one in-memory store. Two users see each other's rides. Need per-user state isolation (Redis/Postgres).

### Lyft production priority

| Priority | Issue | Fix location | Effort |
|----------|-------|-------------|--------|
| P0 | OAuth2 token refresh | `adapters/lyft.py` | 1 day |
| P0 | Rate limit + backoff | `adapters/lyft.py` | 1 day |
| P1 | Quote model shimming | `adapters/lyft.py` | Half day |
| P1 | Geocoder fallback | `adapters/lyft.py` | 1 day |
| P2 | Webhook receiver | New infra layer | 3 days |
| P2 | User isolation | State layer rewrite | 2 days |

**Key insight**: For Lyft, every P0/P1 fix is contained inside the adapter. The agent, tools, gates, guardrails, and logging don't change. The adapter pattern does exactly what it was designed to do.

---

## Zocdoc: Different Domain

### What changes

Almost everything.

```
Layer                        What happens
──────────────────────────────────────────────────────
mcp_server/adapter.py        REWRITE — RideAdapter → AppointmentAdapter
  SearchResult               → AvailabilityResult
  RideOption                 → DoctorSlot (name, specialty, rating, times, copay)
  QuoteResult                → GONE (copay known upfront or after insurance)
  BookResult                 → AppointmentConfirmation
  StatusResult               → AppointmentStatus
  CancelFee                  → Different rules (free >24hrs, fee <24hrs)
  Driver                     → GONE
  Surge                      → GONE
  Vehicle                    → GONE

mcp_server/adapters/uber.py  DELETE
mcp_server/adapters/zocdoc.py NEW

agent/config.py (TOOLS)      REWRITE
  search_rides               → search_doctors(specialty, location, insurance, date)
  get_quote                  → GONE or check_copay(doctor_id, insurance)
  book_ride                  → book_appointment(doctor_id, time_slot)
  check_status               → check_appointment(appointment_id)
  cancel_ride                → cancel_appointment(appointment_id)
  check_surge                → GONE
  save_place                 → save_doctor / save_insurance

agent/config.py (PROMPT)     REWRITE
  "ride-booking assistant"   → "healthcare appointment assistant"
  "contiguous US only"       → "in-network providers only"
  surge/pricing rules        → insurance/copay rules

agent/tools.py               REWRITE — every handler changes
agent/state.py               REWRITE — appointment_id, not ride_id
mcp_server/profile.py        REWRITE — insurance, saved doctors, not places/cars

agent/main.py (loop)         SAME ✓
agent/gates.py               SAME concept, different text
agent/display.py             SAME ✓
mcp_server/action_log.py     SAME ✓
mcp_server/guardrails.py     UPDATE — different leak patterns
start-agent.sh               SAME ✓

server/                      REWRITE — mock Zocdoc API, not mock Uber
  OSRM route validation      → GONE
  US bounding box            → In-network provider check
  Geocoding                  → Specialty/location matching
```

### What breaks first in production

**Minute 1: Everything from Lyft, plus...**

Auth, rate limits, geocoding — same problems. But healthcare adds new categories of breakage.

**Hour 1: Insurance verification fails.**
User says "find me a dermatologist." Agent searches. Results come back. User picks one. But the doctor doesn't accept their insurance. Our system has no concept of insurance — it's not in the profile, not in the search, not validated anywhere.

**Fix**: Add insurance to profile. Pass it in every search. Filter results by in-network status. This touches profile, tools, adapter, and prompt.

**Hour 1: The 3-step flow doesn't map.**
Rides: search → quote → book. Clean pipeline.
Healthcare: search → check insurance → check availability → book → verify patient info → confirm. It's not 3 steps, it's 6, with branching logic.

The agent loop in `main.py` handles multi-step tool calls fine. But the tool definitions and adapter interface assume a linear search → quote → book pipeline. Healthcare isn't linear.

**Day 1: HIPAA compliance.**
Action log records everything — tool calls, params, results. With healthcare, that includes patient names, insurance IDs, medical specialties. `action_log.jsonl` is a plaintext file on disk. That's a HIPAA violation.

**Fix**: Encrypt the log. Redact PII before writing. Add access controls. This is not an adapter problem — it's an infrastructure problem.

**Day 1: Confirmation gates need more context.**
Ride gate: "Book UberX at $13.20? (yes/no)"
Healthcare gate: "Book appointment with Dr. Sarah Chen, Dermatology, Tuesday March 4 at 2:30pm, copay $40, at 123 Medical Plaza? (yes/no)"

The gate function works but needs to display much richer context. The adapter dataclasses need to carry more fields to support this.

**Week 1: Cancellation rules are time-based, not state-based.**
Rides: cancel fee depends on ride state (processing=$0, matched=$5, in-progress=$10+metered).
Healthcare: cancel fee depends on time until appointment (>24hrs=free, <24hrs=$50, no-show=$100).

The `CancelFee` dataclass and the cancel flow work differently. The adapter can normalize this, but the agent needs to understand "you can cancel for free if you do it before tomorrow" — that's a prompt concern, not just an adapter concern.

### Zocdoc production priority

| Priority | Issue | Fix location | Effort |
|----------|-------|-------------|--------|
| P0 | New adapter interface | `adapter.py` | 2 days |
| P0 | New tool definitions | `config.py`, `tools.py` | 2 days |
| P0 | Insurance in profile + search | Profile, adapter, tools | 2 days |
| P0 | New system prompt | `config.py` | 1 day |
| P0 | HIPAA-compliant logging | `action_log.py` + infra | 3 days |
| P1 | Multi-step booking flow | Tools + adapter | 2 days |
| P1 | Time-based cancel rules | Adapter + prompt | 1 day |
| P2 | Patient verification | New tool + adapter method | 2 days |

**Key insight**: For Zocdoc, almost nothing is adapter-contained. The adapter interface itself is wrong. You're not swapping an implementation — you're swapping the domain model.

---

## What Actually Survives Across Domains

```
Reusable (domain-agnostic):           ~40% of codebase
  ✓ agent/main.py         → conversation loop
  ✓ agent/gates.py        → confirmation pattern
  ✓ agent/display.py      → guardrailed output
  ✓ mcp_server/action_log → audit trail
  ✓ mcp_server/guardrails → input/output filtering (patterns update)
  ✓ start-agent.sh        → launch script

Domain-specific (rewrite per domain):  ~60% of codebase
  ✗ adapter interface + dataclasses
  ✗ adapter implementation
  ✗ tool definitions + handlers
  ✗ system prompt
  ✗ state tracker
  ✗ user profile schema
  ✗ mock API server + validation
```

## The Right Architecture for Multi-Domain

The current codebase mixes framework and domain code. To support multiple marketplaces across domains, split them:

```
framework/              ← never changes per marketplace
  loop.py               → conversation loop + model calls
  gates.py              → confirmation gate pattern
  guardrails.py         → input/output filtering
  action_log.py         → audit trail
  display.py            → safe output

domains/
  rides/                ← Uber, Lyft
    adapter.py          → RideAdapter + ride dataclasses
    adapters/uber.py
    adapters/lyft.py
    tools.py            → search_rides, book_ride, etc.
    config.py           → ride system prompt + tool schemas
    state.py            → ride_id tracking
    profile.py          → saved places, car preferences
    mock_server/        → mock ride API + OSRM validation

  healthcare/           ← Zocdoc, One Medical
    adapter.py          → AppointmentAdapter + healthcare dataclasses
    adapters/zocdoc.py
    tools.py            → search_doctors, book_appointment, etc.
    config.py           → healthcare system prompt + tool schemas
    state.py            → appointment_id tracking
    profile.py          → insurance, saved doctors
    mock_server/        → mock appointment API + insurance validation
```

Launch with: `DOMAIN=rides ./start-agent.sh` or `DOMAIN=healthcare ./start-agent.sh`

The framework handles **how** the agent works.
The domain handles **what** it does.

- Uber → Lyft: swap one adapter file inside `domains/rides/`
- Rides → Healthcare: swap the entire domain folder. Framework untouched.

---

## Bottom Line

| Swap | Files changed | Effort | What breaks in prod |
|------|--------------|--------|-------------------|
| Uber → Lyft | 1 | 1 day | Auth, rate limits, quote model (all in adapter) |
| Uber → Zocdoc | ~12 | 2 weeks | Everything above + domain model, compliance, flow mismatch |
| Any → production | Varies | Varies | Auth (minute 1), rate limits (minute 5), geocoding (hour 1), webhooks (week 1) |

The adapter pattern is the right call for same-domain swaps. For cross-domain, you need a framework/domain split — which this codebase is one refactor away from.
