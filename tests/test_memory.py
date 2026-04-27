"""Tests for the memory system."""

import os
import tempfile

import pytest

from agent.memory import MemoryStore, WorkingMemory


@pytest.fixture
def memory():
    """Create a fresh MemoryStore with temp database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = MemoryStore(db_path=path)
    yield store
    store.close()
    os.unlink(path)


class TestWorkingMemory:
    def test_initial_state(self):
        wm = WorkingMemory()
        assert wm.active_ride_id is None
        assert wm.last_estimate_id is None
        assert wm.last_quote_id is None

    def test_update_from_search(self):
        wm = WorkingMemory()
        wm.update_from_tool("search_rides", {"estimate_id": "est_abc123"})
        assert wm.last_estimate_id == "est_abc123"

    def test_update_from_quote(self):
        wm = WorkingMemory()
        wm.update_from_tool("get_quote", {"quote_id": "qt_xyz789"})
        assert wm.last_quote_id == "qt_xyz789"

    def test_update_from_book(self):
        wm = WorkingMemory()
        wm.last_quote_id = "qt_xyz789"
        wm.update_from_tool("book_ride", {"ride_id": "ride_001", "status": "processing"})
        assert wm.active_ride_id == "ride_001"
        assert wm.ride_status == "processing"
        assert wm.last_quote_id is None  # consumed

    def test_update_from_cancel(self):
        wm = WorkingMemory()
        wm.active_ride_id = "ride_001"
        wm.update_from_tool("cancel_ride", {"ride_id": "ride_001", "canceled": True})
        assert wm.active_ride_id is None
        assert wm.ride_status == "canceled"

    def test_update_from_error(self):
        wm = WorkingMemory()
        wm.update_from_tool("book_ride", {"error": "QUOTE_EXPIRED", "message": "gone"})
        assert wm.last_error == "QUOTE_EXPIRED"

    def test_error_clears_on_success(self):
        wm = WorkingMemory()
        wm.last_error = "QUOTE_EXPIRED"
        wm.update_from_tool("search_rides", {"estimate_id": "est_new"})
        assert wm.last_error is None


class TestMemoryStoreShortTerm:
    def test_add_and_retrieve_messages(self, memory):
        memory.add_message("user", "hello")
        memory.add_message("assistant", "hi there")
        assert len(memory.messages) == 2
        assert memory.messages[0]["role"] == "user"

    def test_token_estimation(self, memory):
        memory.add_message("user", "a" * 400)
        tokens = memory.estimate_tokens()
        assert tokens == 100  # 400 chars / 4

    def test_pruning(self, memory):
        # Add enough messages to trigger pruning
        for i in range(50):
            memory.add_message("user", f"message {i} " + "x" * 5000)
            memory.add_message("assistant", f"response {i} " + "y" * 5000)

        memory.prune_if_needed(max_tokens=1000, target_tokens=500)
        assert len(memory.messages) < 100
        assert memory._summary is not None

    def test_get_messages_with_summary(self, memory):
        memory._summary = "Previous context: user asked about rides"
        memory.add_message("user", "hello")
        msgs = memory.get_messages_for_api()
        assert len(msgs) == 2  # summary + actual message
        assert "Previous context" in msgs[0]["content"]


class TestMemoryStorePersistence:
    def test_working_memory_persistence(self, memory):
        memory.working.active_ride_id = "ride_123"
        memory.working.ride_status = "matched"
        memory.save_working_memory()

        # Create new store with same DB
        memory2 = MemoryStore(db_path=memory._db_path)
        assert memory2.working.active_ride_id == "ride_123"
        assert memory2.working.ride_status == "matched"
        memory2.close()

    def test_recover_state(self, memory):
        memory.working.active_ride_id = "ride_456"
        memory.working.ride_status = "in_progress"
        memory.save_working_memory()

        memory2 = MemoryStore(db_path=memory._db_path)
        msg = memory2.recover_state()
        assert msg is not None
        assert "ride_456" in msg
        memory2.close()

    def test_recover_state_no_active_ride(self, memory):
        msg = memory.recover_state()
        assert msg is None


class TestEpisodicMemory:
    def test_record_and_retrieve(self, memory):
        memory.record_episode("ride_completed", "Ride from A to B, $25", {"price": 25})
        episodes = memory.recent_episodes(10)
        assert len(episodes) == 1
        assert episodes[0].event_type == "ride_completed"
        assert episodes[0].details["price"] == 25

    def test_filter_by_type(self, memory):
        memory.record_episode("ride_completed", "ride 1")
        memory.record_episode("error", "something broke")
        memory.record_episode("ride_completed", "ride 2")

        rides = memory.recent_episodes(10, event_type="ride_completed")
        assert len(rides) == 2
        errors = memory.recent_episodes(10, event_type="error")
        assert len(errors) == 1

    def test_max_entries_pruning(self, memory):
        for i in range(150):
            memory.record_episode("test", f"event {i}")
        episodes = memory.recent_episodes(200)
        assert len(episodes) <= 100

    def test_ride_history_summary(self, memory):
        memory.record_episode("ride_completed", "Downtown to Airport, $35")
        summary = memory.ride_history_summary()
        assert "Downtown to Airport" in summary


class TestSemanticMemory:
    def test_learn_and_recall(self, memory):
        memory.learn("preferred_car_type", "UberX")
        assert memory.recall("preferred_car_type") == "UberX"

    def test_overwrite(self, memory):
        memory.learn("preferred_car_type", "UberX")
        memory.learn("preferred_car_type", "Comfort")
        assert memory.recall("preferred_car_type") == "Comfort"

    def test_recall_missing(self, memory):
        assert memory.recall("nonexistent") is None

    def test_all_learned(self, memory):
        memory.learn("car", "UberX")
        memory.learn("area", "downtown")
        learned = memory.all_learned()
        assert len(learned) == 2

    def test_semantic_context(self, memory):
        memory.learn("preferred_car_type", "Comfort")
        ctx = memory.semantic_context()
        assert "preferred_car_type" in ctx
        assert "Comfort" in ctx
