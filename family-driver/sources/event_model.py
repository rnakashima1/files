"""Common event representation shared across all calendar/sport sources."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    """A single normalized calendar/event entry."""

    source: str            # "google_calendar" | "outlook" | "teamsnap"
    person: str            # Whose event this is, e.g. "Oto", "Lara", "Sanjo", "Family"
    title: str
    start: datetime        # timezone-aware
    end: datetime          # timezone-aware
    location: Optional[str] = None
    needs_ride: bool = True  # False for e.g. all-day reminders with no location
    raw: dict = field(default_factory=dict)

    def overlaps(self, other: "Event") -> bool:
        return self.start < other.end and other.start < self.end

    def __repr__(self):
        loc = f" @ {self.location}" if self.location else ""
        return (f"<Event {self.person}: '{self.title}' "
                f"{self.start:%H:%M}-{self.end:%H:%M}{loc} ({self.source})>")


def merge_and_sort(*event_lists, after: datetime = None):
    """Flatten multiple lists of Events, drop those without a location (nothing to drive to),
    optionally drop events that have already ended, and return sorted by start time."""
    merged = [e for lst in event_lists for e in lst if e.location and e.needs_ride]
    if after is not None:
        merged = [e for e in merged if e.end > after]
    return sorted(merged, key=lambda e: e.start)
