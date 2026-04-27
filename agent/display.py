"""Output display with guardrail filtering (always active)."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def safe_print(text: str) -> None:
    """Print agent text, filtered by output guardrail."""
    from mcp_server.guardrails import check_output

    is_safe, reason = check_output(text)
    if not is_safe:
        if os.environ.get("AGENT_DEBUG"):
            logger.debug(f"Output blocked: {reason}")
        print(
            "Agent: I'm a ride booking assistant. "
            "Where would you like to go?"
        )
        return
    print(f"Agent: {text}")
