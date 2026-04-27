# Transcript 3: Bad Address

User gives invalid/ambiguous addresses. Agent handles errors gracefully, helps resolve, saves new place.

---

## Setup

```
Mode: Agent (start-agent.sh)
Scenario: normal
Profile: home=2111 7th Ave Seattle WA, work=Salesforce Tower SF
```

---

## Conversation

**User:** Get me a ride from asdfghjkl to work

**Agent:** *(calls `search_rides(pickup="asdfghjkl", dropoff="work", reasoning="User provided what looks like a nonsense pickup address. Trying anyway — the geocoder will reject it if invalid.")`)*

```
Error: BAD_PICKUP_ADDRESS: Could not geocode pickup address 'asdfghjkl'.
Please provide a valid address, landmark, or business name.
```

I couldn't find a location for "asdfghjkl" — the geocoder didn't recognize it. Could you give me a real address, landmark, or business name? Something like:
- "Starbucks, Mission District, SF"
- "123 Main St, San Francisco"
- Or just say "home" to use your saved address

---

**User:** Ok take me from my apartment

**Agent:** "My apartment" isn't a saved place in your profile. Your saved places are:
- **home** → 2111 7th Ave, Seattle, WA
- **work** → Salesforce Tower, San Francisco

Is "my apartment" the same as "home"? Or do you want to give me a different address and save it?

---

**User:** Yeah that's home

**Agent:** *(calls `search_rides(pickup="home", dropoff="work", reasoning="User confirmed 'my apartment' = home. Using saved alias.")`)*

```
📍 Pickup: 2111 7th Ave, Seattle, WA
📍 Dropoff: Salesforce Tower, 415 Mission St, San Francisco, CA
🆔 Estimate ID: est_m1n2o3

              │    UberX     │   Comfort    │   UberXL     │    Black
─────────────┼──────────────┼──────────────┼──────────────┼──────────────
💰 Price     │   $12-$15    │   $18-$22    │   $22-$27    │   $35-$42
...
```

Found it! Here are your options from home to work. Want me to get an UberX quote (your default)?

---

**User:** Actually take me to my friend Jake's place at 555 made up boulevard

**Agent:** *(calls `search_rides(pickup="home", dropoff="555 made up boulevard", reasoning="User wants to go to a new address. Trying the address as-is for geocoding.")`)*

```
Error: BAD_DROPOFF_ADDRESS: Could not geocode dropoff address '555 made up boulevard'.
Please provide a valid address, landmark, or business name.
```

"555 Made Up Boulevard" didn't match any real location. Could you double-check the address? Maybe include the city or neighborhood:
- "555 Some Street, **San Francisco**"
- "Jake's building near **Mission District**"

---

**User:** Oh right, it's 555 Castro Street, San Francisco

**Agent:** *(calls `search_rides(pickup="home", dropoff="555 Castro Street, San Francisco", reasoning="User corrected the dropoff address with city included.")`)*

```
📍 Pickup: 2111 7th Ave, Seattle, WA
📍 Dropoff: 555 Castro St, San Francisco, CA 94114
🆔 Estimate ID: est_p4q5r6

              │    UberX     │   Comfort    │   UberXL     │    Black
─────────────┼──────────────┼──────────────┼──────────────┼──────────────
💰 Price     │   $10-$13    │   $15-$19    │   $19-$24    │   $30-$37
⏱️  ETA      │    4 min     │    6 min     │    8 min     │    5 min
🚗 Trip      │  3.1mi 11m   │  3.1mi 11m   │  3.1mi 11m   │  3.1mi 11m
👥 Seats     │      4       │      4       │      6       │      4

✦ Best value: UberX ($10-$13)
```

Found it — 555 Castro St. That's a 3.1-mile trip, about 11 minutes. Want me to save this as "Jake's place" so you can just say that next time?

---

**User:** Yeah save it

**Agent:** *(calls `save_place(name="jake's place", address="555 Castro Street, San Francisco")`)*

```
Saved 'jake's place' = 555 Castro Street, San Francisco

All saved places:
  home: 2111 7th Ave, Seattle, WA
  work: Salesforce Tower, San Francisco
  jake's place: 555 Castro Street, San Francisco
```

Done! Next time you can just say "take me to Jake's place." Want me to get a quote for this ride?

---

**User:** Take me from home to home

**Agent:** *(calls `search_rides(pickup="home", dropoff="home", reasoning="User said home to home — same address. The API will reject this.")`)*

```
Error: SAME_ADDRESS: Pickup and dropoff addresses are the same location.
```

Pickup and dropoff can't be the same place — both resolve to 2111 7th Ave, Seattle. Did you mean a different destination?

---

## Action Log

```
📋 Action Log (recent):
  ❌ search_rides: Search rides from 'asdfghjkl' to 'work' → FAILED
        💭 User provided nonsense pickup. Trying anyway — geocoder will reject.
  ✅ search_rides: Search rides from 'home' to 'work' → OK
        💭 User confirmed 'my apartment' = home. Using saved alias.
  ❌ search_rides: Search rides from 'home' to '555 made up boulevard' → FAILED
        💭 User wants to go to a new address. Trying as-is.
  ✅ search_rides: Search rides from 'home' to '555 Castro Street, SF' → OK
        💭 User corrected the dropoff address with city included.
  ✅ save_place: Save place 'jake's place' → OK
  ❌ search_rides: Search rides from 'home' to 'home' → FAILED
        💭 User said home to home — same address. API will reject.
```

## Key Behaviors Demonstrated

1. **Graceful error handling** — nonsense address gets a helpful suggestion, not a stack trace
2. **Alias awareness** — agent knows what's saved and asks if "my apartment" = "home"
3. **Learn and save** — after user corrects an address, agent offers to save it
4. **Same-address guard** — API rejects same pickup/dropoff, agent explains clearly
5. **Decision trace** — every attempt logged with reasoning, including the failures
