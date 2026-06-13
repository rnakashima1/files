"""Turns a day's merged event timeline into a one-car driving plan.

Model
-----
Every location-based event — whether for a kid (Oto, Lara, Sanjo) or a driver
(Komaki, Ryan) — generates two legs:
  - DROPOFF: drive the person from their current location to the event,
    arriving ARRIVAL_BUFFER_MINUTES early
  - PICKUP: drive them home (or to their next event) after it ends

One physical car is shared by the whole household. Legs are walked
chronologically; the car can only do one leg at a time. Each leg is assigned to
whichever driver is free and not double-booked. A driver cannot drive themselves
(the other driver handles their legs). Legs that cannot be covered — because both
drivers are busy or the car is still on a prior trip — are marked UBER so a
human can decide whether to book a rideshare.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import config
from sources.event_model import Event
from routes.google_routes import get_drive_time_cached

FALLBACK_DRIVE_MINUTES = 20

# If a driver would spend fewer than this many minutes at home between two legs,
# assume it's not worth going home — they drive directly to the next stop instead.
# This applies to PICKUP legs: the driver goes straight from the previous drop
# location to the pickup location rather than swinging home first.
HOME_RETURN_THRESHOLD_MINUTES = 15


@dataclass
class Leg:
    kind: str            # "DROPOFF" | "PICKUP"
    rider: str           # person being driven
    event: Event
    origin: str
    destination: str
    depart_by: datetime
    arrive_by: datetime
    driver: Optional[str] = None   # None = conflict/uber
    uber: bool = False
    drive_minutes: Optional[float] = None
    distance_km: Optional[float] = None
    conflict_reason: Optional[str] = None
    # For PICKUP legs: where the car is actually coming FROM (may differ from origin).
    # The driver travels from_location → origin (pickup) → destination (home).
    from_location: Optional[str] = None
    # True when the rider is a driver going alone — they take the car themselves;
    # the car stays parked at their event until they drive home.
    self_drive: bool = False
    # Human-readable assumption attached to this leg (e.g. "stays to watch"),
    # surfaced in the email's Assumptions section.
    assumption: Optional[str] = None

    def __repr__(self):
        d = f"[UBER]" if self.uber else (f"[{self.driver}]" if self.driver else "[UNASSIGNED]")
        mins = f", ~{self.drive_minutes} min" if self.drive_minutes else ""
        return (f"{self.kind:7s} {self.rider:6s} {self.depart_by:%H:%M}->"
                f"{self.arrive_by:%H:%M} {d} | {self.origin} -> {self.destination}"
                f"{mins} | for '{self.event.title}'")


def _drive_estimate(origin, destination, depart_time):
    if origin == destination:
        return 0, 0
    result = get_drive_time_cached(origin, destination, depart_time)
    minutes = result.get("duration_minutes") or FALLBACK_DRIVE_MINUTES
    return minutes, result.get("distance_km")


def _build_legs(events: List[Event]) -> List[Leg]:
    """Build DROPOFF/PICKUP legs for every person with location-based events,
    chained through their day. Works for both kids and drivers."""
    legs = []
    by_rider = {}
    for e in events:
        by_rider.setdefault(e.person, []).append(e)

    for rider, rider_events in by_rider.items():
        rider_events = sorted(rider_events, key=lambda e: e.start)
        prev_location = config.HOME_ADDRESS or "Home"
        for i, e in enumerate(rider_events):
            buffer_ = timedelta(minutes=config.ARRIVAL_BUFFER_MINUTES)

            depart_minutes, distance_km = _drive_estimate(
                prev_location, e.location, e.start - buffer_)
            depart_by = e.start - buffer_ - timedelta(minutes=depart_minutes)
            legs.append(Leg("DROPOFF", rider, e, prev_location, e.location,
                            depart_by, e.start,
                            drive_minutes=depart_minutes, distance_km=distance_km))

            next_location = config.HOME_ADDRESS or "Home"
            if i + 1 < len(rider_events):
                next_location = rider_events[i + 1].location

            pickup_minutes, pickup_km = _drive_estimate(e.location, next_location, e.end)
            # Driver must leave home in time to ARRIVE at the pickup location by e.end.
            home_to_pickup_minutes, _ = _drive_estimate(
                config.HOME_ADDRESS, e.location, e.end)
            depart_for_pickup = e.end - timedelta(minutes=home_to_pickup_minutes)
            # arrive_by includes PICKUP_SLACK so riders can wait a few minutes
            # without the planner immediately flagging an Uber.
            pickup_slack = timedelta(minutes=config.PICKUP_SLACK_MINUTES)
            legs.append(Leg("PICKUP", rider, e, e.location, next_location,
                            depart_for_pickup,
                            e.end + timedelta(minutes=pickup_minutes) + pickup_slack,
                            drive_minutes=pickup_minutes, distance_km=pickup_km))
            prev_location = next_location

    return sorted(legs, key=lambda l: l.depart_by)


def _driver_busy(driver: str, leg: Leg, driver_calendars: dict) -> bool:
    """True if driver has a calendar commitment overlapping this leg's window."""
    for ev in driver_calendars.get(driver, []):
        if ev.start < leg.arrive_by and leg.depart_by < ev.end:
            return True
    return False


