"""Mock Uber API server — 6 endpoints.

API Contract
============

Base URL: http://localhost:8000
Content-Type: application/json
Versioning: /v1 prefix on all routes
Auth: None (mock server)
Scenario Control: X-Scenario header (surge, no-drivers, driver-cancels, quote-expire, slow)

Endpoints
---------
  Method  Path                          Status  Description
  ------  ----------------------------  ------  -----------
  POST    /v1/estimates                 200     Search rides between two addresses.
  POST    /v1/quotes                    200     Lock exact price for a car type. TTL: 120s (5s in quote-expire).
  POST    /v1/rides                     201     Book a ride from a valid quote. Starts async state progression.
  GET     /v1/rides/{ride_id}           200     Current ride state, driver info, live fare, trip progress.
  GET     /v1/rides/{ride_id}/cancel-fee 200    Get cancellation cost before committing.
  POST    /v1/rides/{ride_id}/cancel    200     Execute cancellation. Fee depends on ride state.

Flow: Estimate → Quote → Ride (three-phase commit)
  1. POST /estimates  → browse options (price ranges, ETAs)
  2. POST /quotes     → lock exact price (2 min TTL)
  3. POST /rides      → book with locked quote

Ride State Machine:
  processing → matched → arriving → in_progress → completed
  Any active state → canceled (fee varies by state)
  processing → no_drivers (timeout, terminal)

Error Format:
  All errors return: {"detail": {"error": "<ERROR_CODE>", "message": "<human readable>"}}
  HTTP status codes: 400 (bad input), 404 (not found), 409 (conflict), 410 (expired), 503 (unavailable)

Route Validation:
  Service area: contiguous United States only. Both pickup and dropoff must be
  within the US bounding box (lat 24.5-49.5, lng -125 to -66.5).
  Routes are validated against OSRM (Open Source Routing Machine) to ensure
  a driveable path exists. If OSRM is unreachable, the request fails (no fallback).

Error Codes:
  Estimates:  BAD_PICKUP_ADDRESS, BAD_DROPOFF_ADDRESS, SAME_ADDRESS,
              OUTSIDE_SERVICE_AREA, NO_ROUTE, ROUTE_SERVICE_UNAVAILABLE,
              NO_CAR_TYPES
  Quotes:     ESTIMATE_NOT_FOUND, ESTIMATE_EXPIRED, INVALID_CAR_TYPE
  Rides:      QUOTE_EXPIRED, DUPLICATE_RIDE, NO_DRIVERS
  Cancel:     RIDE_NOT_FOUND, ALREADY_CANCELED, ALREADY_COMPLETED, NOT_CANCELLABLE

Cancel Fee Schedule:
  processing          → $0
  matched (< 2 min)   → $0
  matched (>= 2 min)  → $5
  arriving             → $5
  in_progress          → $10 + fare accrued so far
  completed/canceled   → not cancellable (error)

Models: See server/models.py for all Pydantic request/response schemas.
Simulation: See server/simulation.py for geocoding, pricing, drivers, state machine.
Auto-generated docs: http://localhost:8000/docs (Swagger UI)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException

from .models import (
    CancelFeeDetailed,
    CancelFeeResponse,
    CancelFeeSimple,
    CancelResponse,
    CancellationInfo,
    DropoffInfo,
    ErrorResponse,
    EstimateRequest,
    EstimateResponse,
    Money,
    PickupInfo,
    CarType,
    QuoteRequest,
    QuoteResponse,
    RideOption,
    RideRequest,
    RideResponse,
    RideStatus,
    Surge,
    TripContext,
    TripInfo,
)
from .models import TERMINAL_STATUSES
from .simulation import (
    EstimateRecord,
    NoRouteError,
    OutsideServiceAreaError,
    QuoteRecord,
    RideState,
    RouteServiceUnavailableError,
    Store,
    compute_exact_price,
    compute_price_range,
    compute_trip,
    generate_driver,
    geocode,
    get_car_type,
    get_surge,
    parse_scenarios,
    CAR_TYPES,
)

from contextlib import asynccontextmanager

_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Graceful shutdown: cancel background tasks
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()


app = FastAPI(title="Mock Uber API", version="0.1.0", lifespan=lifespan)
store = Store()

ESTIMATE_TTL_SECONDS = 600  # 10 minutes
QUOTE_TTL_SECONDS = 120  # 2 minutes
DRIVER_MATCH_DELAY = (5, 10)  # seconds


@app.get("/health")
async def health():
    """Health check endpoint."""
    active = [r for r in store.rides.values() if r.status not in TERMINAL_STATUSES]
    return {
        "status": "ok",
        "active_rides": len(active),
        "estimates": len(store.estimates),
        "quotes": len(store.quotes),
        "background_tasks": len(_background_tasks),
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


# POST /v1/estimates


@app.post("/v1/estimates", response_model=EstimateResponse)
async def create_estimate(
    req: EstimateRequest,
    x_scenario: str | None = Header(None),
):
    scenarios = parse_scenarios(x_scenario)

    if "slow" in scenarios:
        await asyncio.sleep(2.5)

    # Geocode (run in thread — Nominatim is blocking I/O)
    pickup = await asyncio.to_thread(geocode, req.pickup)
    if pickup is None:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="BAD_PICKUP_ADDRESS",
                message=f"Could not resolve address: '{req.pickup}'",
            ).model_dump(),
        )

    dropoff = await asyncio.to_thread(geocode, req.dropoff)
    if dropoff is None:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="BAD_DROPOFF_ADDRESS",
                message=f"Could not resolve address: '{req.dropoff}'",
            ).model_dump(),
        )

    # Same address check
    if pickup.lat == dropoff.lat and pickup.lng == dropoff.lng:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="SAME_ADDRESS",
                message="Pickup and dropoff resolve to the same location",
            ).model_dump(),
        )

    # Compute trip (validates service area + route is driveable via OSRM)
    try:
        distance, duration = compute_trip(pickup, dropoff)
    except OutsideServiceAreaError as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="OUTSIDE_SERVICE_AREA",
                message=str(e),
            ).model_dump(),
        )
    except NoRouteError:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="NO_ROUTE",
                message=(
                    "No driveable path exists between these locations. "
                    "The route may cross an ocean or require roads that "
                    "don't exist."
                ),
            ).model_dump(),
        )
    except RouteServiceUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse(
                error="ROUTE_SERVICE_UNAVAILABLE",
                message=(
                    "Unable to verify whether a driveable path exists "
                    f"between these locations. {e}"
                ),
            ).model_dump(),
        )
    surge = get_surge(scenarios)

    # Build options
    import random

    options: list[RideOption] = []
    for ct in CAR_TYPES:
        price_range = compute_price_range(ct, distance, duration, surge.multiplier)
        eta = random.randint(*ct.pickup_eta_range)
        options.append(
            RideOption(
                car_type_id=ct.car_type_id,
                name=ct.name,
                description=ct.description,
                capacity=ct.capacity,
                price_range=price_range,
                surge=surge,
                pickup_eta_minutes=eta,
                trip_duration_minutes=duration,
                trip_distance_miles=distance,
            )
        )

    if not options:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse(
                error="NO_CAR_TYPES",
                message="No ride options available at this location right now",
            ).model_dump(),
        )

    now = _now()
    estimate_id = store.new_id("est")
    record = EstimateRecord(
        estimate_id=estimate_id,
        pickup=pickup,
        dropoff=dropoff,
        distance_miles=distance,
        duration_minutes=duration,
        surge=surge,
        options=options,
        created_at=now,
        expires_at=now + timedelta(seconds=ESTIMATE_TTL_SECONDS),
    )
    store.estimates[estimate_id] = record

    return EstimateResponse(
        estimate_id=estimate_id,
        created_at=record.created_at,
        expires_at=record.expires_at,
        pickup=pickup,
        dropoff=dropoff,
        options=options,
    )


# POST /v1/quotes


@app.post("/v1/quotes", response_model=QuoteResponse)
async def create_quote(
    req: QuoteRequest,
    x_scenario: str | None = Header(None),
):
    scenarios = parse_scenarios(x_scenario)

    if "slow" in scenarios:
        await asyncio.sleep(2.5)

    # Find estimate
    record = store.estimates.get(req.estimate_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="ESTIMATE_NOT_FOUND",
                message=f"No estimate found with id '{req.estimate_id}'",
            ).model_dump(),
        )

    # Check expiry
    if _now() > record.expires_at:
        raise HTTPException(
            status_code=410,
            detail=ErrorResponse(
                error="ESTIMATE_EXPIRED",
                message=f"Estimate expired at {record.expires_at.isoformat()}, request a new one",
            ).model_dump(),
        )

    # Find car type
    car_type = get_car_type(req.car_type_id)
    if car_type is None:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="INVALID_CAR_TYPE",
                message=f"Car type '{req.car_type_id}' not available for this estimate",
            ).model_dump(),
        )

    # Check car type was in estimate options
    valid_ids = {o.car_type_id for o in record.options}
    if req.car_type_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="INVALID_CAR_TYPE",
                message=f"Car type '{req.car_type_id}' not available for this estimate",
            ).model_dump(),
        )

    # Compute exact price — surge may have shifted slightly
    surge = get_surge(scenarios)
    exact_price = compute_exact_price(
        car_type, record.distance_miles, record.duration_minutes, surge.multiplier
    )

    now = _now()
    ttl = 5 if "quote-expire" in scenarios else QUOTE_TTL_SECONDS
    quote_id = store.new_id("qt")

    # Find pickup ETA from the estimate option
    eta = 5
    for opt in record.options:
        if opt.car_type_id == req.car_type_id:
            eta = opt.pickup_eta_minutes
            break

    quote = QuoteRecord(
        quote_id=quote_id,
        estimate_id=req.estimate_id,
        car_type_id=car_type.car_type_id,
        car_type_name=car_type.name,
        pickup=record.pickup,
        dropoff=record.dropoff,
        price=exact_price,
        surge=surge,
        pickup_eta_minutes=eta,
        trip_duration_minutes=record.duration_minutes,
        trip_distance_miles=record.distance_miles,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    store.quotes[quote_id] = quote

    return QuoteResponse(
        quote_id=quote_id,
        estimate_id=req.estimate_id,
        car_type_id=car_type.car_type_id,
        car_type_name=car_type.name,
        pickup=record.pickup,
        dropoff=record.dropoff,
        price=Money(amount=exact_price),
        surge=surge,
        pickup_eta_minutes=eta,
        trip_duration_minutes=record.duration_minutes,
        trip_distance_miles=record.distance_miles,
        created_at=quote.created_at,
        expires_at=quote.expires_at,
    )


# POST /v1/rides


@app.post("/v1/rides", response_model=RideResponse, status_code=201)
async def create_ride(
    req: RideRequest,
    x_scenario: str | None = Header(None),
):
    scenarios = parse_scenarios(x_scenario)

    if "slow" in scenarios:
        await asyncio.sleep(2.5)

    # Find quote
    quote = store.quotes.get(req.quote_id)
    if quote is None:
        raise HTTPException(
            status_code=410,
            detail=ErrorResponse(
                error="QUOTE_EXPIRED",
                message="Quote not found or expired. Request a new quote.",
            ).model_dump(),
        )

    # Check quote expiry
    if _now() > quote.expires_at:
        raise HTTPException(
            status_code=410,
            detail=ErrorResponse(
                error="QUOTE_EXPIRED",
                message=(
                    f"Quote expired "
                    f"{int((_now() - quote.expires_at).total_seconds())}s ago. "
                    "Request a new quote to get current pricing."
                ),
            ).model_dump(),
        )

    # Check duplicate ride
    active = store.active_ride()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error="DUPLICATE_RIDE",
                message=f"Active ride '{active.ride_id}' already exists. Cancel it first or wait for completion.",
            ).model_dump(),
        )

    # No drivers scenario
    if "no-drivers" in scenarios:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse(
                error="NO_DRIVERS",
                message="No drivers available right now. Try again in a few minutes.",
            ).model_dump(),
        )

    # Create ride
    ride_id = store.new_id("ride")
    ride = RideState(
        ride_id=ride_id,
        status=RideStatus.PROCESSING,
        car_type_id=quote.car_type_id,
        car_type_name=quote.car_type_name,
        price_amount=quote.price,
        surge_multiplier=quote.surge.multiplier,
        surge_is_surging=quote.surge.is_surging,
        pickup=quote.pickup,
        dropoff=quote.dropoff,
        estimated_duration_minutes=quote.trip_duration_minutes,
        estimated_distance_miles=quote.trip_distance_miles,
        pickup_eta_minutes=quote.pickup_eta_minutes,
    )
    store.rides[ride_id] = ride

    # Consume the quote so it can't be reused
    del store.quotes[req.quote_id]

    # Schedule driver matching in background
    import random

    match_delay = random.uniform(*DRIVER_MATCH_DELAY)

    async def _match_driver():
        await asyncio.sleep(match_delay)
        async with store.lock:
            if ride.status == RideStatus.PROCESSING:
                ride.driver = generate_driver(ride.pickup)
                ride.transition(RideStatus.MATCHED)

        arrive_delay = ride.pickup_eta_minutes * 10  # compressed time
        await asyncio.sleep(arrive_delay)
        async with store.lock:
            if ride.status == RideStatus.MATCHED:
                ride.transition(RideStatus.ARRIVING)

        await asyncio.sleep(random.uniform(3, 8))
        async with store.lock:
            if ride.status == RideStatus.ARRIVING:
                ride.transition(RideStatus.IN_PROGRESS)

        trip_delay = ride.estimated_duration_minutes * 6  # compressed
        await asyncio.sleep(trip_delay)
        async with store.lock:
            if ride.status == RideStatus.IN_PROGRESS:
                ride.transition(RideStatus.COMPLETED)

    async def _driver_cancels():
        await asyncio.sleep(match_delay)
        async with store.lock:
            if ride.status == RideStatus.PROCESSING:
                ride.driver = generate_driver(ride.pickup)
                ride.transition(RideStatus.MATCHED)
        await asyncio.sleep(5)
        async with store.lock:
            if ride.status == RideStatus.MATCHED:
                ride.transition(RideStatus.PROCESSING)
                ride.driver = None
        await asyncio.sleep(random.uniform(*DRIVER_MATCH_DELAY))
        async with store.lock:
            if ride.status == RideStatus.PROCESSING:
                ride.driver = generate_driver(ride.pickup)
                ride.transition(RideStatus.MATCHED)

    def _track_task(coro):
        task = asyncio.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return task

    if "driver-cancels" in scenarios:
        _track_task(_driver_cancels())
    else:
        _track_task(_match_driver())

    return _build_ride_response(ride)


# GET /v1/rides/{ride_id}


@app.get("/v1/rides/{ride_id}", response_model=RideResponse)
async def get_ride(ride_id: str):
    ride = store.rides.get(ride_id)
    if ride is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="RIDE_NOT_FOUND",
                message=f"No ride found with id '{ride_id}'",
            ).model_dump(),
        )
    return _build_ride_response(ride)


# GET /v1/rides/{ride_id}/cancel-fee


@app.get("/v1/rides/{ride_id}/cancel-fee", response_model=CancelFeeResponse)
async def get_cancel_fee(ride_id: str):
    ride = store.rides.get(ride_id)
    if ride is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="RIDE_NOT_FOUND",
                message=f"No ride found with id '{ride_id}'",
            ).model_dump(),
        )

    if ride.status == RideStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="RIDE_ALREADY_COMPLETED",
                message="Ride is already completed",
            ).model_dump(),
        )

    if ride.status == RideStatus.CANCELED:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="RIDE_ALREADY_CANCELED",
                message="Ride was already canceled",
            ).model_dump(),
        )

    if ride.status == RideStatus.NO_DRIVERS:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="RIDE_ALREADY_COMPLETED",
                message="Ride ended — no drivers were found",
            ).model_dump(),
        )

    fee_amount, reason, detail = ride.cancel_fee_amount()

    if detail is not None:
        # In-progress: detailed fee + trip context
        fee_obj = CancelFeeDetailed(
            base=detail["base"],
            metered_fare=detail["metered_fare"],
            total=detail["total"],
        )
        trip_ctx = TripContext(
            fare_so_far=ride.fare_so_far(),
            estimated_total_fare=ride.price_amount,
            eta_remaining_minutes=ride.eta_remaining_minutes(),
            distance_remaining_miles=ride.distance_remaining(),
        )
        return CancelFeeResponse(
            ride_id=ride_id,
            cancellable=True,
            fee=fee_obj,
            reason=reason,
            trip_context=trip_ctx,
        )

    return CancelFeeResponse(
        ride_id=ride_id,
        cancellable=True,
        fee=CancelFeeSimple(amount=fee_amount),
        reason=reason,
    )


# POST /v1/rides/{ride_id}/cancel


@app.post("/v1/rides/{ride_id}/cancel", response_model=CancelResponse)
async def cancel_ride(ride_id: str):
    ride = store.rides.get(ride_id)
    if ride is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="RIDE_NOT_FOUND",
                message=f"No ride found with id '{ride_id}'",
            ).model_dump(),
        )

    if ride.status == RideStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="ALREADY_COMPLETED",
                message="Ride is already completed",
            ).model_dump(),
        )

    if ride.status == RideStatus.CANCELED:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="ALREADY_CANCELED",
                message=(
                    "Ride was already canceled at "
                    + (ride.canceled_at.isoformat()
                       if ride.canceled_at else "unknown")
                ),
            ).model_dump(),
        )

    if ride.status == RideStatus.NO_DRIVERS:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="ALREADY_COMPLETED",
                message="Ride already ended — no drivers were found",
            ).model_dump(),
        )

    # Calculate fee before transitioning
    fee_amount, reason, detail = ride.cancel_fee_amount()
    ride.transition(RideStatus.CANCELED)
    ride.cancel_fee = fee_amount

    refund_amount = max(0, round(ride.price_amount - fee_amount, 2))

    if detail is not None:
        fee_obj = CancelFeeDetailed(
            base=detail["base"],
            metered_fare=detail["metered_fare"],
            total=detail["total"],
        )
    else:
        fee_obj = CancelFeeSimple(amount=fee_amount)

    driver_instruction = None
    if ride.status == RideStatus.CANCELED and ride.driver is not None:
        driver_instruction = "Driver has been notified to pull over safely"

    return CancelResponse(
        ride_id=ride_id,
        fee=fee_obj,
        refund=Money(amount=refund_amount),
        driver_instruction=driver_instruction,
        canceled_at=ride.canceled_at or _now(),
    )


#  Helpers

STATUS_DESCRIPTIONS = {
    RideStatus.PROCESSING: "We're looking for a driver for you...",
    RideStatus.MATCHED: "Your driver is heading to your pickup",
    RideStatus.ARRIVING: "Your driver is arriving now",
    RideStatus.IN_PROGRESS: "You are on your way",
    RideStatus.COMPLETED: "You have arrived! Trip completed",
    RideStatus.CANCELED: "You have cancelled the ride",
    RideStatus.NO_DRIVERS: "No drivers available right now. Please try again.",
}


def _build_ride_response(ride: RideState) -> RideResponse:
    """Build a full RideResponse from internal ride state."""

    # Pickup info
    pickup = PickupInfo(
        address=ride.pickup.address,
        lat=ride.pickup.lat,
        lng=ride.pickup.lng,
    )
    if ride.status in (RideStatus.MATCHED, RideStatus.ARRIVING):
        pickup.eta_minutes = ride.pickup_eta_minutes if ride.status == RideStatus.MATCHED else 0
    if ride.arriving_at:
        pickup.arrived_at = ride.arriving_at

    # Dropoff info
    dropoff = DropoffInfo(
        address=ride.dropoff.address,
        lat=ride.dropoff.lat,
        lng=ride.dropoff.lng,
    )
    if ride.status == RideStatus.IN_PROGRESS:
        dropoff.eta_minutes = int(ride.eta_remaining_minutes())
    if ride.completed_at:
        dropoff.arrived_at = ride.completed_at

    # Trip info
    trip = TripInfo(
        estimated_duration_minutes=ride.estimated_duration_minutes,
        estimated_distance_miles=ride.estimated_distance_miles,
    )
    if ride.status == RideStatus.IN_PROGRESS:
        trip.elapsed_minutes = ride.elapsed_minutes()
        trip.distance_traveled_miles = ride.distance_traveled()
        trip.fare_so_far = Money(amount=ride.fare_so_far())
        trip.eta_remaining_minutes = ride.eta_remaining_minutes()
    elif ride.status == RideStatus.COMPLETED:
        trip.actual_duration_minutes = ride.estimated_duration_minutes
        trip.actual_distance_miles = round(ride.estimated_distance_miles * 1.02, 1)  # slight variation
        trip.final_fare = Money(amount=ride.price_amount)

    # Cancellation info
    cancellation = None
    if ride.status == RideStatus.CANCELED and ride.canceled_at:
        cancellation = CancellationInfo(
            fee=Money(amount=ride.cancel_fee),
            reason="Canceled by rider",
            canceled_at=ride.canceled_at,
        )

    # Status description
    desc = STATUS_DESCRIPTIONS.get(ride.status, "")
    if ride.status == RideStatus.IN_PROGRESS:
        desc = f"You are on your way to {ride.dropoff.address}"

    return RideResponse(
        ride_id=ride.ride_id,
        status=ride.status,
        status_description=desc,
        car_type=CarType(id=ride.car_type_id, name=ride.car_type_name),
        price=Money(amount=ride.price_amount),
        surge=Surge(multiplier=ride.surge_multiplier, is_surging=ride.surge_is_surging),
        pickup=pickup,
        dropoff=dropoff,
        trip=trip,
        driver=ride.driver,
        cancellation=cancellation,
        created_at=ride.created_at,
        updated_at=ride.updated_at,
        completed_at=ride.completed_at,
    )
