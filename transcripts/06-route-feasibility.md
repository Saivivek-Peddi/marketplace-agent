# Transcript 6: Route Feasibility

Tests US-only service area, ocean crossings, and OSRM route validation.

---

## Setup

```
Mode: Agent (start-agent.sh)
Scenario: normal
Profile: home=2111 7th Ave, Seattle, WA
```

---

## Conversation

### International destination (outside US bounding box)

**User:** Take me from home to Chennai Beach, India

**Agent:** *(calls search_rides)*

```
Error: OUTSIDE_SERVICE_AREA: Dropoff (Marina Beach, Zone 9 Teynampet,
Chennai Corporation) is outside the service area. Rides are only
available within the contiguous United States.
```

I'm sorry, but this ride service only operates within the contiguous United States. Chennai, India is outside our service area. You'd need to look into flights for that trip — maybe check SFO or SEA for direct routes to Chennai.

Where would you like to go within the US?

---

### Hawaii (US but outside contiguous bounds)

**User:** How about Honolulu, Hawaii?

**Agent:** *(calls search_rides)*

```
Error: OUTSIDE_SERVICE_AREA: Dropoff (Honolulu, Hawaii) is outside
the service area. Rides are only available within the contiguous
United States.
```

Hawaii is part of the US, but our ride service only covers the contiguous 48 states — you can't drive to Hawaii. You'd need a flight from Seattle to Honolulu. Want me to find you a ride to SEA airport instead?

---

### Cross-country (valid, long distance)

**User:** What about New York City?

**Agent:** *(calls search_rides)*

```
Estimate ID: est_a1b2c3
Pickup: 2111 7th Ave, Seattle, WA
Dropoff: Times Square, New York, NY

- UberX: $4,200-$5,700, ETA 5min, trip ~2900mi ~46hrs
- Comfort: $5,600-$7,600, ETA 7min, trip ~2900mi ~46hrs
- UberXL: $6,200-$8,400, ETA 9min, trip ~2900mi ~46hrs
- Black: $9,600-$13,000, ETA 11min, trip ~2900mi ~46hrs
```

I found options — but fair warning, that's about 2,900 miles and 46 hours of driving. The cheapest option starts around $4,200. A flight would be much more practical and cheaper. Still want a quote?

---

### Cross-border (US to Canada)

**User:** Take me to Vancouver, BC

**Agent:** *(calls search_rides)*

```
Error: OUTSIDE_SERVICE_AREA: Dropoff (Vancouver, British Columbia,
Canada) is outside the service area. Rides are only available within
the contiguous United States.
```

Vancouver is just across the border but outside our service area — we only operate within the US. You could take a ride to the Blaine, WA border crossing and arrange transport on the Canadian side. Want me to search for that?

---

## Key Behaviors Demonstrated

1. **International rejection** — Chennai blocked by US bounding box
2. **Non-contiguous US rejection** — Hawaii blocked (no road, outside bounds)
3. **Cross-country allowed** — NYC is far but driveable, agent warns about practicality
4. **Cross-border rejection** — Canada blocked by bounding box
5. **Helpful alternatives** — agent suggests flights or nearby alternatives
6. **OSRM provides real distances** — 2,900 miles for Seattle-NYC (not haversine guess)
