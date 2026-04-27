"""Append-only action log with full lifecycle tracking.

Every action goes through phases:
  requested  → agent wants to do something (with reasoning)
  verified   → pre-execution check (fee preview, price lock, etc.)
  decided    → user approved or denied (gate outcome)
  executed   → API call was made
  outcome    → final result (success/failure, response data)

Gated actions (book, cancel) produce multiple linked entries sharing
a correlation_id so you can trace the full chain. Non-gated actions
(search, quote, status) produce a single entry with all phases collapsed.

Three audiences: agent (memory), user (trust), ops (debugging).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ActionLog:
    def __init__(self, log_path: str = "action_log.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.touch(exist_ok=True)
        self._pending_correlations: dict[str, str] = {}

    def _write(self, entry: dict) -> None:
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    #  New lifecycle API

    def record_request(
        self,
        tool: str,
        intent: str,
        params: dict,
        reasoning: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """Phase 1: Agent requested an action."""
        cid = correlation_id or self._new_id()
        self._write({
            "id": self._new_id(),
            "correlation_id": cid,
            "timestamp": self._now(),
            "phase": "requested",
            "tool": tool,
            "intent": intent,
            "reasoning": reasoning,
            "params": params,
        })
        return cid

    def record_verification(
        self,
        correlation_id: str,
        tool: str,
        verification_data: dict,
        message: str | None = None,
    ) -> None:
        """Phase 2: Pre-execution check (fee preview, quote details)."""
        self._write({
            "id": self._new_id(),
            "correlation_id": correlation_id,
            "timestamp": self._now(),
            "phase": "verified",
            "tool": tool,
            "verification": verification_data,
            "message": message,
        })

    def record_decision(
        self,
        correlation_id: str,
        tool: str,
        decision: str,
        message: str | None = None,
    ) -> None:
        """Phase 3: Gate decision — approved, denied, or not_required."""
        self._write({
            "id": self._new_id(),
            "correlation_id": correlation_id,
            "timestamp": self._now(),
            "phase": "decided",
            "tool": tool,
            "decision": decision,
            "message": message,
        })

    def record_execution(
        self,
        correlation_id: str,
        tool: str,
        api_call: dict,
    ) -> None:
        """Phase 4: What API call was actually made."""
        self._write({
            "id": self._new_id(),
            "correlation_id": correlation_id,
            "timestamp": self._now(),
            "phase": "executed",
            "tool": tool,
            "api_call": api_call,
        })

    def record_outcome(
        self,
        correlation_id: str,
        tool: str,
        success: bool,
        result: dict | str | None = None,
        error: str | None = None,
    ) -> None:
        """Phase 5: Final outcome — what actually happened."""
        self._write({
            "id": self._new_id(),
            "correlation_id": correlation_id,
            "timestamp": self._now(),
            "phase": "outcome",
            "tool": tool,
            "success": success,
            "result": result,
            "error": error,
        })

    #  Convenience: single-call for non-gated tools

    def record(
        self,
        tool: str,
        intent: str,
        params: dict,
        gate_required: bool = False,
        gate_decision: str | None = None,
        gate_message: str | None = None,
        success: bool | None = None,
        result: dict | str | None = None,
        error: str | None = None,
        reasoning: str | None = None,
    ) -> str:
        """Backwards-compatible single-entry record.

        For non-gated tools, this collapses all phases into one entry.
        Still works everywhere the old API was used.
        """
        entry_id = self._new_id()
        entry = {
            "id": entry_id,
            "correlation_id": entry_id,
            "timestamp": self._now(),
            "phase": "complete",
            "tool": tool,
            "intent": intent,
            "reasoning": reasoning,
            "params": params,
            "gate": {
                "required": gate_required,
                "decision": gate_decision,
                "message": gate_message,
            },
            "result": {
                "success": success,
                "data": result,
            },
            "error": error,
        }
        self._write(entry)
        return entry_id

    #  Correlation tracking for gated tools

    def start_gated_action(self, tool: str, key: str) -> str:
        """Begin tracking a gated action. Returns correlation_id.

        key: a unique key for this action (e.g. quote_id or ride_id)
             so the second call (confirmed=True) can find the correlation_id.
        """
        cid = self._new_id()
        self._pending_correlations[f"{tool}:{key}"] = cid
        return cid

    def get_correlation_id(self, tool: str, key: str) -> str | None:
        """Retrieve correlation_id for a pending gated action."""
        return self._pending_correlations.get(f"{tool}:{key}")

    def end_gated_action(self, tool: str, key: str) -> None:
        """Clean up after a gated action completes."""
        self._pending_correlations.pop(f"{tool}:{key}", None)

    # Read API (unchanged)

    def read_all(self) -> list[dict]:
        entries = []
        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def read_recent(self, n: int = 10) -> list[dict]:
        all_entries = self.read_all()
        return all_entries[-n:]

    def read_action_chain(self, correlation_id: str) -> list[dict]:
        """Read all phases of a single action by correlation_id."""
        return [e for e in self.read_all() if e.get("correlation_id") == correlation_id]

    def summary(self) -> str:
        entries = self.read_all()
        if not entries:
            return "No actions recorded yet."
        lines = []
        for e in entries:
            phase = e.get("phase", "?")
            if phase == "complete":
                status = "OK" if e["result"]["success"] else "FAILED"
                if e["error"]:
                    status = f"ERROR: {e['error']}"
                gate = ""
                if e["gate"]["required"]:
                    gate = f" [gate: {e['gate']['decision']}]"
                lines.append(
                    f"[{e['timestamp']}] {e['tool']}: "
                    f"{e['intent']} → {status}{gate}"
                )
            else:
                lines.append(
                    f"[{e['timestamp']}] {e['tool']}: "
                    f"[{phase}] {e.get('intent', e.get('message', e.get('decision', '')))} "
                    f"(chain: {e['correlation_id']})"
                )
        return "\n".join(lines)
