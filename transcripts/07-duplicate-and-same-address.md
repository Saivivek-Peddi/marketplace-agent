# Transcript 7: Duplicate Booking & Same Address

Tests duplicate ride prevention and same-address rejection.

---

## Setup

```
Mode: Agent (start-agent.sh)
Scenario: normal
Profile: home=2111 7th Ave, Seattle, WA, work=Salesforce Tower, SF
```

---

## Scenario A: Duplicate Booking

**User:** Book me a ride from home to work

*(Agent searches, quotes $18.50 Comfort, user confirms)*

```
Ride booked!
Ride ID: ride_abc123
Status: processing
Product: Comfort
Price: $18.50
Pickup: 2111 7th Ave, Seattle, WA
```

Your ride is booked. Looking for a driver.

---

**User:** Actually book me another ride to the gym too

*(Agent searches, quotes, user confirms)*

```
Error: DUPLICATE_RIDE: Active ride 'ride_abc123' already exists.
Cancel it first or wait for completion.
```

You already have an active ride in progress. You can only have one ride at a time. Would you like to:

1. Wait for your current ride to finish, then book the next one
2. Cancel the current ride and book a new one instead

---

**User:** Oh right, I'll wait

OK, I'll book your gym ride once the current one completes. Let me check on your driver.

---

## Scenario B: Same Address

**User:** Take me from home to home

*(Agent calls search_rides)*

```
Error: SAME_ADDRESS: Pickup and dropoff resolve to the same location
```

Pickup and dropoff can't be the same place — both resolve to 2111 7th Ave, Seattle. Did you mean a different destination?

---

**User:** Take me from work to Salesforce Tower

*(Agent calls search_rides)*

```
Error: SAME_ADDRESS: Pickup and dropoff resolve to the same location
```

"Work" and "Salesforce Tower" are the same place in your saved locations. Where would you like to go from work?

---

## Scenario C: Booking After Completion

*(First ride completes)*

```
Status: You have arrived! Trip completed.
Final fare: $18.50
```

**User:** Now book that gym ride

*(Agent searches from work to gym, quotes, books successfully)*

```
Ride booked!
Ride ID: ride_def456
Status: processing
Product: Comfort
Price: $12.30
Pickup: Salesforce Tower, San Francisco
```

Your gym ride is booked — $12.30 for Comfort from work to Equinox.

---

## Action Log

```
📋 Action Log (recent):

  ✅ book_ride (chain: a1b2c3)
    📝 Requested: Book ride to work
    🔍 Verified: $18.50 Comfort
    ⚖️ Decided: 🔓 approved
    🚀 Executed: POST /rides
    🏁 Outcome: Success (ride: ride_abc123)

  ❌ book_ride (chain: d4e5f6)
    📝 Requested: Book ride to gym
    🚀 Executed: POST /rides
    🏁 Outcome: Failed — DUPLICATE_RIDE

  ❌ search_rides: home to home → FAILED (SAME_ADDRESS)

  ❌ search_rides: work to Salesforce Tower → FAILED (SAME_ADDRESS)

  ✅ book_ride (chain: g7h8i9)
    📝 Requested: Book ride to gym (after first ride completed)
    🔍 Verified: $12.30 Comfort
    ⚖️ Decided: 🔓 approved
    🚀 Executed: POST /rides
    🏁 Outcome: Success (ride: ride_def456)
```

## Key Behaviors Demonstrated

1. **Duplicate prevention** — API rejects second booking while first is active
2. **Agent offers options** — wait or cancel, doesn't dead-end
3. **Same address rejection** — both direct and alias-resolved duplicates caught
4. **Sequential booking works** — after first ride completes, second goes through
5. **Alias awareness** — agent knows "work" and "Salesforce Tower" are the same