def build_driving_plan(events: List[Event], driver_calendars: dict = None,
                       all_events: List[Event] = None) -> List[Leg]:
    """Assign each leg to a driver, respecting the single-car constraint.

    - Driver appointments are included as legs (the other driver handles them).
    - A driver cannot be assigned to their own leg (can't drive yourself).
    - Legs that can't be covered are marked uber=True.
    """
    driver_calendars = driver_calendars or {}
    drivers = list(config.DRIVERS) if config.DRIVERS else ["Komaki", "Ryan"]

    # Build legs for kids AND drivers who have location-based events
    driver_location_events = [
        e for evs in driver_calendars.values() for e in evs if e.location
    ]
    all_leg_events = list(events) + driver_location_events
    legs = _build_legs(all_leg_events)

    # car_free_at: earliest moment the car is available for the next trip.
    # car_location: where the car actually is at car_free_at.
    car_free_at = None
    car_location = config.HOME_ADDRESS
    prev_leg = None
    next_driver_idx = 0

    for leg in legs:
        # Travel from car's actual current position to this leg's origin.
        travel_to_origin, _ = _drive_estimate(
            car_location, leg.origin, car_free_at or leg.depart_by)

        if car_free_at is not None:
            # Must be able to reach origin and complete the leg by arrive_by.
            # arrive_by already includes PICKUP_SLACK so this is a soft deadline.
            earliest_arrival_at_origin = car_free_at + timedelta(minutes=travel_to_origin)
            if earliest_arrival_at_origin > leg.arrive_by:
                leg.uber = True
                from zoneinfo import ZoneInfo
                _pt = car_free_at.astimezone(ZoneInfo("America/Los_Angeles"))
                _t = _pt.strftime("%-I:%M") + (" a.m." if _pt.hour < 12 else " p.m.")
                leg.conflict_reason = (
                    f"car busy until {_t} "
                    f"(on '{prev_leg.event.title}' for {prev_leg.rider})"
                )
                continue

            # DROPOFF: depart as late as possible so the rider doesn't sit waiting.
            # PICKUP: don't depart before the event ends; otherwise leave ASAP
            #         to free the car for the next leg.
            if leg.kind == "DROPOFF":
                # Total trip = car's position -> origin (get rider) -> destination.
                haul = leg.drive_minutes or FALLBACK_DRIVE_MINUTES
                latest_depart = (leg.arrive_by
                                 - timedelta(minutes=config.ARRIVAL_BUFFER_MINUTES)
                                 - timedelta(minutes=travel_to_origin + haul))
                leg.depart_by = max(car_free_at, latest_depart)
                leg.drive_minutes = travel_to_origin + haul
            else:
                # earliest we can arrive at pickup = car_free_at + travel_to_origin
                # but we also must not arrive before the event ends
                # (leg.drive_minutes stays = the ride home from the pickup)
                earliest_needed = leg.event.end - timedelta(minutes=travel_to_origin)
                leg.depart_by = max(car_free_at, earliest_needed)

        # A driver going alone to their own event drives themself — no need
        # for the other adult to chauffeur. The car stays with them.
        if leg.rider in drivers:
            assigned = leg.rider
            leg.self_drive = True
        else:
            # Try each driver in rotation; skip the rider themselves and anyone busy
            assigned = None
            for offset in range(len(drivers)):
                candidate = drivers[(next_driver_idx + offset) % len(drivers)]
                if candidate == leg.rider:
                    continue  # can't drive yourself
                if _driver_busy(candidate, leg, driver_calendars):
                    continue
                assigned = candidate
                next_driver_idx = (drivers.index(candidate) + 1) % len(drivers)
                break

        if assigned is None:
            leg.uber = True
            leg.conflict_reason = "both drivers unavailable"
        else:
            leg.driver = assigned

        # Record where the car is physically coming from for this leg.
        leg.from_location = car_location

        drive_mins = leg.drive_minutes or FALLBACK_DRIVE_MINUTES
        if leg.self_drive and leg.kind == "DROPOFF":
            # Car is parked at the driver's event until they head home.
            car_free_at = leg.event.end
        elif leg.kind == "DROPOFF":
            # Car arrives at destination and is immediately free.
            car_free_at = leg.depart_by + timedelta(minutes=drive_mins)
        else:
            # PICKUP: car drives to pickup location then to destination.
            # Actual return = depart + travel_to_pickup + drive_to_destination.
            ride_home = leg.drive_minutes or FALLBACK_DRIVE_MINUTES
            car_free_at = leg.depart_by + timedelta(minutes=travel_to_origin + ride_home)
        car_location = leg.destination
        prev_leg = leg

    return legs


