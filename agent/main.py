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
from . import ui
from .memory import MemoryStore, list_sessions
from .retry import retry
from .tools import execute, ToolResult

logger = logging.getLogger(__name__)

RETRYABLE_API_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


class Agent:
    """Ride-booking agent with Plan-Execute-Verify loop, memory, and guardrails."""

    def __init__(self, session_name: str = "default"):
        self.client = anthropic.Anthropic()
        self.adapter = UberAdapter(base_url=API_BASE)
        self.profile = UserProfile(PROFILE_PATH)
        self.log = ActionLog(LOG_PATH)
        self.session_name = session_name
        self.memory = MemoryStore(session_name=session_name)

    def _choose_model(self) -> str:
        models = {
            "1": ("claude-sonnet-4-6", "Sonnet 4.6 (fast, cheap)"),
            "2": ("claude-opus-4-6", "Opus 4.6 (smartest)"),
            "3": ("claude-haiku-4-5", "Haiku 4.5 (fastest, cheapest)"),
        }
        choice = ui.model_menu(models)
        model_id, desc = models.get(choice, models["1"])
        ui.success(f"Using {desc}")
        return model_id

    def start(self):
        ui.banner()
        model = self._choose_model()
        self.model = model

        print()
        ui.status_line(self.model)
        ui.session_info(self.session_name)

        if not self._check_server():
            sys.exit(1)

        ui.server_connected()
        print()

        # Show saved places and preferences
        ui.saved_places(self.profile.list_places())
        ui.preferences(self.profile.list_preferences())
        rides = self.profile.recent_rides(3)
        if rides:
            ui.recent_rides(rides)
        print()

        # Show conversation history if resuming a session
        if self.memory.is_resumed_session():
            history = self.memory.conversation_history(limit=10)
            stats = self.memory.session_stats()
            if history:
                ui.conversation_history(history, stats)

        # Check for active ride from previous session
        recovery_msg = self.memory.recover_state()
        if recovery_msg:
            ride_id = self.memory.working.active_ride_id
            if ride_id:
                try:
                    self.adapter.status(ride_id)
                    ui.recovery(recovery_msg)
                except Exception:
                    self.memory.working.active_ride_id = None
                    self.memory.working.ride_status = None
                    self.memory.save_working_memory()
                    ui.info("Previous ride session cleared (ride no longer active).")
            print()

        try:
            self._conversation_loop()
        finally:
            self.memory.close()

    def _check_server(self) -> bool:
        try:
            httpx.get(f"{API_BASE}/docs", timeout=5.0)
            return True
        except httpx.RequestError:
            ui.server_failed(API_BASE)
            return False

    def _conversation_loop(self):
        while True:
            user_input = ui.user_prompt()

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                ui.goodbye()
                break

            is_safe, _ = check_input(user_input)
            if not is_safe:
                ui.agent_blocked()
                continue

            self.memory.add_message("user", user_input)
            self._agent_turn()

    def _build_system_prompt(self) -> str:
        parts = [SYSTEM_PROMPT.format(state=self.memory.working)]

        history = self.memory.ride_history_summary()
        if history and history != "No ride history yet.":
            parts.append(f"\n## Ride History\n{history}")

        semantic = self.memory.semantic_context()
        if semantic:
            parts.append(f"\n## User Patterns\n{semantic}")

        return "\n".join(parts)

    def _agent_turn(self):
        tool_call_count = 0
        last_tool_call: tuple[str, str] | None = None

        self.memory.prune_if_needed()

        while True:
            system = self._build_system_prompt()
            messages = self.memory.get_messages_for_api()

            ui.thinking()

            try:
                response = self._call_api(system, messages)
            except anthropic.APIError as e:
                ui.clear_thinking()
                ui.error(f"API error: {e.message}")
                self.memory.add_message(
                    "assistant",
                    "I'm having trouble connecting right now. Could you try again?",
                )
                self.memory.record_episode("error", f"API error: {e.message}")
                break

            ui.clear_thinking()
            content = response.content

            if response.stop_reason != "tool_use":
                self._handle_text_response(content)
                break

            tool_results = []
            for block in content:
                if block.type == "text" and block.text:
                    ui.agent_message(block.text)

                if block.type != "tool_use":
                    continue

                tool_call_count += 1
                ui.tool_call(block.name)

                result = self._handle_tool_call(block, tool_call_count, last_tool_call)
                tool_results.append(result["tool_result"])
                if result.get("call_key"):
                    last_tool_call = result["call_key"]

            self.memory.add_message("assistant", content)
            self.memory.add_message("user", tool_results)

            if tool_call_count > MAX_TOOL_CALLS_PER_TURN + 2:
                ui.agent_message("Let me stop here. What would you like to do?")
                self.memory.add_message(
                    "assistant", "Let me stop here. What would you like to do?",
                )
                break

    @retry(max_attempts=3, base_delay=1.0, retryable=RETRYABLE_API_ERRORS)
    def _call_api(self, system: str, messages: list[dict]):
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
        tool_name = block.name
        tool_input = block.input
        tool_id = block.id

        if call_count > MAX_TOOL_CALLS_PER_TURN:
            return {
                "tool_result": {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "LOOP LIMIT: Stop calling tools and respond to the user.",
                },
            }

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

        if tool_name in GATED_TOOLS:
            approved = self._confirmation_gate(tool_name, tool_input)
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

        self.memory.working.update_from_tool(tool_name, result.data)
        self.memory.save_working_memory()
        self._record_episodes(tool_name, result)
        self._learn_from_action(tool_name, result)

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

    def _confirmation_gate(self, tool_name: str, params: dict) -> bool:
        """Pretty confirmation gate using ui module."""
        details = []
        if tool_name == "cancel_ride":
            try:
                fee = self.adapter.cancel_fee(params["ride_id"])
                details.append(f"Cancel fee: ${fee.fee.amount:.2f}")
                details.append(f"Reason: {fee.reason}")
            except Exception:
                details.append("(Could not fetch cancel fee preview)")

        answer = ui.confirmation_box(tool_name, details)
        approved = answer in ("yes", "y")

        self.log.record(
            tool=tool_name,
            intent=f"Confirmation gate for {tool_name}",
            params=params,
            gate_required=True,
            gate_decision="approved" if approved else "denied",
            gate_message=f"User said: {answer}",
            success=approved,
        )

        return approved

    def _record_episodes(self, tool_name: str, result: ToolResult):
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
        text_parts = []
        for block in content:
            if hasattr(block, "text") and block.text:
                is_safe, reason = check_output(block.text)
                if not is_safe:
                    logger.warning(f"Output blocked: {reason}")
                    ui.agent_blocked()
                    return
                ui.agent_message(block.text)
                text_parts.append(block.text)
        # Save raw content for Claude API, and text for conversation log
        self.memory.add_message("assistant", content)
        if text_parts:
            # Also log the readable text for history replay
            self._log_assistant_text("\n".join(text_parts))

    def _log_assistant_text(self, text: str):
        """Save assistant text to conversation log for history replay."""
        import time as _time
        self.memory._conn.execute(
            "INSERT INTO conversation_log (timestamp, role, content) VALUES (?, ?, ?)",
            (_time.time(), "assistant", text),
        )
        self.memory._conn.commit()
