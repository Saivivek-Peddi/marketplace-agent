"""Tool handlers — one function per tool, returning structured results."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from mcp_server.adapter import (
    AdapterError,
    ConnectionError as AdapterConnectionError,
    RideAdapter,
)
from mcp_server.profile import UserProfile

from .validation import validate_address, validate_id, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Structured tool result with display string and machine-readable data."""
    display: str
    data: dict = field(default_factory=dict)


def _search_rides(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    pickup = validate_address(profile.resolve_address(params["pickup"]), "pickup")
    dropoff = validate_address(profile.resolve_address(params["dropoff"]), "dropoff")
    r = adapter.search(pickup, dropoff)
    lines = [
        f"Estimate ID: {r.estimate_id}",
        f"Pickup: {r.pickup.address}",
        f"Dropoff: {r.dropoff.address}",
        "",
    ]
    for o in r.options:
        surge = ""
        if o.surge.is_surging:
            surge = f" (surge {o.surge.multiplier}x)"
        lines.append(
            f"- {o.name} ({o.car_type_id}): "
            f"${o.price_range.min:.2f}-"
            f"${o.price_range.max:.2f}{surge}, "
            f"ETA {o.pickup_eta_minutes}min, "
            f"trip ~{o.trip_duration_minutes}min"
        )
    return ToolResult(
        display="\n".join(lines),
        data={
            "estimate_id": r.estimate_id,
            "pickup": r.pickup.address,
            "dropoff": r.dropoff.address,
            "options": [o.car_type_id for o in r.options],
        },
    )


def _get_quote(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    estimate_id = validate_id(params["estimate_id"], "estimate_id")
    car_type_id = validate_id(params["car_type_id"], "car_type_id")
    r = adapter.quote(estimate_id, car_type_id)
    surge = ""
    if r.surge.is_surging:
        surge = f" (surge {r.surge.multiplier}x)"
    display = (
        f"Quote ID: {r.quote_id}\n"
        f"Product: {r.car_type_name}\n"
        f"Price: ${r.price:.2f}{surge}\n"
        f"Pickup ETA: {r.pickup_eta_minutes}min\n"
        f"Trip: {r.trip_distance_miles}mi, "
        f"~{r.trip_duration_minutes}min\n"
        f"Expires: {r.expires_at}"
    )
    return ToolResult(
        display=display,
        data={
            "quote_id": r.quote_id,
            "estimate_id": estimate_id,
            "car_type_id": car_type_id,
            "price": r.price,
            "car_type_name": r.car_type_name,
        },
    )


def _book_ride(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    quote_id = validate_id(params["quote_id"], "quote_id")
    r = adapter.book(quote_id)
    display = (
        f"Ride booked!\n"
        f"Ride ID: {r.ride_id}\n"
        f"Status: {r.status}\n"
        f"Product: {r.car_type_name}\n"
        f"Price: ${r.price:.2f}\n"
        f"Pickup: {r.pickup_address}"
    )
    # Save to ride history immediately at booking (don't wait for completion)
    existing = {rd.get("ride_id") for rd in profile.recent_rides(20)}
    if r.ride_id not in existing:
        profile.add_recent_ride({
            "from": r.pickup_address,
            "to": r.dropoff_address if hasattr(r, "dropoff_address") else "—",
            "car_type": r.car_type_name,
            "price": r.price,
            "ride_id": r.ride_id,
            "status": r.status,
        })
    return ToolResult(
        display=display,
        data={
            "ride_id": r.ride_id,
            "status": r.status,
            "price": r.price,
            "car_type_name": r.car_type_name,
            "pickup": r.pickup_address,
        },
    )


def _check_status(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    ride_id = validate_id(params["ride_id"], "ride_id")
    r = adapter.status(ride_id)
    lines = [
        f"Status: {r.status_description}",
        f"Product: {r.car_type_name}",
        f"Price: ${r.price:.2f}",
    ]
    data: dict[str, Any] = {
        "ride_id": r.ride_id,
        "status": r.status,
        "price": r.price,
    }
    if r.driver:
        d = r.driver
        lines.append(
            f"Driver: {d.name} ({d.rating}) - "
            f"{d.vehicle.color} {d.vehicle.make} "
            f"{d.vehicle.model} ({d.vehicle.license_plate})"
        )
        data["driver_name"] = d.name
    if r.trip.fare_so_far is not None:
        lines.append(f"Fare so far: ${r.trip.fare_so_far:.2f}")
        data["fare_so_far"] = r.trip.fare_so_far
    if r.trip.eta_remaining_minutes is not None:
        lines.append(f"ETA remaining: {r.trip.eta_remaining_minutes:.0f}min")
    if r.trip.final_fare is not None:
        lines.append(f"Final fare: ${r.trip.final_fare:.2f}")
        data["final_fare"] = r.trip.final_fare
        # Update existing ride entry with final fare and completed status
        for rd in profile.recent_rides(20):
            if rd.get("ride_id") == r.ride_id:
                rd["price"] = r.trip.final_fare
                rd["status"] = "completed"
                profile._save()
                break
    return ToolResult(display="\n".join(lines), data=data)


def _cancel_ride(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    ride_id = validate_id(params["ride_id"], "ride_id")
    fee = adapter.cancel_fee(ride_id)
    if not fee.cancellable:
        return ToolResult(
            display=f"Cannot cancel: {fee.reason}",
            data={"error": "not_cancellable", "reason": fee.reason},
        )
    r = adapter.cancel(ride_id)
    return ToolResult(
        display=(
            f"Ride canceled.\n"
            f"Fee: ${r.fee.amount:.2f}\n"
            f"Refund: ${r.refund:.2f}"
        ),
        data={
            "ride_id": ride_id,
            "canceled": True,
            "fee": r.fee.amount,
            "refund": r.refund,
        },
    )


def _save_place(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    name = params["name"].strip()
    address = validate_address(params["address"], "address")
    profile.save_place(name, address)
    places = profile.list_places()
    lines = [f"Saved '{name}' = {address}", ""]
    for k, v in places.items():
        lines.append(f"  {k}: {v}")
    return ToolResult(
        display="\n".join(lines),
        data={"saved_place": name, "address": address},
    )


def _save_preference(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    value = params["value"]
    parsed: str | bool = value
    if value.lower() in ("true", "yes"):
        parsed = True
    elif value.lower() in ("false", "no"):
        parsed = False
    profile.save_preference(params["key"], parsed)
    return ToolResult(
        display=f"Preference saved: {params['key']} = {parsed}",
        data={"preference_key": params["key"], "preference_value": parsed},
    )


def _get_profile(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    places = profile.list_places()
    prefs = profile.list_preferences()
    rides = profile.recent_rides(5)
    lines = ["User Profile", ""]
    lines.append("Saved Places:")
    if places:
        for k, v in places.items():
            lines.append(f"  {k}: {v}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("Preferences:")
    for k, v in prefs.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append(f"Recent Rides: {len(rides)}")
    for r in rides:
        lines.append(
            f"  {r.get('from', '?')} -> "
            f"{r.get('to', '?')} "
            f"({r.get('car_type', '?')}, "
            f"${r.get('price', '?')})"
        )
    return ToolResult(display="\n".join(lines), data={"places": places, "preferences": prefs})


def _check_surge(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    pickup = validate_address(profile.resolve_address(params["pickup"]), "pickup")
    dropoff = validate_address(profile.resolve_address(params["dropoff"]), "dropoff")
    r = adapter.search(pickup, dropoff)
    cheapest = min(r.options, key=lambda o: o.price_range.min)
    mult = cheapest.surge.multiplier
    if not cheapest.surge.is_surging:
        lines = ["No surge -- prices are normal!"]
        for o in r.options:
            lines.append(
                f"  {o.name}: ${o.price_range.min:.2f}-${o.price_range.max:.2f}"
            )
        lines.append(f"Estimate ID: {r.estimate_id}")
        return ToolResult(
            display="\n".join(lines),
            data={"surging": False, "estimate_id": r.estimate_id, "multiplier": 1.0},
        )
    normal = cheapest.price_range.min / mult
    saving = cheapest.price_range.min - normal
    return ToolResult(
        display=(
            f"SURGE ACTIVE: {mult}x\n"
            f"Cheapest ({cheapest.name}): ${cheapest.price_range.min:.2f} "
            f"(normally ~${normal:.2f})\n"
            f"You'd save ~${saving:.2f} if surge drops to 1x\n"
            "Surge usually drops in 10-15 min."
        ),
        data={"surging": True, "multiplier": mult, "estimate_id": r.estimate_id},
    )


def _get_suggestions(
    params: dict, adapter: RideAdapter, profile: UserProfile,
) -> ToolResult:
    rides = profile.recent_rides(20)
    if not rides:
        return ToolResult(display="No ride history yet.", data={})
    route_counts = Counter(
        (r.get("from", "?"), r.get("to", "?")) for r in rides
    )
    car_counts = Counter(r.get("car_type", "?") for r in rides)
    prices = [r["price"] for r in rides if isinstance(r.get("price"), (int, float))]
    lines = ["Smart Suggestions", ""]
    for (fr, to), count in route_counts.most_common(3):
        lines.append(f"  {fr} -> {to} ({count}x)")
    fav = car_counts.most_common(1)[0][0]
    lines.append(f"Preferred car type: {fav}")
    if prices:
        avg = sum(prices) / len(prices)
        lines.append(f"Avg price: ${avg:.2f}")
    return ToolResult(
        display="\n".join(lines),
        data={"favorite_car_type": fav, "avg_price": sum(prices)/len(prices) if prices else 0},
    )


# Dispatch table
DISPATCH = {
    "search_rides": _search_rides,
    "get_quote": _get_quote,
    "book_ride": _book_ride,
    "check_status": _check_status,
    "cancel_ride": _cancel_ride,
    "save_place": _save_place,
    "save_preference": _save_preference,
    "get_profile": _get_profile,
    "check_surge": _check_surge,
    "get_suggestions": _get_suggestions,
}


def execute(
    name: str,
    params: dict,
    adapter: RideAdapter,
    profile: UserProfile,
) -> ToolResult:
    """Execute a tool by name. Returns structured ToolResult."""
    handler = DISPATCH.get(name)
    if not handler:
        return ToolResult(display=f"Unknown tool: {name}", data={"error": "unknown_tool"})
    try:
        return handler(params, adapter, profile)
    except ValidationError as e:
        return ToolResult(display=f"Validation error: {e}", data={"error": "validation", "message": str(e)})
    except AdapterConnectionError as e:
        return ToolResult(
            display=f"Error: Could not connect to ride service. ({e})",
            data={"error": "connection", "message": str(e)},
        )
    except AdapterError as e:
        # Provide recovery hints for expired resources
        hint = ""
        if e.code == "QUOTE_EXPIRED":
            hint = " Try getting a new quote with the same estimate_id and car_type_id."
        elif e.code == "ESTIMATE_EXPIRED":
            hint = " Try searching for rides again with the same pickup and dropoff."
        return ToolResult(
            display=f"Error: {e.code}: {e.message}{hint}",
            data={"error": e.code, "message": e.message},
        )
