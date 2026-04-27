"""Input and output guardrails for the ride-booking agent.

InputGuard:  Blocks prompt injection and off-topic requests BEFORE
             the message reaches the model. Runs on raw user text.

OutputGuard: Catches leaked internals in agent responses BEFORE
             the user sees them. Runs on model output text.

Both return (is_safe: bool, reason: str). The harness decides
what to do — block, redact, or warn.
"""

from __future__ import annotations

import re


#  Input Guard 


# Patterns that indicate prompt injection or extraction attempts
_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"system\s*prompt", re.I),
     "prompt extraction attempt"),
    (re.compile(r"your\s*(instructions|rules|guidelines|directives)", re.I),
     "instruction extraction attempt"),
    (re.compile(
        r"ignore\s*(previous|all|prior|above)\s*(instructions|rules|prompts)",
        re.I),
     "instruction override attempt"),
    (re.compile(r"(admin|developer|debug|diagnostic)\s*(override|mode|access)", re.I),
     "privilege escalation attempt"),
    (re.compile(r"print\s*(the|your)\s*(system|prompt|instructions|config)", re.I),
     "prompt extraction attempt"),
    (re.compile(r"</?\s*system\s*>", re.I),
     "XML injection attempt"),
    (re.compile(r"repeat\s*(everything|all|the text)\s*(above|before|from the start)", re.I),
     "prompt extraction attempt"),
    (re.compile(
        r"(reveal|show|display|dump|output)\s*(your|the|all)?\s*"
        r"(prompt|instructions|system|config|source|code)", re.I),
     "prompt extraction attempt"),
    (re.compile(r"what\s*(are|is)\s*your\s*(system|full|complete)?\s*(prompt|instructions|rules)", re.I),
     "prompt extraction attempt"),
    (re.compile(r"summarize\s*your\s*(system\s*)?prompt", re.I),
     "prompt extraction attempt"),
    (re.compile(r"(act|pretend|behave)\s*(as|like)\s*(a|an)?\s*(different|new)", re.I),
     "role hijack attempt"),
    (re.compile(r"you\s*are\s*now\s*(a|an|no longer)", re.I),
     "role hijack attempt"),
    (re.compile(r"from\s*now\s*on\s*(you|ignore|forget|disregard)", re.I),
     "instruction override attempt"),
    (re.compile(r"forget\s*(everything|all|your)\s*(you|instructions|rules|about)", re.I),
     "instruction override attempt"),
    (re.compile(r"\bDAN\b|\bDo Anything Now\b", re.I),
     "jailbreak attempt"),
]


def check_input(text: str) -> tuple[bool, str]:
    """Check user input for prompt injection or off-topic content.

    Returns (is_safe, reason). If is_safe is False, the message
    should be blocked before it reaches the model.
    """
    for pattern, reason in _INJECTION_PATTERNS:
        if pattern.search(text):
            return False, reason

    return True, ""


#  Output Guard 


# Patterns that indicate the model is leaking internals
_LEAK_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Tool/API internals
    (re.compile(
        r"\b(search_rides|get_quote|book_ride|cancel_ride|check_status"
        r"|check_surge|get_profile|get_suggestions|save_place"
        r"|save_preference|set_scenario|view_action_log)\b"),
     "tool name leaked"),
    (re.compile(r"\b(estimate_id|quote_id|car_type_id|ride_id)\s*[:=]", re.I),
     "internal parameter leaked"),
    (re.compile(r"\best_[a-f0-9]{8}\b"),
     "estimate ID leaked"),
    (re.compile(r"\bqt_[a-f0-9]{8}\b"),
     "quote ID leaked"),

    # File/code internals
    (re.compile(r"(mcp_server|server\.py|adapter\.py|harness\.py|simulation\.py|models\.py)", re.I),
     "file path leaked"),
    (re.compile(r"\b(FastMCP|RideAdapter|UberAdapter|ActionLog|UserProfile)\b"),
     "class name leaked"),
    (re.compile(r"\b(httpx|uvicorn|fastapi|pydantic)\b", re.I),
     "dependency name leaked"),
    (re.compile(r"(localhost:\d+|/v1/estimates|/v1/quotes|/v1/rides)"),
     "API endpoint leaked"),

    # System prompt content
    (re.compile(r"CONFIDENTIALITY:", re.I),
     "system prompt section leaked"),
    (re.compile(r"ROUTE FEASIBILITY:", re.I),
     "system prompt section leaked"),
    (re.compile(r"reasoning.*parameter.*audit", re.I),
     "system prompt content leaked"),

    # Architecture details
    (re.compile(r"\b(MCP|Model Context Protocol)\b"),
     "architecture detail leaked"),
    (re.compile(r"\b(OSRM|Nominatim|geopy|geocod)", re.I),
     "infrastructure detail leaked"),
    (re.compile(r"docker[\s-]?compose|Dockerfile", re.I),
     "infrastructure detail leaked"),
]

# Ride IDs are OK to show to users (they need them to track/cancel)
_RIDE_ID_OK = re.compile(r"\bride_[a-f0-9]{8}\b")


def check_output(text: str) -> tuple[bool, str]:
    """Check agent output for leaked internals.

    Returns (is_safe, reason). If is_safe is False, the response
    should be blocked or redacted before the user sees it.
    """
    for pattern, reason in _LEAK_PATTERNS:
        match = pattern.search(text)
        if match:
            # ride_id is allowed — users need it
            if reason == "internal parameter leaked" and "ride_id" in match.group():
                continue
            return False, reason

    return True, ""


def redact_output(text: str) -> str:
    """Remove leaked internals from agent output.

    Fallback if you want to show a partially cleaned response
    instead of blocking entirely.
    """
    result = text
    for pattern, _ in _LEAK_PATTERNS:
        result = pattern.sub("[redacted]", result)
    return result
