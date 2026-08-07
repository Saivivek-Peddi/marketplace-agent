"""CC-style chat loop: Claude drives the Domino's tools to order the pizza.

    export ANTHROPIC_API_KEY=sk-ant-...
    python3 -m pizza_agent.chat

Requires: pip install anthropic  (or: uv sync --extra harness)
"""

from __future__ import annotations

import json
import os
import sys

from . import dominos
from .order_now import DELIVERY_NOTE, VENUE_CITY, VENUE_REGION, VENUE_STREET, VENUE_ZIP

MODEL = os.environ.get("PIZZA_AGENT_MODEL", "claude-sonnet-5")

SYSTEM = f"""You are Pizza Agent, competing live in AlphaSignal's Pizza Agent Challenge.
Mission: autonomously order a pepperoni jalapeño pizza delivered to the venue:
{VENUE_STREET}, {VENUE_CITY}, {VENUE_REGION} {VENUE_ZIP}.
Use your tools: find the nearest open Domino's, price a large pepperoni + jalapeño
pizza, then place it with cash-at-door payment. Before calling place_order you MUST
have the user's name and phone number (the driver needs it) and their explicit
go-ahead on the total price. Be fast, confident, and fun — a crowd is watching."""

TOOLS = [
    {
        "name": "find_stores",
        "description": "Find open Domino's stores that deliver to the venue address. Returns nearest first.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "price_pizza",
        "description": "Build and price the pepperoni jalapeño pizza order at a store. Returns the total.",
        "input_schema": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "size": {"type": "string", "enum": sorted(dominos.SIZES), "default": "large"},
                "name": {"type": "string", "description": "Customer full name"},
                "phone": {"type": "string", "description": "Customer phone number"},
                "email": {"type": "string"},
            },
            "required": ["store_id", "name", "phone"],
        },
    },
    {
        "name": "place_order",
        "description": "Place the most recently priced order for real, cash at the door. Irreversible!",
        "input_schema": {"type": "object", "properties": {}},
    },
]

_state: dict = {"order": None, "total": None}


def run_tool(name: str, inp: dict) -> str:
    if name == "find_stores":
        stores = dominos.find_stores(VENUE_STREET, f"{VENUE_CITY}, {VENUE_REGION} {VENUE_ZIP}")
        return json.dumps([
            {
                "store_id": s["StoreID"],
                "address": s.get("AddressDescription", "").strip(),
                "miles": s.get("MinDistance"),
                "open_for_delivery": bool(s.get("ServiceIsOpen", {}).get("Delivery")),
                "est_wait_min": s.get("ServiceMethodEstimatedWaitMinutes", {}).get("Delivery"),
            }
            for s in stores[:5]
        ])
    if name == "price_pizza":
        first, _, last = inp["name"].partition(" ")
        order = dominos.build_order(
            store_id=inp["store_id"],
            street=VENUE_STREET, city=VENUE_CITY, region=VENUE_REGION, postal_code=VENUE_ZIP,
            first_name=first, last_name=last or "Agent",
            phone=inp["phone"], email=inp.get("email", "pizza@agent.dev"),
            size_code=dominos.SIZES.get(inp.get("size", "large"), "14SCREEN"),
            delivery_instructions=DELIVERY_NOTE,
        )
        priced = dominos.price_order(order)
        errs = dominos.errors_in(priced)
        if errs:
            return json.dumps({"error": errs})
        for key in ("OrderID", "Amounts", "EstimatedWaitMinutes", "BusinessDate", "PriceOrderTime"):
            if key in priced.get("Order", {}):
                order["Order"][key] = priced["Order"][key]
        _state["order"], _state["total"] = order, dominos.order_total(priced)
        return json.dumps({"total_usd": _state["total"], "payment": "cash at the door"})
    if name == "place_order":
        if not _state["order"]:
            return json.dumps({"error": "price_pizza must succeed first"})
        dominos.attach_payment(_state["order"], amount=_state["total"] or 0.0)
        placed = dominos.place_order(_state["order"])
        errs = dominos.errors_in(placed)
        if errs:
            return json.dumps({"error": errs})
        o = placed.get("Order", {})
        return json.dumps({
            "status": "PLACED",
            "order_id": o.get("OrderID"),
            "total_usd": o.get("Amounts", {}).get("Customer", _state["total"]),
            "estimated_wait_minutes": o.get("EstimatedWaitMinutes"),
            "tracker": "https://www.dominos.com/en/pages/tracker/",
        })
    return json.dumps({"error": f"unknown tool {name}"})


def main() -> int:
    try:
        import anthropic
    except ImportError:
        print("pip install anthropic  (or run the no-dependency mode: python3 -m pizza_agent.order_now)")
        return 1
    client = anthropic.Anthropic()
    messages: list = []
    print("🍕 Pizza Agent — type your message ('order the pizza' works). Ctrl-C to quit.\n")
    while True:
        try:
            user = input("\033[1;36myou>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        messages.append({"role": "user", "content": user})
        while True:
            resp = client.messages.create(
                model=MODEL, max_tokens=1024, system=SYSTEM, tools=TOOLS, messages=messages
            )
            messages.append({"role": "assistant", "content": resp.content})
            for block in resp.content:
                if block.type == "text" and block.text.strip():
                    print(f"\033[1;33magent>\033[0m {block.text}")
            if resp.stop_reason != "tool_use":
                break
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    print(f"\033[2m  ⚙ {block.name}({json.dumps(block.input)})\033[0m")
                    try:
                        out = run_tool(block.name, block.input)
                    except Exception as e:  # surface API hiccups to the model
                        out = json.dumps({"error": str(e)})
                    print(f"\033[2m  → {out[:200]}\033[0m")
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    sys.exit(main())
