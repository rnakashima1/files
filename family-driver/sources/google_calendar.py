"""Fetch today's events from Google Calendar (one or more calendars, e.g. each
family member's calendar) using the Google Calendar API.

Auth: OAuth2 "installed app" flow. First run opens a browser for consent and
caches a refresh token in GOOGLE_OAUTH_TOKEN_FILE.
"""
from datetime import datetime, time, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config
from sources.event_model import Event

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _get_credentials():
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(config.GOOGLE_OAUTH_TOKEN_FILE, SCOPES)
    except FileNotFoundError:
        pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.GOOGLE_OAUTH_CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(config.GOOGLE_OAUTH_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def _resolve_person(label):
    """Map a calendar's label to a family member. An exact family name wins;
    otherwise a label that contains a family name (e.g. 'Ryan-Work' -> 'Ryan')
    resolves to that person, so work/other calendars are attributed correctly."""
    family = list(config.DRIVERS) + list(config.NON_DRIVERS)
    if label in family:
        return label
    low = (label or "").lower()
    for fam in family:
        if fam.lower() in low:
            return fam
    return label


def fetch_today_events(calendar_person_map: dict, day: datetime = None):
    """calendar_person_map: {calendar_id_or_'primary': person_name}

    Returns a list of Event for the given local day (defaults to today).
    """
    day = day or datetime.now().astimezone()
    start_of_day = datetime.combine(day.date(), time.min, tzinfo=day.tzinfo)
    end_of_day = start_of_day + timedelta(days=1)

    creds = _get_credentials()
    service = build("calendar", "v3", credentials=creds)

    events = []
    for calendar_id, person in calendar_person_map.items():
        person = _resolve_person(person)
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        for item in resp.get("items", []):
            start_raw = item["start"].get("dateTime") or item["start"].get("date")
            end_raw = item["end"].get("dateTime") or item["end"].get("date")
            start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            if start.tzinfo is None:  # all-day event
                start = start.replace(tzinfo=timezone.utc)
                end = end.replace(tzinfo=timezone.utc)

            location = item.get("location")
            if location:
                # Calendar addresses often span multiple lines; flatten to one
                # comma-separated line so the Maps API can geocode it.
                location = ", ".join(p.strip() for p in location.splitlines() if p.strip())
            title = item.get("summary", "")
            title_lower = title.lower()
            # Discard virtual/URL locations (Zoom, Teams, Meet links) — not driveable.
            virtual = False
            if location and (
                location.startswith(("http://", "https://", "zoom.us",
                                     "teams.microsoft.com", "meet.google.com"))
                or "teams meeting" in location.lower()
            ):
                location = None
                virtual = True
            if "zoom" in title_lower:
                virtual = True
            if not location:
                for keyword, address in config.KNOWN_LOCATIONS.items():
                    if keyword in title_lower:
                        location = address
                        break
            # If event is on a driver's calendar but names a non-driver in the title,
            # reassign to that child (they need the ride, not the driver).
            assigned_person = person
            if person not in config.NON_DRIVERS:
                for child in config.NON_DRIVERS:
                    if child.lower() in title_lower:
                        assigned_person = child
                        break
            events.append(Event(
                source="google_calendar",
                person=assigned_person,
                title=title or "(no title)",
                start=start,
                end=end,
                location=location,
                needs_ride=bool(location),
                virtual=virtual,
                raw=item,
            ))
    return events
