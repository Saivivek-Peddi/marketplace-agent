"""Confirmation gates — enforced in code, not model instructions."""

from __future__ import annotations

from mcp_server.action_log import ActionLog
from mcp_server.adapter import RideAdapter


def confirmation_gate(
    tool_name: str,
    params: dict,
    adapter: RideAdapter,
    log: ActionLog,
) -> bool:
    """Ask user for confirmation. Returns True if approved."""
    print("\n" + "=" * 50)
    print(f"  CONFIRMATION REQUIRED: {tool_name}")
    print("=" * 50)

    if tool_name == "book_ride":
        print("  The agent wants to BOOK this ride.")
    elif tool_name == "cancel_ride":
        try:
            fee = adapter.cancel_fee(params["ride_id"])
            print(f"  Cancel fee: ${fee.fee.amount:.2f}")
            print(f"  Reason: {fee.reason}")
        except Exception:
            print("  (Could not fetch cancel fee preview)")

    print()
    answer = input("  Approve? (yes/no): ").strip().lower()
    approved = answer in ("yes", "y")

    log.record(
        tool=tool_name,
        intent=f"Confirmation gate for {tool_name}",
        params=params,
        gate_required=True,
        gate_decision="approved" if approved else "denied",
        gate_message=f"User said: {answer}",
        success=approved,
    )

    if approved:
        print("  -> Approved.")
    else:
        print("  -> Denied.")
    print("=" * 50 + "\n")

    return approved
