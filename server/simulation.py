"""Simulation engine for the mock Uber API.

Handles geocoding, surge pricing, driver generation, ride state
transitions, fare interpolation, and scenario control.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field

from .models import (
    Driver,
    Location,
    PriceRange,
    RideOption,
    RideStatus,
    Surge,
    TERMINAL_STATUSES,
    VALID_TRANSITIONS,
    Vehicle,
)


# Known addresses (mock geocoding)

# Cache for geocode results to avoid repeated API calls
_geocode_cache: dict[str, Location | None] = {}


NOISE_WORDS = {
    "nearest", "closest", "nearby", "near", "around",
    "the", "a", "an", "my", "to", "from", "go", "take",
    "me", "ride", "drive", "get", "book", "find",
}


def _clean_address(raw: str) -> str:
    """Strip noise words that confuse geocoders."""
    words = raw.strip().lower().split()
    cleaned = [w for w in words if w not in NOISE_WORDS]
    return " ".join(cleaned) if cleaned else raw.strip()


def geocode(address: str) -> Location | None:
    """Resolve an address to lat/lng using OpenStreetMap Nominatim.

    Strips noise words like "nearest", "closest" etc. before geocoding.
    Results are cached in memory. Returns None if unresolvable.
    """
    cleaned = _clean_address(address)
    if not cleaned or len(cleaned) < 2:
        return None

    # Check cache
    if cleaned in _geocode_cache:
        return _geocode_cache[cleaned]

    # Call Nominatim
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="ride-agent-mock")
        result = geolocator.geocode(cleaned, timeout=5)
        if result:
            parts = result.address.split(",")
            display = ", ".join(p.strip() for p in parts[:3])
            loc = Location(
                address=display,
                lat=round(result.latitude, 4),
                lng=round(result.longitude, 4),
            )
            _geocode_cache[cleaned] = loc
            return loc
    except Exception:
        pass

    _geocode_cache[cleaned] = None
    return None


# Car Types


@dataclass
class CarTypeConfig:
    car_type_id: str
    name: str
    description: str
    capacity: int
    base_fare: float
    per_mile: float
    per_minute: float
    min_fare: float
    pickup_eta_range: tuple[int, int]  # (min, max) minutes


CAR_TYPES = [
    CarTypeConfig(
        car_type_id="uberx",
        name="UberX",
        description="Affordable rides, just for you",
        capacity=4,
        base_fare=2.50,
        per_mile=1.50,
        per_minute=0.30,
        min_fare=8.00,
        pickup_eta_range=(3, 7),
    ),
    CarTypeConfig(
        car_type_id="comfort",
        name="Uber Comfort",
        description="Newer cars with extra legroom",
        capacity=4,
        base_fare=3.50,
        per_mile=2.00,
        per_minute=0.40,
        min_fare=12.00,
        pickup_eta_range=(5, 10),
    ),
    CarTypeConfig(
        car_type_id="uberxl",
        name="UberXL",
        description="Affordable rides for groups up to 6",
        capacity=6,
        base_fare=3.00,
        per_mile=2.20,
        per_minute=0.45,
        min_fare=10.00,
        pickup_eta_range=(5, 12),
    ),
    CarTypeConfig(
        car_type_id="black",
        name="Uber Black",
        description="Premium rides in luxury cars",
        capacity=4,
        base_fare=8.00,
        per_mile=3.50,
        per_minute=0.65,
        min_fare=25.00,
        pickup_eta_range=(7, 15),
    ),
]


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Approximate distance in miles between two lat/lng points."""
    import math

    r = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


# Contiguous US bounding box (approximate)
_US_BOUNDS = {
    "lat_min": 24.5,   # southern tip of Florida Keys
    "lat_max": 49.5,   # northern border with Canada
    "lng_min": -125.0,  # west coast
    "lng_max": -66.5,   # east coast
}


class OutsideServiceAreaError(Exception):
    """Raised when pickup or dropoff is outside the USA service area."""
    pass


class NoRouteError(Exception):
    """Raised when OSRM finds no driveable path between two points."""
    pass


class RouteServiceUnavailableError(Exception):
    """Raised when the OSRM routing service is unreachable."""
    pass


def _check_service_area(location: Location, label: str) -> None:
    """Verify a location is within the contiguous US."""
    b = _US_BOUNDS
    if not (b["lat_min"] <= location.lat <= b["lat_max"]
            and b["lng_min"] <= location.lng <= b["lng_max"]):
        raise OutsideServiceAreaError(
            f"{label} ({location.address}) is outside the service area. "
            "Rides are only available within the contiguous United States."
        )


