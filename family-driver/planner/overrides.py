"""Per-day event overrides learned from email replies.

When the plan email asks "where is the team lunch?" and someone replies
"Team lunch: 1234 Main St, Your City", the answer is stored here and applied on
the next plan build for that date.

Storage: overrides.json in the project root:
  { "2026-06-10": { "team lunch": {"location": "...", "person": "..."} } }
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import config

OVERRIDES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "overrides.json")


def _load() -> dict:
    try:
        with open(OVERRIDES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict):
    with open(OVERRIDES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_for_day(day_key: str) -> dict:
    return _load().get(day_key, {})


def set_override(day_key: str, title: str, **fields):
    """Store override fields for an event on a given day. Recognized fields:
    location, person, driver (force this driver), skip (rider has another ride),
    start, end ('HH:MM', retime the event)."""
    data = _load()
    entry = data.setdefault(day_key, {}).setdefault(title.lower().strip(), {})
    for k, v in fields.items():
        if v is not None:
            entry[k] = v
    _save(data)


def _retime(dt, hhmm, day_key):
    """Return a datetime on day_key (YYYY-MM-DD) at HH:MM wall-clock time in the
    household timezone (config.TIMEZONE), expressed in dt's original tzinfo.

    The date is built explicitly from day_key rather than derived from dt,
    because converting an all-day event's stored UTC midnight to local time can
    land on the previous calendar day. Reply times are always local
    wall-clock — never converted from UTC."""
    h, m = (int(x) for x in hhmm.split(":"))
    y, mo, d = (int(x) for x in day_key.split("-"))
    local_tz = ZoneInfo(config.TIMEZONE)
    if dt.tzinfo is None:
        return datetime(y, mo, d, h, m, tzinfo=local_tz)
    local_dt = datetime(y, mo, d, h, m, tzinfo=local_tz)
    return local_dt.astimezone(dt.tzinfo)


def apply_overrides(events, day_key: str):
    """Mutate events in place with any stored answers/directives for this day."""
    day_overrides = get_for_day(day_key)
    if not day_overrides:
        return events
    for e in events:
        for title_key, fix in day_overrides.items():
            if title_key in e.title.lower():
                if fix.get("skip"):
                    e.skip = True
                if fix.get("location"):
                    e.location = fix["location"]
                    e.needs_ride = True
                if fix.get("person"):
                    e.person = fix["person"]
                if fix.get("driver"):
                    e.forced_driver = fix["driver"]
                if fix.get("start"):
                    e.start = _retime(e.start, fix["start"], day_key)
                if fix.get("end"):
                    e.end = _retime(e.end, fix["end"], day_key)
                break
    return events


def collect_questions(events):
    """Return (event, kind) pairs the email should ask about.

    kind = "where"  — family member event with no driveable location
    kind = "who"    — event whose attendee couldn't be determined (e.g. on the
                      Family calendar with no child named in the title)
    """
    # Titles that are really to-do reminders, not appointments — no travel.
    TODO_PREFIXES = ("make ", "call ", "email ", "text ", "buy ", "order ",
                     "schedule ", "book ", "remind", "pay ", "sign up", "renew ")
    family = set(config.DRIVERS) | set(config.NON_DRIVERS)
    questions = []
    for e in events:
        if e.virtual:
            continue
        if e.title.lower().startswith(TODO_PREFIXES):
            continue
        if e.person not in family:
            questions.append((e, "who"))
        elif not e.location:
            questions.append((e, "where"))
    return questions


def parse_reply_lines(text: str, events) -> list:
    """Parse a reply body into (event_title, field, value) answers.

    Lines look like 'Team lunch: 1234 Main St' (location) or
    'Playdate: <child name>' (attendee, when the value is a family member's name).
    Returns list of (title, {"location": ...} or {"person": ...}).
    """
    family = {n.lower(): n for n in (list(config.DRIVERS) + list(config.NON_DRIVERS))}
    answers = []
    for line in text.splitlines():
        line = line.strip().lstrip(">").strip()
        if not line or ":" not in line:
            continue
        title_part, _, value = line.partition(":")
        title_part, value = title_part.strip().lower(), value.strip()
        if not value:
            continue
        for e in events:
            et = e.title.lower()
            if title_part and (title_part in et or et in title_part):
                if value.lower() in family:
                    answers.append((e.title, {"person": family[value.lower()]}))
                else:
                    answers.append((e.title, {"location": value}))
                break
    return answers
