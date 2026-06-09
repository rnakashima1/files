"""Fetch today's games/practices for the "Sanjo's Fury" team from the
TeamSnap API v3 (https://www.teamsnap.com/documentation/apiv3).

Auth: OAuth2 access token (create an app at https://auth.teamsnap.com,
or generate a personal token). TeamSnap's API uses a Collection+JSON / HAL-ish
format with a search-and-follow-links pattern; this module does the minimal
walk: find the team by name -> list events in range -> resolve location.
"""
from datetime import datetime, time, timedelta

import requests

import config
from sources.event_model import Event

API_BASE = "https://api.teamsnap.com/v3"


def _headers():
    return {
        "Authorization": f"Bearer {config.TEAMSNAP_ACCESS_TOKEN}",
        "Accept": "application/json",
    }


def _get_user_id() -> str:
    resp = requests.get(f"{API_BASE}/me", headers=_headers(), timeout=30)
    resp.raise_for_status()
    items = resp.json().get("collection", {}).get("items", [])
    if not items:
        raise RuntimeError("Could not retrieve TeamSnap user info")
    data = {d["name"]: d.get("value") for d in items[0].get("data", [])}
    return str(data["id"])


def _find_team_id(team_name: str) -> str:
    user_id = _get_user_id()
    resp = requests.get(f"{API_BASE}/teams/active", headers=_headers(),
                        params={"user_id": user_id}, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("collection", {}).get("items", [])
    for item in items:
        data = {d["name"]: d.get("value") for d in item.get("data", [])}
        if data.get("name", "").lower() == team_name.lower():
            return str(data["id"])
    raise RuntimeError(f"TeamSnap team '{team_name}' not found")


def fetch_today_events(person="Sanjo", day: datetime = None):
    """Returns games + practices for today as a list of Event, attributed to `person`
    (the player on the team — defaults to Sanjo per the household roster)."""
    day = day or datetime.now().astimezone()
    start_of_day = datetime.combine(day.date(), time.min, tzinfo=day.tzinfo)
    end_of_day = start_of_day + timedelta(days=1)

    team_id = _find_team_id(config.TEAMSNAP_TEAM_NAME)

    events = []
    for resource in ("events",):  # TeamSnap exposes games & practices both under /events
        resp = requests.get(
            f"{API_BASE}/{resource}/search",
            headers=_headers(),
            params={
                "team_id": team_id,
                "started_after": start_of_day.astimezone().isoformat(),
                "started_before": end_of_day.astimezone().isoformat(),
            },
            timeout=30,
        )
        resp.raise_for_status()
        for item in resp.json().get("collection", {}).get("items", []):
            data = {d["name"]: d.get("value") for d in item.get("data", [])}
            start = datetime.fromisoformat(data["start_date"].replace("Z", "+00:00"))
            # TeamSnap doesn't always give an explicit end; default to 2 hours
            end = (datetime.fromisoformat(data["end_date"].replace("Z", "+00:00"))
                   if data.get("end_date") else start + timedelta(hours=2))
            location = (data.get("location_name") or data.get("formatted_location_address")
                        or data.get("location"))
            title = data.get("name") or ("Game" if data.get("is_game") else "Practice")
            events.append(Event(
                source="teamsnap",
                person=person,
                title=f"{config.TEAMSNAP_TEAM_NAME}: {title}",
                start=start,
                end=end,
                location=location,
                needs_ride=bool(location),
                raw=data,
            ))
    return events
