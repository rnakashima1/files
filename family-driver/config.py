"""Central config loaded from environment variables (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _list(name, default=""):
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


GOOGLE_OAUTH_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "credentials.json")
GOOGLE_OAUTH_TOKEN_FILE = os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "token.json")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_TENANT_ID = os.getenv("MS_TENANT_ID", "common")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")

TEAMSNAP_ACCESS_TOKEN = os.getenv("TEAMSNAP_ACCESS_TOKEN", "")
TEAMSNAP_TEAM_NAME = os.getenv("TEAMSNAP_TEAM_NAME", "Sanjo's Fury")

HOME_ADDRESS = os.getenv("HOME_ADDRESS", "")
DRIVERS = _list("DRIVERS", "Komaki,Ryan")
NON_DRIVERS = _list("NON_DRIVERS", "Oto,Lara,Sanjo")

PLAN_RECIPIENTS = _list("PLAN_RECIPIENTS", "")

# Google Calendar: comma-separated list of calendarId:PersonName pairs.
# e.g. "primary:Ryan,komakisera@gmail.com:Komaki,abc123@group.calendar.google.com:Family"
def _parse_calendar_map(raw: str) -> dict:
    result = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            cal_id, _, name = entry.partition(":")
            result[cal_id.strip()] = name.strip()
    return result

GOOGLE_CALENDAR_MAP = _parse_calendar_map(os.getenv("GOOGLE_CALENDAR_MAP", ""))

# How many minutes a driver needs to be at a location before an event starts
ARRIVAL_BUFFER_MINUTES = int(os.getenv("ARRIVAL_BUFFER_MINUTES", "10"))
# How many minutes a rider can wait after their event ends before we flag Uber.
PICKUP_SLACK_MINUTES = int(os.getenv("PICKUP_SLACK_MINUTES", "20"))

# Known locations: if a calendar event has no location but its title contains
# one of these keywords (case-insensitive), use this address instead.
KNOWN_LOCATIONS = {
    "ata": "ATA Gymnastics, Foxworthy Ave & Meridian Ave, San Jose, CA",
    "paula": "1479 Montelegre Dr, San Jose, CA",
    "union school district": "Union School District, Union Ave & Los Gatos Almaden Rd, San Jose, CA",
}
