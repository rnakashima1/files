"""Fetch today's events from Outlook / Microsoft 365 via Microsoft Graph.

Auth: MSAL device-code flow (public client) — works for personal or work
Microsoft accounts without needing a client secret. Token cache is kept
in-memory per run; for unattended re-runs, persist `app.token_cache` to disk.
"""
from datetime import datetime, time, timedelta

import requests
import msal

import config
from sources.event_model import Event

GRAPH_SCOPES = ["Calendars.Read"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get_token():
    app = msal.PublicClientApplication(
        config.MS_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{config.MS_TENANT_ID}",
    )
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
    if not result:
        flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to start device flow: {flow}")
        print(flow["message"])  # Prompts user to open a browser & enter the code
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Could not authenticate with Microsoft Graph: {result}")
    return result["access_token"]


def fetch_today_events(calendar_person_map: dict, day: datetime = None):
    """calendar_person_map: {"me": "Parent1"} or {calendar_id: person_name, ...}

    Uses /me/calendarView for the "me" entry; for shared/other calendars you'd
    extend this to /users/{id}/calendarView with appropriate permissions.
    """
    day = day or datetime.now().astimezone()
    start_of_day = datetime.combine(day.date(), time.min, tzinfo=day.tzinfo)
    end_of_day = start_of_day + timedelta(days=1)

    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="UTC"',
    }

    events = []
    for cal_key, person in calendar_person_map.items():
        url = f"{GRAPH_BASE}/me/calendarView"
        params = {
            "startDateTime": start_of_day.astimezone().isoformat(),
            "endDateTime": end_of_day.astimezone().isoformat(),
            "$orderby": "start/dateTime",
            "$select": "subject,start,end,location",
        }
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()

        for item in resp.json().get("value", []):
            start = datetime.fromisoformat(item["start"]["dateTime"])
            end = datetime.fromisoformat(item["end"]["dateTime"])
            location = (item.get("location") or {}).get("displayName") or None
            events.append(Event(
                source="outlook",
                person=person,
                title=item.get("subject", "(no title)"),
                start=start,
                end=end,
                location=location,
                needs_ride=bool(location),
                raw=item,
            ))
    return events