def _osrm_route(pickup: Location, dropoff: Location) -> tuple[float, int]:
    """Call OSRM public API to get real road distance and duration.

    Returns (distance_miles, duration_minutes) if a route exists.
    Raises NoRouteError if no driveable path exists.
    Raises RouteServiceUnavailableError if OSRM is unreachable.
    """
    import httpx

    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{pickup.lng},{pickup.lat};{dropoff.lng},{dropoff.lat}"
        f"?overview=false"
    )
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
    except Exception as e:
        raise RouteServiceUnavailableError(
            f"Could not reach routing service: {e}"
        )

    data = resp.json()
    if data.get("code") != "Ok":
        raise NoRouteError(
            "No driveable path exists between these locations"
        )

    route = data["routes"][0]
    distance_miles = round(route["distance"] / 1609.34, 1)  # meters → miles
    duration_minutes = max(5, round(route["duration"] / 60))  # seconds → minutes
    return distance_miles, duration_minutes


def compute_trip(pickup: Location, dropoff: Location) -> tuple[float, int]:
    """Return (distance_miles, duration_minutes) for a trip.

    Validates both locations are within the contiguous US, then uses
    OSRM for real road routing. Raises OutsideServiceAreaError if
    either location is outside the US, NoRouteError if no driveable
    path exists, or RouteServiceUnavailableError if OSRM is unreachable.
    """
    _check_service_area(pickup, "Pickup")
    _check_service_area(dropoff, "Dropoff")
    return _osrm_route(pickup, dropoff)


def compute_price_range(car_type: CarTypeConfig, distance: float, duration: int, surge: float) -> PriceRange:
    """Compute min/max price for a car type given trip details and surge."""
    base = car_type.base_fare + (car_type.per_mile * distance) + (car_type.per_minute * duration)
    base = max(base, car_type.min_fare)
    surged = base * surge
    # ±15% range
    return PriceRange(
        min=round(surged * 0.85, 2),
        max=round(surged * 1.15, 2),
    )


def compute_exact_price(car_type: CarTypeConfig, distance: float, duration: int, surge: float) -> float:
    """Compute exact locked-in price for a quote."""
    base = car_type.base_fare + (car_type.per_mile * distance) + (car_type.per_minute * duration)
    base = max(base, car_type.min_fare)
    return round(base * surge, 2)


def get_car_type(car_type_id: str) -> CarTypeConfig | None:
    for p in CAR_TYPES:
        if p.car_type_id == car_type_id:
            return p
    return None


#  Surge


def get_surge(scenarios: set[str]) -> Surge:
    """Get current surge based on scenario flags."""
    if "surge" in scenarios:
        return Surge(multiplier=2.5, is_surging=True)
    # Default: slight random variation
    mult = round(random.uniform(0.9, 1.3), 1)
    return Surge(multiplier=mult, is_surging=mult > 1.0)


#  Driver generation (hard coded for now)


DRIVER_NAMES = ["DJ", "Mark", "James", "Akash", "Aisha", "Wei", "Sofia"]
VEHICLE_POOL = [
    Vehicle(make="Toyota", model="Camry", year=2023, color="Silver", license_plate="7ABC123"),
    Vehicle(make="Honda", model="Civic", year=2024, color="Black", license_plate="8XYZ456"),
    Vehicle(make="Tesla", model="Model 3", year=2024, color="White", license_plate="9EV0789"),
    Vehicle(make="Hyundai", model="Sonata", year=2023, color="Blue", license_plate="3KLM012"),
    Vehicle(make="BMW", model="5 Series", year=2024, color="Black", license_plate="5LUX345"),
    Vehicle(make="Mercedes", model="E-Class", year=2024, color="Black", license_plate="6PRE678"),
]


def generate_driver(pickup: Location) -> Driver:
    """Generate a random driver near the pickup location."""
    name = random.choice(DRIVER_NAMES)
    vehicle = random.choice(VEHICLE_POOL)
    # Driver is nearby — small offset from pickup
    lat_offset = random.uniform(-0.01, 0.01)
    lng_offset = random.uniform(-0.01, 0.01)
    return Driver(
        name=name,
        rating=round(random.uniform(4.7, 5.0), 2),
        phone=f"+1555{random.randint(1000000, 9999999)}",
        vehicle=vehicle,
        location=Location(
            address="",
            lat=round(pickup.lat + lat_offset, 4),
            lng=round(pickup.lng + lng_offset, 4),
        ),
    )


# Ride state machine


