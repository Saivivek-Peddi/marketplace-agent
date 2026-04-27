"""Memory system — short-term, working, episodic, and semantic memory.

Provides structured persistence across sessions with SQLite backing.
Replaces the flat message list and string-parsed AgentState.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DB_PATH = Path("agent_memory.db")
MAX_SHORT_TERM_MESSAGES = 40
MAX_EPISODIC_ENTRIES = 100
TOKEN_ESTIMATE_RATIO = 4  # ~4 chars per token


@dataclass
class WorkingMemory:
    """Active entities the agent is currently working with."""
    active_ride_id: str | None = None
    last_estimate_id: str | None = None
    last_quote_id: str | None = None
    ride_status: str | None = None
    pending_action: str | None = None
    last_error: str | None = None

    def update_from_tool(self, tool_name: str, data: dict):
        """Update working memory from structured tool result data."""
        if "estimate_id" in data:
            self.last_estimate_id = data["estimate_id"]
        if "quote_id" in data:
            self.last_quote_id = data["quote_id"]
        if "ride_id" in data:
            self.active_ride_id = data["ride_id"]
        if "status" in data:
            self.ride_status = data["status"]
        if "error" in data:
            self.last_error = data["error"]
        else:
            self.last_error = None

        if tool_name == "cancel_ride" and not data.get("error"):
            self.active_ride_id = None
            self.ride_status = "canceled"
            self.last_quote_id = None

        if tool_name == "book_ride" and not data.get("error"):
            self.pending_action = None
            self.last_quote_id = None

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class EpisodicEntry:
    """A record of a past interaction or ride."""
    timestamp: float
    event_type: str  # "ride_completed", "ride_canceled", "error", "preference_learned"
    summary: str
    details: dict = field(default_factory=dict)


class MemoryStore:
    """Multi-layer memory system with SQLite persistence.

    Layers:
    - Short-term: Current conversation messages (pruned with summarization)
    - Working: Active entities (ride IDs, estimate IDs, current status)
    - Episodic: Past rides, errors, notable events
    - Semantic: Learned user preferences and patterns
    """

    def __init__(self, db_path: str | Path = DB_PATH):
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self._db_path))
        self._init_tables()

        # Short-term: in-memory conversation messages
        self.messages: list[dict] = []
        self._summary: str | None = None

        # Working: active state
        self.working = WorkingMemory()

        # Load persisted state
        self._load_working_memory()

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodic (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS semantic (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS working_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS conversation_summary (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                summary TEXT
            );
        """)
        self._conn.commit()

    # --- Short-term memory (conversation) ---

    def add_message(self, role: str, content: Any):
        """Add a message to short-term memory."""
        self.messages.append({"role": role, "content": content})

    def estimate_tokens(self) -> int:
        """Rough token estimate for current conversation."""
        total_chars = sum(len(str(m.get("content", ""))) for m in self.messages)
        if self._summary:
            total_chars += len(self._summary)
        return total_chars // TOKEN_ESTIMATE_RATIO

    def prune_if_needed(self, max_tokens: int = 120_000, target_tokens: int = 80_000):
        """Prune old messages if over token budget, keeping context via summary."""
        if self.estimate_tokens() <= max_tokens:
            return

        # Keep first 2 messages (initial context) and last 6 (current turn)
        keep_start = min(2, len(self.messages))
        keep_end = min(6, len(self.messages))

        if len(self.messages) <= keep_start + keep_end:
            return

        # Summarize messages being pruned
        to_prune = self.messages[keep_start:-keep_end]
        summary_parts = []
        if self._summary:
            summary_parts.append(self._summary)

        for msg in to_prune:
            content = str(msg.get("content", ""))[:200]
            summary_parts.append(f"[{msg['role']}]: {content}")

        self._summary = "Previous conversation summary:\n" + "\n".join(summary_parts[-20:])
        self._save_summary()

        # Prune
        self.messages = self.messages[:keep_start] + self.messages[-keep_end:]

    def get_messages_for_api(self) -> list[dict]:
        """Get messages formatted for the Claude API, with summary injected."""
        if not self._summary:
            return self.messages

        # Inject summary as first user context
        summary_msg = {
            "role": "user",
            "content": f"[Context from earlier in conversation]\n{self._summary}",
        }
        if len(self.messages) > 0:
            return [summary_msg] + self.messages
        return self.messages

    def _save_summary(self):
        self._conn.execute(
            "INSERT OR REPLACE INTO conversation_summary (id, summary) VALUES (1, ?)",
            (self._summary,),
        )
        self._conn.commit()

    def _load_summary(self):
        row = self._conn.execute(
            "SELECT summary FROM conversation_summary WHERE id = 1"
        ).fetchone()
        if row:
            self._summary = row[0]

    # --- Working memory (active state) ---

    def save_working_memory(self):
        """Persist working memory to SQLite for crash recovery."""
        data = self.working.to_dict()
        for key, value in data.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO working_state (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
        self._conn.commit()

    def _load_working_memory(self):
        """Restore working memory from SQLite."""
        rows = self._conn.execute("SELECT key, value FROM working_state").fetchall()
        for key, value in rows:
            parsed = json.loads(value)
            if hasattr(self.working, key):
                setattr(self.working, key, parsed)

    def has_active_ride(self) -> bool:
        return self.working.active_ride_id is not None

    # --- Episodic memory (past events) ---

    def record_episode(self, event_type: str, summary: str, details: dict | None = None):
        """Record a notable event for future reference."""
        self._conn.execute(
            "INSERT INTO episodic (timestamp, event_type, summary, details) VALUES (?, ?, ?, ?)",
            (time.time(), event_type, summary, json.dumps(details or {})),
        )
        self._conn.commit()

        # Prune old entries
        count = self._conn.execute("SELECT COUNT(*) FROM episodic").fetchone()[0]
        if count > MAX_EPISODIC_ENTRIES:
            self._conn.execute(
                "DELETE FROM episodic WHERE id IN (SELECT id FROM episodic ORDER BY timestamp ASC LIMIT ?)",
                (count - MAX_EPISODIC_ENTRIES,),
            )
            self._conn.commit()

    def recent_episodes(self, count: int = 10, event_type: str | None = None) -> list[EpisodicEntry]:
        """Retrieve recent episodes, optionally filtered by type."""
        if event_type:
            rows = self._conn.execute(
                "SELECT timestamp, event_type, summary, details FROM episodic WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
                (event_type, count),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT timestamp, event_type, summary, details FROM episodic ORDER BY timestamp DESC LIMIT ?",
                (count,),
            ).fetchall()
        return [
            EpisodicEntry(
                timestamp=r[0], event_type=r[1], summary=r[2],
                details=json.loads(r[3]),
            )
            for r in rows
        ]

    def ride_history_summary(self) -> str:
        """Generate a summary of past rides for the system prompt."""
        rides = self.recent_episodes(5, event_type="ride_completed")
        cancels = self.recent_episodes(3, event_type="ride_canceled")
        errors = self.recent_episodes(3, event_type="error")

        parts = []
        if rides:
            parts.append(f"Recent rides ({len(rides)}):")
            for r in rides:
                parts.append(f"  - {r.summary}")
        if cancels:
            parts.append(f"Recent cancellations ({len(cancels)}):")
            for c in cancels:
                parts.append(f"  - {c.summary}")
        if errors:
            parts.append(f"Recent errors ({len(errors)}):")
            for e in errors:
                parts.append(f"  - {e.summary}")

        return "\n".join(parts) if parts else "No ride history yet."

    # --- Semantic memory (learned preferences) ---

    def learn(self, key: str, value: str, confidence: float = 1.0):
        """Store a learned preference or pattern."""
        self._conn.execute(
            "INSERT OR REPLACE INTO semantic (key, value, confidence, updated_at) VALUES (?, ?, ?, ?)",
            (key, value, confidence, time.time()),
        )
        self._conn.commit()

    def recall(self, key: str) -> str | None:
        """Recall a learned preference."""
        row = self._conn.execute(
            "SELECT value FROM semantic WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def all_learned(self) -> dict[str, str]:
        """Get all learned preferences."""
        rows = self._conn.execute(
            "SELECT key, value FROM semantic ORDER BY updated_at DESC"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def semantic_context(self) -> str:
        """Generate context string for system prompt from semantic memory."""
        learned = self.all_learned()
        if not learned:
            return ""
        parts = ["Learned about this user:"]
        for key, value in learned.items():
            parts.append(f"  - {key}: {value}")
        return "\n".join(parts)

    # --- Lifecycle ---

    def close(self):
        """Persist everything and close."""
        self.save_working_memory()
        self._conn.close()

    def recover_state(self) -> str | None:
        """Check if there's an active ride from a previous session."""
        self._load_working_memory()
        self._load_summary()
        if self.working.active_ride_id:
            return (
                f"Recovered active ride from previous session: "
                f"{self.working.active_ride_id} (status: {self.working.ride_status})"
            )
        return None
