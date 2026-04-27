"""Uber platform adapter.

Translates between the abstract RideAdapter interface and
the Uber (mock) REST API. To swap platforms, write a new adapter
that implements the same interface — no MCP tool changes needed.
"""

from __future__ import annotations

import httpx

from ..adapter import (
    AdapterError,
    BookResult,
    CancelFee,
    CancelFeeResult,
    CancelResult,
    ConnectionError,
    Driver,
    Location,
    PriceRange,
    QuoteResult,
    RideAdapter,
    RideOption,
    SearchResult,
    StatusResult,
    Surge,
    TripProgress,
    CancellationInfo,
    Vehicle,
)


class UberAdapter(RideAdapter):
    """Adapter for the Uber (mock) API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._http = httpx.Client(base_url=base_url, timeout=timeout)
        self._scenario: str | None = None

    def set_scenario(self, scenario: str | None) -> None:
        """Set test scenario header (Uber-specific test hook)."""
        self._scenario = scenario

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._scenario:
            headers["X-Scenario"] = self._scenario
        return headers

    def _raise_for_error(self, resp: httpx.Response) -> None:
        """Parse Uber error response and raise AdapterError."""
        try:
            detail = resp.json().get("detail", {})
            if isinstance(detail, dict):
                raise AdapterError(
                    detail.get("error", "UNKNOWN"),
                    detail.get("message", ""),
                )
            raise AdapterError("UNKNOWN", str(detail))
        except AdapterError:
            raise
        except Exception:
            raise AdapterError("HTTP_ERROR", f"HTTP {resp.status_code}")

    #  Interface methods 

    def search(self, pickup: str, dropoff: str) -> SearchResult:
        try:
            resp = self._http.post(
                "/v1/estimates",
                json={"pickup": pickup, "dropoff": dropoff},
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise ConnectionError(f"Could not connect to Uber API: {e}")

        if resp.status_code != 200:
            self._raise_for_error(resp)

        data = resp.json()
        return SearchResult(
            estimate_id=data["estimate_id"],
            pickup=_parse_location(data["pickup"]),
            dropoff=_parse_location(data["dropoff"]),
            options=[_parse_option(o) for o in data["options"]],
        )

    def quote(self, estimate_id: str, car_type_id: str) -> QuoteResult:
        try:
            resp = self._http.post(
                "/v1/quotes",
                json={
                    "estimate_id": estimate_id,
                    "car_type_id": car_type_id,
                },
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise ConnectionError(f"Could not connect to Uber API: {e}")

        if resp.status_code != 200:
            self._raise_for_error(resp)

        data = resp.json()
        return QuoteResult(
            quote_id=data["quote_id"],
            car_type_id=data["car_type_id"],
            car_type_name=data["car_type_name"],
            pickup=_parse_location(data["pickup"]),
            dropoff=_parse_location(data["dropoff"]),
            price=data["price"]["amount"],
            currency=data["price"].get("currency", "USD"),
            surge=_parse_surge(data["surge"]),
            pickup_eta_minutes=data["pickup_eta_minutes"],
            trip_duration_minutes=data["trip_duration_minutes"],
            trip_distance_miles=data["trip_distance_miles"],
            expires_at=data["expires_at"],
        )

    def book(self, quote_id: str) -> BookResult:
        try:
            resp = self._http.post(
                "/v1/rides",
                json={"quote_id": quote_id},
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise ConnectionError(f"Could not connect to Uber API: {e}")

        if resp.status_code not in (200, 201):
            self._raise_for_error(resp)

        data = resp.json()
        return BookResult(
            ride_id=data["ride_id"],
            status=data["status"],
            car_type_name=data["car_type"]["name"],
            price=data["price"]["amount"],
            currency=data["price"].get("currency", "USD"),
            pickup_address=data["pickup"]["address"],
            dropoff_address=data["dropoff"]["address"],
            driver=_parse_driver(data.get("driver")),
        )

    def status(self, ride_id: str) -> StatusResult:
        try:
            resp = self._http.get(
                f"/v1/rides/{ride_id}",
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise ConnectionError(f"Could not connect to Uber API: {e}")

        if resp.status_code != 200:
            self._raise_for_error(resp)

        data = resp.json()
        trip_data = data.get("trip", {})

        cancellation = None
        if data.get("cancellation"):
            c = data["cancellation"]
            cancellation = CancellationInfo(
                fee=c["fee"]["amount"],
                reason=c["reason"],
                canceled_at=c["canceled_at"],
            )

        return StatusResult(
            ride_id=data["ride_id"],
            status=data["status"],
            status_description=data["status_description"],
            car_type_name=data["car_type"]["name"],
            price=data["price"]["amount"],
            currency=data["price"].get("currency", "USD"),
            surge=_parse_surge(data.get("surge", {})),
            pickup_address=data["pickup"]["address"],
            pickup_eta_minutes=data["pickup"].get("eta_minutes"),
            pickup_arrived_at=data["pickup"].get("arrived_at"),
            dropoff_address=data["dropoff"]["address"],
            dropoff_eta_minutes=data["dropoff"].get("eta_minutes"),
            dropoff_arrived_at=data["dropoff"].get("arrived_at"),
            trip=TripProgress(
                estimated_duration_minutes=trip_data.get(
                    "estimated_duration_minutes", 0
                ),
                estimated_distance_miles=trip_data.get(
                    "estimated_distance_miles", 0
                ),
                elapsed_minutes=trip_data.get("elapsed_minutes", 0),
                distance_traveled_miles=trip_data.get(
                    "distance_traveled_miles", 0
                ),
                fare_so_far=(
                    trip_data["fare_so_far"]["amount"]
                    if trip_data.get("fare_so_far")
                    else None
                ),
                eta_remaining_minutes=trip_data.get("eta_remaining_minutes"),
                actual_duration_minutes=trip_data.get(
                    "actual_duration_minutes"
                ),
                actual_distance_miles=trip_data.get("actual_distance_miles"),
                final_fare=(
                    trip_data["final_fare"]["amount"]
                    if trip_data.get("final_fare")
                    else None
                ),
            ),
            driver=_parse_driver(data.get("driver")),
            cancellation=cancellation,
        )

    def cancel_fee(self, ride_id: str) -> CancelFeeResult:
        try:
            resp = self._http.get(
                f"/v1/rides/{ride_id}/cancel-fee",
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise ConnectionError(f"Could not connect to Uber API: {e}")

        if resp.status_code != 200:
            self._raise_for_error(resp)

        data = resp.json()
        fee_data = data["fee"]

        if isinstance(fee_data, dict) and "base" in fee_data:
            fee = CancelFee(
                amount=fee_data["total"],
                base=fee_data["base"],
                metered_fare=fee_data["metered_fare"],
            )
        elif isinstance(fee_data, dict):
            fee = CancelFee(amount=fee_data.get("amount", 0))
        else:
            fee = CancelFee(amount=0)

        tc = data.get("trip_context")
        return CancelFeeResult(
            ride_id=ride_id,
            cancellable=data["cancellable"],
            fee=fee,
            reason=data["reason"],
            fare_so_far=tc["fare_so_far"] if tc else None,
            estimated_total_fare=tc["estimated_total_fare"] if tc else None,
            eta_remaining_minutes=(
                tc["eta_remaining_minutes"] if tc else None
            ),
            distance_remaining_miles=(
                tc["distance_remaining_miles"] if tc else None
            ),
        )

    def cancel(self, ride_id: str) -> CancelResult:
        try:
            resp = self._http.post(
                f"/v1/rides/{ride_id}/cancel",
                json={},
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise ConnectionError(f"Could not connect to Uber API: {e}")

        if resp.status_code != 200:
            self._raise_for_error(resp)

        data = resp.json()
        fee_data = data["fee"]

        if isinstance(fee_data, dict) and "base" in fee_data:
            fee = CancelFee(
                amount=fee_data["total"],
                base=fee_data["base"],
                metered_fare=fee_data["metered_fare"],
            )
        elif isinstance(fee_data, dict):
            fee = CancelFee(amount=fee_data.get("amount", 0))
        else:
            fee = CancelFee(amount=0)

        return CancelResult(
            ride_id=data["ride_id"],
            fee=fee,
            refund=data["refund"]["amount"],
            refund_currency=data["refund"].get("currency", "USD"),
            driver_instruction=data.get("driver_instruction"),
            canceled_at=data.get("canceled_at", ""),
        )


# Parsing helpers (Uber JSON -> adapter dataclasses)


def _parse_location(data: dict) -> Location:
    return Location(
        address=data["address"],
        lat=data["lat"],
        lng=data["lng"],
    )


def _parse_surge(data: dict) -> Surge:
    return Surge(
        multiplier=data.get("multiplier", 1.0),
        is_surging=data.get("is_surging", False),
    )


def _parse_option(data: dict) -> RideOption:
    return RideOption(
        car_type_id=data["car_type_id"],
        name=data["name"],
        description=data["description"],
        capacity=data["capacity"],
        price_range=PriceRange(
            min=data["price_range"]["min"],
            max=data["price_range"]["max"],
            currency=data["price_range"].get("currency", "USD"),
        ),
        surge=_parse_surge(data["surge"]),
        pickup_eta_minutes=data["pickup_eta_minutes"],
        trip_duration_minutes=data["trip_duration_minutes"],
        trip_distance_miles=data["trip_distance_miles"],
    )


def _parse_driver(data: dict | None) -> Driver | None:
    if not data:
        return None
    v = data["vehicle"]
    return Driver(
        name=data["name"],
        rating=data["rating"],
        phone=data.get("phone", ""),
        vehicle=Vehicle(
            make=v["make"],
            model=v["model"],
            year=v["year"],
            color=v["color"],
            license_plate=v["license_plate"],
        ),
    )
