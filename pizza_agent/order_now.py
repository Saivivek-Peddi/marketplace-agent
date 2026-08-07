"""One-shot autonomous pizza mission.

Finds the nearest open Domino's to the venue, builds a pepperoni jalapeño
pizza order, prices it, and places it (cash at the door by default).

Usage (stdlib only — no pip install needed):

    python3 -m pizza_agent.order_now --name "Sai Vivek Peddi" --phone 4155551234

Add --yes to place the order without the final confirmation prompt.
Credit card instead of cash: set PIZZA_CARD_NUMBER, PIZZA_CARD_EXP (MMYY),
PIZZA_CARD_CVV, PIZZA_CARD_ZIP in the environment.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import dominos

VENUE_STREET = "3 Embarcadero Center"
VENUE_CITY = "San Francisco"
VENUE_REGION = "CA"
VENUE_ZIP = "94105"
DELIVERY_NOTE = (
    "Codi event space - AlphaSignal Pizza Agent Challenge. "
    "Look for the PIZZA CHALLENGE signs. Please call on arrival."
)


def log(msg: str) -> None:
    print(f"\033[1;33m🍕\033[0m {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Order a pepperoni jalapeño pizza to the venue")
    ap.add_argument("--name", required=True, help="Full name for the order")
    ap.add_argument("--phone", required=True, help="Phone number the driver can call")
    ap.add_argument("--email", default=os.environ.get("PIZZA_EMAIL", "peddisaivivek999@gmail.com"))
    ap.add_argument("--size", default="large", choices=sorted(dominos.SIZES))
    ap.add_argument("--qty", type=int, default=1)
    ap.add_argument("--street", default=VENUE_STREET)
    ap.add_argument("--city", default=VENUE_CITY)
    ap.add_argument("--region", default=VENUE_REGION)
    ap.add_argument("--zip", dest="postal", default=VENUE_ZIP)
    ap.add_argument("--yes", action="store_true", help="Place the order without confirming")
    ap.add_argument("--dry-run", action="store_true", help="Price only, never place")
    args = ap.parse_args()

    first, _, last = args.name.partition(" ")
    last = last or "Agent"
    size_code = dominos.SIZES[args.size]

    # Some stores near the boundary reject the address (ServiceMethodNotAllowed),
    # so try every nearby store, and both plausible zips for Embarcadero Center.
    zips = [args.postal] + [z for z in ("94111", "94105") if z != args.postal]
    order = priced = store = None
    total = None
    for postal in zips:
        log(f"Locating stores that deliver to {args.street}, {args.city} {postal}...")
        stores = dominos.find_stores(args.street, f"{args.city}, {args.region} {postal}")
        for candidate in stores[:6]:
            sid = candidate["StoreID"]
            log(f"Trying store #{sid} — {candidate.get('AddressDescription', '?').splitlines()[0]} "
                f"({candidate.get('MinDistance', '?')} mi)")
            attempt = dominos.build_order(
                store_id=sid,
                street=args.street,
                city=args.city,
                region=args.region,
                postal_code=postal,
                first_name=first,
                last_name=last,
                phone=args.phone,
                email=args.email,
                size_code=size_code,
                quantity=args.qty,
                delivery_instructions=DELIVERY_NOTE,
            )
            result = dominos.price_order(attempt)
            errs = dominos.errors_in(result)
            if errs:
                log(f"  store #{sid} rejected: {errs}")
                continue
            order, priced, store = attempt, result, candidate
            total = dominos.order_total(priced)
            break
        if order:
            break
    if not order:
        log("Every nearby store rejected the order — dumping last response:")
        return 1
    log(f"✅ Store #{store['StoreID']} accepted. Total (incl. tax & delivery): ${total}")

    # Carry forward server-side adjustments (order ID, amounts) into the order we place.
    for key in ("OrderID", "Amounts", "EstimatedWaitMinutes", "BusinessDate", "PriceOrderTime"):
        if key in priced.get("Order", {}):
            order["Order"][key] = priced["Order"][key]

    card = os.environ.get("PIZZA_CARD_NUMBER", "")
    dominos.attach_payment(
        order,
        amount=total or 0.0,
        card_number=card,
        card_expiration=os.environ.get("PIZZA_CARD_EXP", ""),
        card_cvv=os.environ.get("PIZZA_CARD_CVV", ""),
        card_zip=os.environ.get("PIZZA_CARD_ZIP", ""),
    )
    pay_desc = "credit card" if card else "CASH AT THE DOOR"
    log(f"Payment method: {pay_desc}")

    if args.dry_run:
        log("Dry run — stopping before placing the order.")
        return 0

    if not args.yes:
        answer = input(f"Place the order for ${total} ({pay_desc})? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            log("Aborted — nothing ordered.")
            return 1

    log("Placing order...")
    placed = dominos.place_order(order)
    errs = dominos.errors_in(placed)
    if errs:
        log(f"Order FAILED: {errs}")
        print(placed)
        return 1

    o = placed.get("Order", {})
    log("✅ ORDER PLACED!")
    log(f"   Order ID:  {o.get('OrderID', '?')}")
    log(f"   Store:     #{store_id} {store.get('AddressDescription', '').strip()}")
    log(f"   Total:     ${o.get('Amounts', {}).get('Customer', total)} ({pay_desc})")
    log(f"   Est. wait: {o.get('EstimatedWaitMinutes', '?')} minutes")
    log("   Track it:  https://www.dominos.com/en/pages/tracker/")
    log("Go win that $2,500. 🏆")
    return 0


if __name__ == "__main__":
    sys.exit(main())
