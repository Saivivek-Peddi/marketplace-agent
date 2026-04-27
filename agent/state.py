"""Agent state tracker — DEPRECATED, use agent.memory instead.

Kept for backward compatibility with imports. All state is now
managed by MemoryStore.working (WorkingMemory).
"""

from __future__ import annotations

from .memory import WorkingMemory

# Re-export for any code still importing AgentState
AgentState = WorkingMemory
