"""Tests for simulation engine — state machine, store, pricing."""

import asyncio

import pytest

from server.models import RideStatus, VALID_TRANSITIONS, TERMINAL_STATUSES
from server.simulation import Store, RideState, compute_price_range


class TestRideStateTransitions:
    def _make_ride(self, status=RideStatus.PROCESSING):
        from server.models import Location
        return RideState(
            ride_id="ride_test",
            status=status,
            car_type_id="uberx",
            car_type_name="UberX",
            price_amount=25.0,
            surge_multiplier=1.0,
            surge_is_surging=False,
            pickup=Location(address="A", lat=40.0, lng=-74.0),
            dropoff=Location(address="B", lat=40.1, lng=-74.1),
            estimated_duration_minutes=15,
            estimated_distance_miles=5.0,
            pickup_eta_minutes=3,
        )

    def test_valid_transition_processing_to_matched(self):
        ride = self._make_ride(RideStatus.PROCESSING)
        ride.transition(RideStatus.MATCHED)
        assert ride.status == RideStatus.MATCHED

    def test_valid_transition_matched_to_arriving(self):
        ride = self._make_ride(RideStatus.MATCHED)
        ride.transition(RideStatus.ARRIVING)
        assert ride.status == RideStatus.ARRIVING

    def test_valid_transition_matched_to_processing(self):
        """Driver cancel scenario — MATCHED back to PROCESSING."""
        ride = self._make_ride(RideStatus.MATCHED)
        ride.transition(RideStatus.PROCESSING)
        assert ride.status == RideStatus.PROCESSING

    def test_invalid_transition_raises(self):
        ride = self._make_ride(RideStatus.PROCESSING)
        with pytest.raises(Exception):
            ride.transition(RideStatus.IN_PROGRESS)  # skip MATCHED

    def test_cancel_from_any_active_state(self):
        for status in [RideStatus.PROCESSING, RideStatus.MATCHED, RideStatus.ARRIVING, RideStatus.IN_PROGRESS]:
            ride = self._make_ride(status)
            ride.transition(RideStatus.CANCELED)
            assert ride.status == RideStatus.CANCELED

    def test_terminal_states_no_transitions(self):
        for status in TERMINAL_STATUSES:
            ride = self._make_ride(status)
            with pytest.raises(Exception):
                ride.transition(RideStatus.PROCESSING)


class TestStore:
    def test_new_id_format(self):
        store = Store()
        id1 = store.new_id("est")
        assert id1.startswith("est_")
        assert len(id1) > 4

    def test_unique_ids(self):
        store = Store()
        ids = {store.new_id("test") for _ in range(100)}
        assert len(ids) == 100

    def test_active_ride_none(self):
        store = Store()
        assert store.active_ride() is None

    def test_has_lock(self):
        store = Store()
        assert hasattr(store, "lock")
        assert isinstance(store.lock, asyncio.Lock)


class TestValidTransitions:
    def test_matched_allows_processing(self):
        """Verify our fix: MATCHED -> PROCESSING is valid (driver cancel)."""
        assert RideStatus.PROCESSING in VALID_TRANSITIONS[RideStatus.MATCHED]

    def test_all_active_states_allow_cancel(self):
        active_states = [s for s in RideStatus if s not in TERMINAL_STATUSES]
        for status in active_states:
            assert RideStatus.CANCELED in VALID_TRANSITIONS[status], \
                f"{status} should allow transition to CANCELED"
