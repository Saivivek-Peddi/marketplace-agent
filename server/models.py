from __future__ import annotations

import enum
from datetime import datetime
from pydantic import BaseModel


# Enums #

# Ride status

class RideStatus(str, enum.Enum):
    PROCESSING = "processing"
    MATCHED = "matched"
    ARRIVING = "arriving"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELED = "canceled"
    NO_DRIVERS = "no_drivers"


# State machine for the API

VALID_TRANSITIONS: dict[RideStatus, list[RideStatus]] = {
    RideStatus.PROCESSING: [RideStatus.MATCHED, RideStatus.NO_DRIVERS, RideStatus.CANCELED],
    RideStatus.MATCHED: [RideStatus.ARRIVING, RideStatus.CANCELED, RideStatus.PROCESSING],
    RideStatus.ARRIVING: [RideStatus.IN_PROGRESS, RideStatus.CANCELED],
    RideStatus.IN_PROGRESS: [RideStatus.COMPLETED, RideStatus.CANCELED],
    RideStatus.COMPLETED: [],
    RideStatus.CANCELED: [],
    RideStatus.NO_DRIVERS: [],
}

TERMINAL_STATUSES = {RideStatus.COMPLETED, RideStatus.CANCELED, RideStatus.NO_DRIVERS}


# Error codes mock API


class ErrorCode(str, enum.Enum):

    # Estimates
    BAD_PICKUP_ADDRESS = "BAD_PICKUP_ADDRESS"
    BAD_DROPOFF_ADDRESS = "BAD_DROPOFF_ADDRESS"
    SAME_ADDRESS = "SAME_ADDRESS"
    OUTSIDE_SERVICE_AREA = "OUTSIDE_SERVICE_AREA"
    NO_ROUTE = "NO_ROUTE"
    NO_CAR_TYPES = "NO_CAR_TYPES"

    # Quotes
    ESTIMATE_NOT_FOUND = "ESTIMATE_NOT_FOUND"
    ESTIMATE_EXPIRED = "ESTIMATE_EXPIRED"
    INVALID_CAR_TYPE = "INVALID_CAR_TYPE"

    # Rides
    QUOTE_EXPIRED = "QUOTE_EXPIRED"
    DUPLICATE_RIDE = "DUPLICATE_RIDE"
    NO_DRIVERS = "NO_DRIVERS"

    # Cancel
    RIDE_NOT_FOUND = "RIDE_NOT_FOUND"
    ALREADY_CANCELED = "ALREADY_CANCELED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    NOT_CANCELLABLE = "NOT_CANCELLABLE"


# Shared sub-models


class Location(BaseModel):
    address: str
    lat: float
    lng: float


class Money(BaseModel):
    amount: float
    currency: str = "USD"


class Surge(BaseModel):
    multiplier: float = 1.0
    is_surging: bool = False


class Vehicle(BaseModel):
    make: str
    model: str
    year: int
    color: str
    license_plate: str


class Driver(BaseModel):
    name: str
    rating: float
    phone: str
    vehicle: Vehicle
    location: Location


# Estimates for the ride


class EstimateRequest(BaseModel):
    pickup: str
    dropoff: str


class PriceRange(BaseModel):
    min: float
    max: float
    currency: str = "USD"


class RideOption(BaseModel):
    car_type_id: str
    name: str
    description: str
    capacity: int
    price_range: PriceRange
    surge: Surge
    pickup_eta_minutes: int
    trip_duration_minutes: int
    trip_distance_miles: float


class EstimateResponse(BaseModel):
    estimate_id: str
    created_at: datetime
    expires_at: datetime
    pickup: Location
    dropoff: Location
    options: list[RideOption]


# Quotes for the ride (request and response)


class QuoteRequest(BaseModel):
    estimate_id: str
    car_type_id: str


class QuoteResponse(BaseModel):
    quote_id: str
    estimate_id: str
    car_type_id: str
    car_type_name: str
    pickup: Location
    dropoff: Location
    price: Money
    surge: Surge
    pickup_eta_minutes: int
    trip_duration_minutes: int
    trip_distance_miles: float
    created_at: datetime
    expires_at: datetime


# Ride details


class RideRequest(BaseModel):
    quote_id: str


class CarType(BaseModel):
    id: str
    name: str


class PickupInfo(BaseModel):
    address: str
    lat: float
    lng: float
    eta_minutes: int | None = None
    arrived_at: datetime | None = None


class DropoffInfo(BaseModel):
    address: str
    lat: float
    lng: float
    eta_minutes: int | None = None
    arrived_at: datetime | None = None


class TripInfo(BaseModel):
    estimated_duration_minutes: int
    estimated_distance_miles: float
    elapsed_minutes: float = 0
    distance_traveled_miles: float = 0.0
    fare_so_far: Money | None = None
    eta_remaining_minutes: float | None = None
    actual_duration_minutes: float | None = None
    actual_distance_miles: float | None = None
    final_fare: Money | None = None


class CancellationInfo(BaseModel):
    fee: Money
    reason: str
    canceled_at: datetime


class RideResponse(BaseModel):
    ride_id: str
    status: RideStatus
    status_description: str
    car_type: CarType
    price: Money
    surge: Surge
    pickup: PickupInfo
    dropoff: DropoffInfo
    trip: TripInfo
    driver: Driver | None = None
    cancellation: CancellationInfo | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


# Cancellatinons


class CancelFeeSimple(BaseModel):
    amount: float
    currency: str = "USD"


class CancelFeeDetailed(BaseModel):
    base: float
    metered_fare: float
    total: float
    currency: str = "USD"


class TripContext(BaseModel):
    fare_so_far: float
    estimated_total_fare: float
    eta_remaining_minutes: float
    distance_remaining_miles: float


class CancelFeeResponse(BaseModel):
    ride_id: str
    cancellable: bool
    fee: CancelFeeSimple | CancelFeeDetailed | None = None
    reason: str
    trip_context: TripContext | None = None


class CancelResponse(BaseModel):
    ride_id: str
    canceled: bool = True
    fee: CancelFeeSimple | CancelFeeDetailed
    refund: Money
    driver_instruction: str | None = None
    canceled_at: datetime


# Error

class ErrorResponse(BaseModel):
    error: str
    message: str
