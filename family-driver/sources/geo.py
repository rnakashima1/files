"""Best-effort: derive an IANA timezone from a street address, using Google's
Geocoding + Time Zone APIs (same key as the Routes API).

Returns None on any failure (no key, API not enabled, no result, network
error) so callers fall back to the configured/default timezone.
"""
import time

import requests

import config


def timezone_for_address(address):
    """Return an IANA timezone id (e.g. 'America/Los_Angeles') for `address`,
    or None if it can't be determined."""
    key = config.GOOGLE_MAPS_API_KEY
    if not address or not key:
        return None
    try:
        geo = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": key}, timeout=20,
        ).json()
        results = geo.get("results") or []
        if not results:
            return None
        loc = results[0]["geometry"]["location"]
        tz = requests.get(
            "https://maps.googleapis.com/maps/api/timezone/json",
            params={"location": f"{loc['lat']},{loc['lng']}",
                    "timestamp": int(time.time()), "key": key}, timeout=20,
        ).json()
        return tz.get("timeZoneId") or None
    except Exception:  # noqa: BLE001 — best effort; caller falls back
        return None
