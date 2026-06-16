"""Central config loaded from environment variables (.env).

All household-specific values (names, addresses, calendar IDs, recipients) come
from the .env file — there are no family names hard-coded here. The onboarding
web app (web/) writes this .env; see .env.example for the full key list.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _list(name, default=""):
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_pairs(raw: str) -> dict:
    """Parse 'a:1,b:2' into {'a': '1', 'b': '2'} (first colon splits each entry)."""
    result = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if ":" in entry:
            key, _, val = entry.partition(":")
            result[key.strip()] = val.strip()
    return result


GOOGLE_OAUTH_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "credentials.json")
GOOGLE_OAUTH_TOKEN_FILE = os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "token.json")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# Anthropic / Claude — a single SERVICE credential interprets all free-form
# email replies (planner/llm_reply.py). End users are never asked for a key.
# Provide ONE of: ANTHROPIC_API_KEY (Console pay-as-you-go key) or
# ANTHROPIC_AUTH_TOKEN (OAuth token from a Claude Pro/Max subscription); or set
# ANTHROPIC_USE_LOGIN=1 to use an `ant auth login` profile on this host.
# Without any, replies fall back to the keyword parser.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
# Model for the (small, cheap) reply-interpretation step. Default Opus; set to
# claude-haiku-4-5 or claude-sonnet-4-6 to cut cost.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_TENANT_ID = os.getenv("MS_TENANT_ID", "common")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")

TEAMSNAP_ACCESS_TOKEN = os.getenv("TEAMSNAP_ACCESS_TOKEN", "")
TEAMSNAP_TEAM_NAME = os.getenv("TEAMSNAP_TEAM_NAME", "")
# Which child (non-driver) the TeamSnap team belongs to.
TEAMSNAP_PERSON = os.getenv("TEAMSNAP_PERSON", "")

# Household roster — populated by onboarding. "Drivers" are parents who can
# drive; "non-drivers" are children (or any rider who needs a ride).
HOME_ADDRESS = os.getenv("HOME_ADDRESS", "")
# IANA timezone for the household (where they live). Drives all displayed times
# and the interpretation of times in email replies. Onboarding derives it from
# the home address; defaults to US Pacific.
TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
NUM_CARS = int(os.getenv("NUM_CARS", "1") or "1")
DRIVERS = _list("DRIVERS")
NON_DRIVERS = _list("NON_DRIVERS")

# Email addresses that should receive the daily driving summary.
PLAN_RECIPIENTS = _list("PLAN_RECIPIENTS")

# Optional explicit colour per driver for the email, e.g.
# "Parent1:#1a73e8,Parent2:#c0392b". If unset, colours are assigned from a
# palette in roster order (see planner/timeline.py).
DRIVER_COLORS = _parse_pairs(os.getenv("DRIVER_COLORS", ""))

# Google Calendar: comma-separated list of calendarId:PersonName pairs, e.g.
# "primary:Parent1,spouse@example.com:Parent2,abc123@group.calendar.google.com:Family"
GOOGLE_CALENDAR_MAP = _parse_pairs(os.getenv("GOOGLE_CALENDAR_MAP", ""))

# Outlook / Microsoft 365: calendarId:PersonName pairs. Use "me:Parent1" for the
# signed-in account's default calendar.
OUTLOOK_CALENDAR_MAP = _parse_pairs(os.getenv("OUTLOOK_CALENDAR_MAP", ""))

# How many minutes a driver needs to be at a location before an event starts
ARRIVAL_BUFFER_MINUTES = int(os.getenv("ARRIVAL_BUFFER_MINUTES", "10"))
# How many minutes a rider can wait after their event ends before we flag Uber.
PICKUP_SLACK_MINUTES = int(os.getenv("PICKUP_SLACK_MINUTES", "20"))


# Known locations: if a calendar event has no location but its title contains
# one of these keywords (case-insensitive), use the mapped address instead.
# Format in .env (optional): "keyword:address; keyword2:address2"
def _parse_known_locations(raw: str) -> dict:
    result = {}
    for entry in (raw or "").split(";"):
        entry = entry.strip()
        if ":" in entry:
            kw, _, addr = entry.partition(":")
            result[kw.strip().lower()] = addr.strip()
    return result

KNOWN_LOCATIONS = _parse_known_locations(os.getenv("KNOWN_LOCATIONS", ""))

# Flask session signing key for the onboarding web app (auto-generated on first
# onboarding run if missing).
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "")
