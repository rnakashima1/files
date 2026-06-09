"""Quick smoke test of the planning logic with mock events & a stubbed Routes
API (no network/credentials needed). Run: python3 tests_smoke.py"""
from datetime import datetime, timedelta, timezone
from unittest import mock

import config
from sources.event_model import Event
from planner.timeline import build_timeline, render_timeline, render_plan
from planner.driving_plan import build_driving_plan, summarize_conflicts

TZ = timezone(timedelta(hours=-7))
D = lambda h, m=0: datetime(2026, 6, 8, h, m, tzinfo=TZ)

config.HOME_ADDRESS = "1 Family Way, Hometown"
config.DRIVERS = ["Komaki", "Ryan"]
config.NON_DRIVERS = ["Oto", "Lara", "Sanjo"]

events = [
    Event("teamsnap", "Sanjo", "Sanjo's Fury: Game vs Hawks", D(9), D(11), "Riverside Park Field 3"),
    Event("google_calendar", "Lara", "Piano lesson", D(10), D(11), "Bright Notes Studio"),
    Event("google_calendar", "Oto", "Robotics club", D(15, 30), D(17), "Lincoln Middle School"),
    Event("outlook", "Komaki", "Client meeting", D(9, 30), D(12), "Downtown Office Tower"),
    Event("google_calendar", "Ryan", "Standup", D(9), D(9, 15), "Home Office"),
]


def fake_drive_time(origin, destination, departure_time):
    return {"duration_minutes": 18.0, "distance_km": 12.3, "typical_duration_minutes": 15.0, "note": None}


with mock.patch("planner.driving_plan.get_drive_time_cached", side_effect=fake_drive_time):
    timeline = build_timeline(events)
    print(render_timeline(timeline))
    print()

    kid_events = [e for e in timeline if e.person in config.NON_DRIVERS]
    driver_cals = {d: [e for e in timeline if e.person == d] for d in config.DRIVERS}
    legs = build_driving_plan(kid_events, driver_cals)
    conflicts = summarize_conflicts(legs)
    print(render_plan(legs, conflicts, D(0)))

assert legs, "expected legs to be generated"
assert all(l.drive_minutes == 18.0 for l in legs), "stubbed drive time should propagate"
print("\nSMOKE TEST PASSED")
