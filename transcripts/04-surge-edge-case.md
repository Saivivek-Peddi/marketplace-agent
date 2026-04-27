# Transcript 4: Surge Pricing & Edge Cases

Surge active, user waits, quote expires, no drivers scenario.

---

## Setup

```
Mode: Agent (start-agent.sh)
Scenario: surge (then switched to surge,quote-expire, then no-drivers)
Profile: home=2111 7th Ave Seattle WA, work=Salesforce Tower SF, default_product=uberx
```

---

## Conversation

**User:** Take me to work

**Agent:** *(calls `search_rides(pickup="home", dropoff="work", reasoning="User wants to go to work. Resolving alias.")`)*

```
📍 Pickup: 2111 7th Ave, Seattle, WA
📍 Dropoff: Salesforce Tower, 415 Mission St, San Francisco, CA
🆔 Estimate ID: est_s1s2s3

⚠️  SURGE PRICING ACTIVE (2.5x)
   Normal UberX: $12.00-$15.00
   Surged UberX: $30.00-$37.50
   💡 Prices usually drop in 10-15 min. Wait, or book now?

              │    UberX     │   Comfort    │   UberXL     │    Black
─────────────┼──────────────┼──────────────┼──────────────┼──────────────
💰 Price     │   $30-$38    │   $45-$55    │   $55-$68    │   $88-$105
⏱️  ETA      │    3 min     │    5 min     │    7 min     │    4 min
...
```

Heads up — **2.5x surge** is active right now. Your usual UberX ride would be around **$30-38** instead of the normal $12-15. That's more than double.

I'd recommend waiting 10-15 minutes for the surge to drop. Want me to monitor it and let you know when prices come down?

---

**User:** Yeah check the surge

**Agent:** *(calls `check_surge(pickup="home", dropoff="work", reasoning="Surge is 2.5x. User wants to wait and monitor. First surge check to establish baseline.")`)*

```
⚠️  SURGE ACTIVE: 2.5x

  Product      Normal     Surged      Extra
  ─────────── ────────── ────────── ──────────
  UberX       $  12.00   $  30.00   +$ 18.00
  Comfort     $  18.00   $  45.00   +$ 27.00
  UberXL      $  22.00   $  55.00   +$ 33.00
  Black       $  35.00   $  87.50   +$ 52.50

  💡 Surge usually drops in 10-15 min.
  Call check_surge again in a few minutes to see the trend.

  💰 You'd save ~$27.00 on Comfort if surge drops to 1x
  📊 Checks on this route: 1
```

First check logged. At 2.5x, you'd be paying an extra **$27 on Comfort**. I'll check again in a few minutes.

---

*(5 minutes later)*

**User:** Check again

**Agent:** *(calls `check_surge(pickup="home", dropoff="work", reasoning="Second surge check. Comparing to previous 2.5x reading to see trend.")`)*

```
⚠️  SURGE ACTIVE: 1.8x

  Product      Normal     Surged      Extra
  ─────────── ────────── ────────── ──────────
  UberX       $  12.00   $  21.60   +$  9.60
  Comfort     $  18.00   $  32.40   +$ 14.40
  UberXL      $  22.00   $  39.60   +$ 17.60
  Black       $  35.00   $  63.00   +$ 28.00

  📉 DROPPING: 2.5x → 1.8x (prices are coming down!)
  💡 Keep waiting — check again in a few minutes.

  💰 You'd save ~$14.40 on Comfort if surge drops to 1x
  📊 Checks on this route: 2
```

Good news — surge dropped from **2.5x to 1.8x**. Comfort would be ~$32 now instead of $45. Still above normal though. Want to wait a bit more or book now?

---

**User:** Let's wait a bit more

*(3 minutes later)*

**User:** One more check

**Agent:** *(calls `check_surge(pickup="home", dropoff="work", reasoning="Third surge check. Previous was 1.8x, looking for further drop.")`)*

```
✅ NO SURGE — prices are normal right now!

  UberX: $12-$15
  Comfort: $18-$22
  UberXL: $22-$27
  Black: $35-$42

  📉 Surge dropped from 1.8x → 1.0x since last check!
  💰 You're saving ~$14.40 by waiting!

  Estimate ID: est_s4s5s6
  Ready to get a quote and book!
```

