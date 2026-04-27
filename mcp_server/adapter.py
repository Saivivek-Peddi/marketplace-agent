"""Abstract adapter interface for ride-hailing platforms.

Defines platform-agnostic data types and the RideAdapter ABC.
To add a new platform (Lyft, Zocdoc, etc.), implement RideAdapter
and swap it in via config — no MCP tool changes needed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


# Return types (platform-agnostic)


@dataclass
class Location:
    address: str
    lat: float
    lng: float


@dataclass
class PriceRange:
    min: float
    max: float
    currency: str = "USD"


@dataclass
class Surge:
    multiplier: float
    is_surging: bool


@dataclass
class RideOption:
    car_type_id: str
    name: str
    description: str
    capacity: int
    price_range: PriceRange
    surge: Surge
    pickup_eta_minutes: int
    trip_duration_minutes: int
    trip_distance_miles: float


@dataclass
class SearchResult:
    estimate_id: str
    pickup: Location
    dropoff: Location
    options: list[RideOption]


@dataclass
class QuoteResult:
    quote_id: str
    car_type_id: str
    car_type_name: str
    pickup: Location
    dropoff: Location
    price: float
    currency: str
    surge: Surge
    pickup_eta_minutes: int
    trip_duration_minutes: int
    trip_distance_miles: float
    expires_at: str


@dataclass
class Vehicle:
    make: str
    model: str
    year: int
    color: str
    license_plate: str


@dataclass
class Driver:
    name: str
    rating: float
    phone: str
    vehicle: Vehicle


@dataclass
class BookResult:
    ride_id: str
    status: str
    car_type_name: str
    price: float
    currency: str
    pickup_address: str
    dropoff_address: str
    driver: Driver | None = None


@dataclass
class TripProgress:
    estimated_duration_minutes: int
    estimated_distance_miles: float
    elapsed_minutes: float = 0
    distance_traveled_miles: float = 0.0
    fare_so_far: float | None = None
    eta_remaining_minutes: float | None = None
    actual_duration_minutes: float | None = None
    actual_distance_miles: float | None = None
    final_fare: float | None = None


@dataclass
class CancellationInfo:
    fee: float
    reason: str
    canceled_at: str


@dataclass
class StatusResult:
    ride_id: str
    status: str
    status_description: str
    car_type_name: str
    price: float
    currency: str
    surge: Surge
    pickup_address: str
    dropoff_address: str
    trip: TripProgress
    pickup_eta_minutes: int | None = None
    pickup_arrived_at: str | None = None
    dropoff_eta_minutes: int | None = None
    dropoff_arrived_at: str | None = None
    driver: Driver | None = None
    cancellation: CancellationInfo | None = None


@dataclass
class CancelFee:
    amount: float
    base: float | None = None
    metered_fare: float | None = None

    @property
    def is_detailed(self) -> bool:
        return self.base is not None


@dataclass
class CancelFeeResult:
    ride_id: str
    cancellable: bool
    fee: CancelFee
    reason: str
    fare_so_far: float | None = None
    estimated_total_fare: float | None = None
    eta_remaining_minutes: float | None = None
    distance_remaining_miles: float | None = None


@dataclass
class CancelResult:
    ride_id: str
    fee: CancelFee
    refund: float
    refund_currency: str
    driver_instruction: str | None = None
    canceled_at: str = ""


# Errors

class AdapterError(Exception):
    """Raised when the platform API returns an error."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ConnectionError(Exception):
    """Raised when the platform API is unreachable."""
    pass


#  Abstract adapter


class RideAdapter(ABC):
    """Platform-agnostic interface for ride-hailing services.

    Implement this for each platform (Uber, Lyft, etc.).
    The MCP tools call only these methods — never the platform API directly.
    """

    @abstractmethod
    def search(self, pickup: str, dropoff: str) -> SearchResult:
        """Search for available ride options between two addresses."""
        pass

    @abstractmethod
    def quote(self, estimate_id: str, car_type_id: str) -> QuoteResult:
        """Lock in an exact price for a specific ride option."""
        pass

    @abstractmethod
    def book(self, quote_id: str) -> BookResult:
        """Book a ride using a valid quote."""
        pass

    @abstractmethod
    def status(self, ride_id: str) -> StatusResult:
        """Get the current status of a ride."""
        pass

    @abstractmethod
    def cancel_fee(self, ride_id: str) -> CancelFeeResult:
        """Check the cancellation fee before cancelling."""
        pass

    @abstractmethod
    def cancel(self, ride_id: str) -> CancelResult:
        """Execute the cancellation of a ride."""
        pass