def summarize_conflicts(legs: List[Leg]) -> List[str]:
    notes = []
    for leg in legs:
        if leg.uber:
            notes.append(
                f"⚠️  UBER NEEDED: {leg.rider} {leg.kind.lower()} "
                f"at {leg.depart_by:%H:%M} ({leg.origin} → {leg.destination}) "
                f"— {leg.conflict_reason}."
            )
    return notes


def collect_assumptions(legs: List[Leg]) -> List[str]:
    """Surface 'stay and watch' assumptions: cases where a parent stays at a
    child's event rather than driving home and back, because the round trip home
    would cost more than the time they'd actually get at home.

    Rule: if the time you'd spend at home (event duration minus the round trip)
    is less than the one-way drive home, it isn't worth going — assume the
    parent stays to watch and goes directly to the next stop.

    Marks the relevant PICKUP leg (leg.assumption) and returns display strings.
    """
    home = config.HOME_ADDRESS or "Home"
    dropoff_by_event = {id(l.event): l for l in legs if l.kind == "DROPOFF"}
    notes = []
    for leg in legs:
        if leg.kind != "PICKUP" or leg.uber or leg.self_drive or not leg.driver:
            continue
        # Only when the car stayed at the event (didn't go elsewhere first) and
        # the post-pickup trip is home — i.e. the real "go home or wait?" choice.
        if leg.from_location != leg.origin or leg.destination != home:
            continue
        one_way_home = leg.drive_minutes or 0          # event -> home
        if one_way_home < 5:
            continue
        duration = (leg.event.end - leg.event.start).total_seconds() / 60.0
        round_trip = 2 * one_way_home
        time_at_home = duration - round_trip
        if time_at_home >= one_way_home:
            continue  # enough time that a trip home is worth it
        drop = dropoff_by_event.get(id(leg.event))
        if not drop or not drop.driver or drop.uber:
            continue  # need a coherent drop-off driver for someone to stay
        # The parent who dropped off also does the pick-up — they stayed to watch
        # rather than driving home and back, so keep the same driver for both.
        leg.driver = drop.driver
        dur, rt = int(round(duration)), int(round(round_trip))
        if duration <= round_trip:
            why = (f"the event runs ~{dur} min but driving home and back is "
                   f"~{rt} min")
        else:
            why = (f"driving home and back (~{rt} min) would leave only "
                   f"~{int(round(time_at_home))} min at home")
        leg.assumption = f"{leg.driver} stays to watch"
        notes.append(
            f"{leg.driver} stays at {leg.origin} to watch {leg.rider}'s "
            f"“{leg.event.title}” instead of driving home — {why}."
        )
    return notes
