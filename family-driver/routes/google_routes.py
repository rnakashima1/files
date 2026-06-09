"""Thin client for the Google Maps Routes API (computeRoutes), used to get
traffic-aware driving time & distance between two addresses at a given
departure time.

Docs: https://developers.google.com/maps/documentation/routes
Requires: "Routes API" enabled + an API key (config.GOOGLE_MAPS_API_KEY).
"""
from datetime import datetime, timedelta
from functools import lru_cache

import requests

import config

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Only request the fields we need — Routes API requires an explicit field mask.
FIELD_MASK = "routes.duration,routes.staticDuration,routes.distanceMeters,routes.description"


def _waypoint(address: str) -> dict:
    return {"address": address}


def get_drive_time(origin: str, destination: str, departure_time: datetime) -> dict:
    """Returns {'duration_minutes': float, 'distance_km': float,
    'typical_duration_minutes': float} for driving from origin to destination,
    departing at `departure_time` (timezone-aware), using live traffic
    prediction (TRAFFIC_AWARE_OPTIMAL).

    Falls back to a (None, None) duration if the API key isn't configured —
    callers should handle that gracefully (e.g. use a flat estimate).
    """
    if not config.GOOGLE_MAPS_API_KEY:
        return {"duration_minutes": None, "distance_km": None,
                "typical_duration_minutes": None, "note": "GOOGLE_MAPS_API_KEY not set"}

    body = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
        "departureTime": departure_time.astimezone().isoformat(),
        "computeAlternativeRoutes": False,
        "languageCode": "en-US",
        "units": "METRIC",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    resp = requests.post(ROUTES_URL, json=body, headers=headers, timeout=30)
    resp.raise_for_status()
    routes = resp.json().get("routes", [])
    if not routes:
        return {"duration_minutes": None, "distance_km": None,
                "typical_duration_minutes": None, "note": "no route found"}

    route = routes[0]
    traffic_seconds = int(route["duration"].rstrip("s"))
    typical_seconds = int(route.get("staticDuration", route["duration"]).rstrip("s"))
    return {
        "duration_minutes": round(traffic_seconds / 60, 1),
        "typical_duration_minutes": round(typical_seconds / 60, 1),
        "distance_km": round(route.get("distanceMeters", 0) / 1000, 1),
        "note": None,
    }


@lru_cache(maxsize=256)
def _cached_lookup(origin, destination, departure_iso):
    return get_drive_time(origin, destination, datetime.fromisoformat(departure_iso))


def get_drive_time_cached(origin: str, destination: str, departure_time: datetime) -> dict:
    """Same as get_drive_time but memoized per (origin, destination, departure
    time rounded to 15 min). Clamps past departure times to now to avoid
    Google Routes API 400 errors."""
    now = datetime.now().astimezone()
    dt = departure_time.astimezone()
    if dt < now:
        dt = now
    # Round up to the next 15-min boundary so we never pass a past timestamp.
    minutes_into_slot = dt.minute % 15
    if minutes_into_slot:
        dt = dt + timedelta(minutes=(15 - minutes_into_slot))
    rounded = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
    return _cached_lookup(origin, destination, rounded.isoformat())
