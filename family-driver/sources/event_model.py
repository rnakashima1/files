"""Common event representation shared across all calendar/sport sources."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    """A single normalized calendar/event entry."""

    source: str            # "google_calendar" | "outlook" | "teamsnap"
    person: str            # Whose event this is — a driver, a child, or "Family"
    title: str
    start: datetime        # timezone-aware
    end: datetime          # timezone-aware
    location: Optional[str] = None
    needs_ride: bool = True  # False for e.g. all-day reminders with no location
    virtual: bool = False    # Zoom/Teams/Meet — no driving, no location question
    skip: bool = False       # override: rider has another ride — exclude from plan
    forced_driver: Optional[str] = None  # override: this driver must handle it
    raw: dict = field(default_factory=dict)

    def overlaps(self, other: "Event") -> bool:
        return self.start < other.end and other.start < self.end

    def __repr__(self):
        loc = f" @ {self.location}" if self.location else ""
        return (f"<Event {self.person}: '{self.title}' "
                f"{self.start:%H:%M}-{self.end:%H:%M}{loc} ({self.source})>")


def _norm_title(title):
    """Title reduced to lowercase alphanumerics, so e.g. 'Fury 11U: Shooting
    Camp' (TeamSnap) and 'Fury 11U - Shooting Camp' (Google) match."""
    return "".join(c for c in (title or "").lower() if c.isalnum())


def _location_score(e):
    """How routable a location is: a street address (contains a digit) beats a
    bare venue name, which beats nothing."""
    if not e.location:
        return 0
    return 2 if any(c.isdigit() for c in e.location) else 1


def dedupe(events):
    """Collapse the same event arriving from multiple calendars/sources — same
    person, normalized title, start and end. Keeps the copy with the most
    routable location, so a Google Calendar street address wins over the bare
    venue name TeamSnap returns for the same game/practice."""
    best = {}
    for e in events:
        key = (e.person, _norm_title(e.title), e.start, e.end)
        cur = best.get(key)
        if cur is None or _location_score(e) > _location_score(cur):
            best[key] = e
    return list(best.values())


def merge_and_sort(*event_lists, after: datetime = None):
    """Flatten multiple lists of Events, drop those without a location (nothing to drive to),
    optionally drop events that have already ended, dedupe cross-calendar copies,
    and return sorted by start time."""
    merged = [e for lst in event_lists for e in lst if e.location and e.needs_ride]
    if after is not None:
        merged = [e for e in merged if e.end > after]
    return sorted(dedupe(merged), key=lambda e: e.start)