@dataclass
class RideState:
    ride_id: str
    status: RideStatus
    car_type_id: str
    car_type_name: str
    price_amount: float
    surge_multiplier: float
    surge_is_surging: bool
    pickup: Location
    dropoff: Location
    estimated_duration_minutes: int
    estimated_distance_miles: float
    driver: Driver | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    matched_at: datetime | None = None
    arriving_at: datetime | None = None
    trip_started_at: datetime | None = None
    completed_at: datetime | None = None
    canceled_at: datetime | None = None
    cancel_fee: float = 0.0
    cancel_fee_detail: dict | None = None
    pickup_eta_minutes: int = 5

    def transition(self, new_status: RideStatus) -> None:
        if new_status not in VALID_TRANSITIONS[self.status]:
            raise InvalidTransition(
                f"Cannot go from {self.status.value} to {new_status.value}"
            )
        now = datetime.now(timezone.utc)
        self.status = new_status
        self.updated_at = now

        if new_status == RideStatus.MATCHED:
            self.matched_at = now
        elif new_status == RideStatus.ARRIVING:
            self.arriving_at = now
        elif new_status == RideStatus.IN_PROGRESS:
            self.trip_started_at = now
        elif new_status == RideStatus.COMPLETED:
            self.completed_at = now
        elif new_status == RideStatus.CANCELED:
            self.canceled_at = now

    def trip_progress(self) -> float:
        """Return 0.0-1.0 progress through the trip. Only meaningful when in_progress."""
        if self.status != RideStatus.IN_PROGRESS or self.trip_started_at is None:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - self.trip_started_at).total_seconds()
        total = self.estimated_duration_minutes * 60
        if total == 0:
            return 1.0
        return min(elapsed / total, 1.0)

    def fare_so_far(self) -> float:
        """Linear interpolation of fare based on trip progress."""
        return round(self.price_amount * self.trip_progress(), 2)

    def elapsed_minutes(self) -> float:
        if self.trip_started_at is None:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - self.trip_started_at).total_seconds()
        return round(elapsed / 60, 1)

    def eta_remaining_minutes(self) -> float:
        return round(self.estimated_duration_minutes - self.elapsed_minutes(), 1)

    def distance_traveled(self) -> float:
        return round(self.estimated_distance_miles * self.trip_progress(), 1)

    def distance_remaining(self) -> float:
        return round(self.estimated_distance_miles - self.distance_traveled(), 1)

    def cancel_fee_amount(self) -> tuple[float, str, dict | None]:
        """Return (fee, reason, detail_dict_or_none) based on current status."""
        if self.status == RideStatus.PROCESSING:
            return 0.0, "Free cancellation — driver hasn't been dispatched yet", None

        if self.status == RideStatus.MATCHED:
            if self.matched_at is not None:
                elapsed = (datetime.now(timezone.utc) - self.matched_at).total_seconds()
                if elapsed < 120:
                    return 0.0, "Free cancellation — within 2 minute window", None
            return 5.0, "Driver already dispatched. Cancellation fee applies.", None

        if self.status == RideStatus.ARRIVING:
            return 5.0, "Driver is arriving. Cancellation fee applies.", None

        if self.status == RideStatus.IN_PROGRESS:
            metered = self.fare_so_far()
            base = 10.0
            total = round(base + metered, 2)
            detail = {
                "base": base,
                "metered_fare": metered,
                "total": total,
            }
            reason = (
                "Ride is in progress. You will be charged the base cancellation "
                "fee plus fare accrued so far."
            )
            return total, reason, detail

        return 0.0, "No fee applicable", None


class InvalidTransition(Exception):
    pass


# Estimate, Quote storage


@dataclass
class EstimateRecord:
    estimate_id: str
    pickup: Location
    dropoff: Location
    distance_miles: float
    duration_minutes: int
    surge: Surge
    options: list[RideOption]
    created_at: datetime
    expires_at: datetime


@dataclass
class QuoteRecord:
    quote_id: str
    estimate_id: str
    car_type_id: str
    car_type_name: str
    pickup: Location
    dropoff: Location
    price: float
    surge: Surge
    pickup_eta_minutes: int
    trip_duration_minutes: int
    trip_distance_miles: float
    created_at: datetime
    expires_at: datetime


# In-memory store save the ride lifecycle, we would replace this with redis cache in prod


class Store:
    """In-memory storage for estimates, quotes, and rides."""

    def __init__(self) -> None:
        self.estimates: dict[str, EstimateRecord] = {}
        self.quotes: dict[str, QuoteRecord] = {}
        self.rides: dict[str, RideState] = {}
        self.lock = asyncio.Lock()

    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def active_ride(self) -> RideState | None:
        """Return the current active (non-terminal) ride, if any."""
        for ride in self.rides.values():
            if ride.status not in TERMINAL_STATUSES:
                return ride
        return None


# Scenario parsing


def parse_scenarios(header: str | None) -> set[str]:
    if not header:
        return set()
    return {s.strip().lower() for s in header.split(",")}