Surge is gone! Prices are back to normal. By waiting ~8 minutes, you saved about **$27** on Comfort. Want me to lock in a quote now?

---

**User:** Yes, comfort please

**Agent:** *(calls `get_quote(estimate_id="est_s4s5s6", product_id="comfort", reasoning="Surge cleared. Locking in normal-price Comfort quote.")`)*

```
Quote locked in!
Quote ID: q_nosurge_01
Product: Comfort
Price: $19.80
Pickup ETA: 5 min
Trip: 4.2 mi, ~14 min
Expires: 2026-04-25T08:35:00Z
```

$19.80 for Comfort — right at your normal average. Want me to book?

---

**User:** Yes

**Agent:** *(calls `book_ride(quote_id="q_nosurge_01", confirmed=False, reasoning="User confirmed. Presenting gate.")`)*

```
CONFIRMATION REQUIRED
Quote ID: q_nosurge_01
```

**$19.80 for Comfort**, home to work. Confirm?

---

**User:** Go

**Agent:** *(calls `book_ride(quote_id="q_nosurge_01", confirmed=True, reasoning="User confirmed booking at normal price after waiting out surge.")`)*

```
✅ Ride booked!
🆔 Ride ID: r_postsurge_01
🚘 Comfort · 💰 $19.80
📍 2111 7th Ave, Seattle → Salesforce Tower
🔍 Looking for a driver now...
```

Booked! Saved you $27 by waiting out that surge.

---

## Edge Case: Quote Expiry

*(Different scenario — demonstrating what happens when a quote expires)*

**User:** *(sets scenario to quote-expire via set_scenario)* Get me a comfort quote from home to work

**Agent:** *(searches, gets quote with 5s TTL)*

```
Quote ID: q_expire_01
Price: $19.80
Expires: 2026-04-25T08:40:05Z   ← only 5 seconds!
```

*(User takes too long)*

**Agent:** *(calls `book_ride(quote_id="q_expire_01", confirmed=True, reasoning="User confirmed but quote may have expired.")`)*

```
Error: QUOTE_EXPIRED: Quote q_expire_01 has expired. Please get a new quote.
```

That quote expired — they only last a short time during busy periods. Let me get you a fresh one.

*(Agent automatically re-searches and re-quotes)*

---

## Edge Case: No Drivers

*(Scenario switched to no-drivers)*

**Agent:** *(calls `book_ride` after user confirms)*

```
Error: NO_DRIVERS: No drivers available in your area right now.
Please try again in a few minutes.
```

No drivers available right now — this sometimes happens during very busy times. I can:
1. Keep checking every minute or two
2. Try a different product (Black cars sometimes have more availability)
3. Wait and you tell me when to retry

What would you prefer?

---

## Action Log

```
📋 Action Log (recent):
  ✅ search_rides: Search rides from 'home' to 'work' → OK
        💭 User wants to go to work. Resolving alias.
  ✅ check_surge: Surge check home → work → OK
        💭 Surge is 2.5x. First check to establish baseline.
  ✅ check_surge: Surge check home → work → OK
        💭 Second check. Comparing to previous 2.5x.
  ✅ check_surge: Surge check home → work → OK
        💭 Third check. Previous was 1.8x, looking for further drop.
  ✅ get_quote: Get quote for comfort → OK
        💭 Surge cleared. Locking in normal-price Comfort quote.

  ✅ book_ride (chain: e5f6g7h8)
    📝 Requested: Book ride (quote q_nosurge_01) — User confirmed at normal price.
    🔍 Verified: Presenting quote to user for confirmation
    ⚖️ Decided: 🔓 approved
    🚀 Executed: POST /v1/rides
    🏁 Outcome: Success (ride: r_postsurge_01)
```

## Key Behaviors Demonstrated

1. **Surge detection** — immediately warns user, calculates exact overpay
2. **Trend tracking** — 2.5x → 1.8x → 1.0x with directional indicators
3. **Savings calculation** — user sees exactly how much they saved by waiting
4. **Quote expiry recovery** — graceful handling, automatic re-quote
5. **No drivers fallback** — offers alternatives instead of dead-ending
6. **Proactive advice** — agent recommends waiting, not just reporting numbers
