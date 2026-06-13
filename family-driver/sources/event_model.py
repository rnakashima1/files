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
    raw: dict = field(default_factory=dict)

    def overlaps(self, other: "Event") -> bool:
        return self.start < other.end and other.start < self.end

    def __repr__(self):
        loc = f" @ {self.location}" if self.location else ""
        return (f"<Event {self.person}: '{self.title}' "
                f"{self.start:%H:%M}-{self.end:%H:%M}{loc} ({self.source})>")


def dedupe(events):
    """Drop copies of the same event that appear on multiple calendars
    (same person, title, and times). Keeps the first copy with a location."""
    seen = {}
    for e in sorted(events, key=lambda e: (e.location is None,)):
        key = (e.person, e.title.strip().lower(), e.start, e.end)
        if key not in seen:
            seen[key] = e
    return list(seen.values())


def merge_and_sort(*event_lists, after: datetime = None):
    """Flatten multiple lists of Events, drop those without a location (nothing to drive to),
    optionally drop events that have already ended, dedupe cross-calendar copies,
    and return sorted by start time."""
    merged = [e for lst in event_lists for e in lst if e.location and e.needs_ride]
    if after is not None:
        merged = [e for e in merged if e.end > after]
    return sorted(dedupe(merged), key=lambda e: e.start)
