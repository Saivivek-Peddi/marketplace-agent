"""Agent class — Plan-Execute-Verify architecture with memory system."""

from __future__ import annotations

import json
import logging
import sys

import anthropic
import httpx

from mcp_server.action_log import ActionLog
from mcp_server.adapters.uber import UberAdapter
from mcp_server.guardrails import check_input, check_output
from mcp_server.profile import UserProfile

from .config import (
    API_BASE,
    GATED_TOOLS,
    LOG_PATH,
    MAX_TOOL_CALLS_PER_TURN,
    PROFILE_PATH,
    SYSTEM_PROMPT,
    TOOLS,
)
from .gates import confirmation_gate
from .memory import MemoryStore
from .retry import retry
from .tools import execute, ToolResult

logger = logging.getLogger(__name__)

# Retry config for Claude API calls
RETRYABLE_API_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


class Agent:
    """Ride-booking agent with Plan-Execute-Verify loop, memory, and guardrails."""

    def __init__(self):
        self.client = anthropic.Anthropic()
        self.adapter = UberAdapter(base_url=API_BASE)
        self.profile = UserProfile(PROFILE_PATH)
        self.log = ActionLog(LOG_PATH)
        self.memory = MemoryStore()

    def _choose_model(self) -> str:
        models = {
            "1": ("claude-sonnet-4-6", "Sonnet 4.6 (fast, cheap)"),
            "2": ("claude-opus-4-6", "Opus 4.6 (smartest)"),
            "3": ("claude-haiku-4-5", "Haiku 4.5 (fastest, cheapest)"),
        }
        print("Select a model:")
        for key, (_, desc) in models.items():
            print(f"  {key}. {desc}")
        choice = input("Choice [1]: ").strip() or "1"
        model_id, desc = models.get(choice, models["1"])
        print(f"Using: {desc}")
        return model_id

    def start(self):
        """Launch the interactive conversation loop."""
        model = self._choose_model()
        self.model = model

        print()
        print("Ride-Booking Agent (type 'quit' to exit)")
        print(f"Model: {self.model}")
        print("Guardrails: ON")
        print("-" * 50)

        if not self._check_server():
            sys.exit(1)

        # Recover state from previous session
        recovery_msg = self.memory.recover_state()
        if recovery_msg:
            print(f"[{recovery_msg}]")

        print("Server connected. Ready!\n")

        try:
            self._conversation_loop()
        finally:
            self.memory.close()

    def _check_server(self) -> bool:
        try:
            httpx.get(f"{API_BASE}/docs", timeout=5.0)
            return True
        except httpx.RequestError:
            logger.error(f"Server not running at {API_BASE}")
            print(f"ERROR: Server not running at {API_BASE}")
            print("Start it first: ./start.sh or ./start-docker.sh")
            return False

    def _conversation_loop(self):
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            # Input guardrail (always on)
            is_safe, _ = check_input(user_input)
            if not is_safe:
                print("Agent: I'm a ride booking assistant. Where would you like to go?")
                continue

            self.memory.add_message("user", user_input)
            self._agent_turn()

    def _build_system_prompt(self) -> str:
        """Build system prompt with working memory, episodic context, and semantic memory."""
        parts = [SYSTEM_PROMPT.format(state=self.memory.working)]

        # Add episodic context
        history = self.memory.ride_history_summary()
        if history and history != "No ride history yet.":
            parts.append(f"\n## Ride History\n{history}")

        # Add semantic context
        semantic = self.memory.semantic_context()
        if semantic:
            parts.append(f"\n## User Patterns\n{semantic}")

        return "\n".join(parts)

    def _agent_turn(self):
        """Plan-Execute-Verify loop for one agent turn."""
        tool_call_count = 0
        last_tool_call: tuple[str, str] | None = None

        # Prune conversation if needed
        self.memory.prune_if_needed()

        while True:
            system = self._build_system_prompt()
            messages = self.memory.get_messages_for_api()

            try:
                response = self._call_api(system, messages)
            except anthropic.APIError as e:
                logger.error(f"API error: {e.message}")
                print(f"\nAPI Error: {e.message}")
                # Don't pop the user message — let them retry
                self.memory.add_message(
                    "assistant",
                    "I'm having trouble connecting right now. Could you try again?",
                )
                self.memory.record_episode("error", f"API error: {e.message}")
                break

            content = response.content

            if response.stop_reason != "tool_use":
                self._handle_text_response(content)
                break

            tool_results = []
            for block in content:
                if block.type == "text" and block.text:
                    self._safe_print(block.text)

                if block.type != "tool_use":
                    continue

                tool_call_count += 1
                result = self._handle_tool_call(block, tool_call_count, last_tool_call)
                tool_results.append(result["tool_result"])
                if result.get("call_key"):
                    last_tool_call = result["call_key"]

            self.memory.add_message("assistant", content)
            self.memory.add_message("user", tool_results)

            # Loop guard
            if tool_call_count > MAX_TOOL_CALLS_PER_TURN + 2:
                logger.warning(f"Tool call limit reached ({tool_call_count})")
                print("Agent: Let me stop here. What would you like to do?")
                self.memory.add_message(
                    "assistant",
                    "Let me stop here. What would you like to do?",
                )
                break

    @retry(max_attempts=3, base_delay=1.0, retryable=RETRYABLE_API_ERRORS)
    def _call_api(self, system: str, messages: list[dict]):
        """Call Claude API with retry logic."""
        return self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=TOOLS,
        )

    def _handle_tool_call(
        self, block, call_count: int, last_call: tuple[str, str] | None,
    ) -> dict:
        """Execute a tool call with guards, verification, and memory updates."""
        tool_name = block.name
        tool_input = block.input
        tool_id = block.id

        # Loop guard
        if call_count > MAX_TOOL_CALLS_PER_TURN:
            return {
                "tool_result": {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "LOOP LIMIT: Stop calling tools and respond to the user.",
                },
            }

        # Dedup guard
        params_key = json.dumps(tool_input, sort_keys=True)
        call_key = (tool_name, params_key)
        if call_key == last_call:
            return {
                "tool_result": {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "DUPLICATE: You just made this exact call. Try something different or respond.",
                },
            }

        # Confirmation gate
        if tool_name in GATED_TOOLS:
            approved = confirmation_gate(tool_name, tool_input, self.adapter, self.log)
            if not approved:
                self.memory.record_episode(
                    "gate_denied", f"User denied {tool_name}", {"params": tool_input}
                )
                return {
                    "tool_result": {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": "USER DENIED this action. Do not retry. Ask the user what they'd like to do.",
                    },
                    "call_key": call_key,
                }

        # Execute
        try:
            result = execute(tool_name, tool_input, self.adapter, self.profile)
        except Exception as e:
            logger.error(f"Unexpected error in {tool_name}: {e}")
            self.memory.record_episode("error", f"Tool {tool_name} failed: {e}")
            return {
                "tool_result": {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": f"Error executing {tool_name}: {e}. Try a different approach.",
                },
                "call_key": call_key,
            }

        # --- Verify & Update Memory ---
        self.memory.working.update_from_tool(tool_name, result.data)
        self.memory.save_working_memory()

        # Record episodes for significant events
        self._record_episodes(tool_name, result)

        # Learn from user behavior
        self._learn_from_action(tool_name, result)

        # Log
        self.log.record(
            tool=tool_name,
            intent=f"{tool_name} call",
            params=tool_input,
            gate_required=tool_name in GATED_TOOLS,
            gate_decision="approved" if tool_name in GATED_TOOLS else None,
            success=not result.data.get("error"),
            result=result.display[:200],
        )

        return {
            "tool_result": {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result.display,
            },
            "call_key": call_key,
        }

    def _record_episodes(self, tool_name: str, result: ToolResult):
        """Record significant events to episodic memory."""
        data = result.data

        if tool_name == "book_ride" and not data.get("error"):
            self.memory.record_episode(
                "ride_booked",
                f"Booked {data.get('car_type_name', '?')} for ${data.get('price', '?')} from {data.get('pickup', '?')}",
                data,
            )
        elif tool_name == "cancel_ride" and data.get("canceled"):
            self.memory.record_episode(
                "ride_canceled",
                f"Canceled ride. Fee: ${data.get('fee', 0):.2f}, Refund: ${data.get('refund', 0):.2f}",
                data,
            )
        elif tool_name == "check_status" and data.get("final_fare") is not None:
            self.memory.record_episode(
                "ride_completed",
                f"Ride completed. Final fare: ${data['final_fare']:.2f}",
                data,
            )
        elif data.get("error"):
            self.memory.record_episode(
                "error",
                f"{tool_name} failed: {data.get('error')} - {data.get('message', '')}",
                data,
            )

    def _learn_from_action(self, tool_name: str, result: ToolResult):
        """Update semantic memory based on user patterns."""
        data = result.data

        if tool_name == "book_ride" and data.get("car_type_name"):
            current = self.memory.recall("preferred_car_type")
            car = data["car_type_name"]
            if current and current != car:
                self.memory.learn("preferred_car_type", car, confidence=0.8)
            elif not current:
                self.memory.learn("preferred_car_type", car, confidence=0.6)

        if tool_name == "save_preference":
            key = data.get("preference_key", "")
            value = str(data.get("preference_value", ""))
            self.memory.learn(f"explicit_pref_{key}", value, confidence=1.0)

    def _handle_text_response(self, content):
        """Print final text response with output guardrail."""
        for block in content:
            if hasattr(block, "text") and block.text:
                self._safe_print(block.text)
        self.memory.add_message("assistant", content)

    def _safe_print(self, text: str):
        """Print with output guardrail."""
        is_safe, reason = check_output(text)
        if not is_safe:
            logger.warning(f"Output blocked: {reason}")
            print("Agent: I'm a ride booking assistant. Where would you like to go?")
            return
        print(f"Agent: {text}")
