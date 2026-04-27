# What breaks in the prod after swapping uber to lyft

## What needs to be changed before switching to Lyft/others 

The adapter pattern swaps Uber for Lyft (or any ride-hailing platform) is a three-file change:

```
mcp_server/adapters/lyft.py    ← NEW: implement RideAdapter
agent/config.py                ← CHANGE: one line (adapter class)
agent/main.py                  ← CHANGE: one import
```

Everything else — tools, guardrails, gates, logging, state tracking, system prompt — stays identical. The agent doesn't know or care which platform it's talking to.

## Rate limiting

The adapter makes raw httpx calls with no throttling. The agent's surge advisor calls adapter.search() repeatedly, but in reality both Uber, Lyft APIs will rate limit our agent, limiting our ability to search. 

- Fix : Add a rety + exponential backoff in adapter and not in the agent. Agent should be agnostic of these changes. 

## Quote model mismatch

Current flow is : search -> quote -> book. But Lyft might even give the price during the search step itself. There may not be a quote altogether. Adapter might need to fake the steps to keep the flow working. 

- Fix : The tool layer should be flexible enough to skip the steps we assumed. 

## Data model mismatch

We have assumed a certain datamodel for objects like StatusResult, that has attributes like pickup_eta_minutes, driver.vehicle.license_plate, but in reality the platform like uber may not provide all of these. We handle this by using None fields in the adapter, but the platforms might have more attributes that we are not considering in our datamodel. 

- Fix : We need to extend to dataclasses, which needs changing every adapter.
