#!/usr/bin/env python3
"""Family driving-plan generator — entry point.

Run:  python main.py [--draft-email] [--date YYYY-MM-DD]

Pulls today's events from Google Calendar, Outlook, and TeamSnap (Sanjo's
Fury), lines them up by time + location, builds a one-car pickup/dropoff
driving plan for Komaki and Ryan, estimates drive times with the Google Maps
Routes API (traffic-aware), prints the plan, and — if --draft-email is passed
— creates a Gmail draft of the plan addressed to Komaki for review & sending.

CONFIGURE FIRST: copy .env.example to .env and fill in:
  - Google OAuth client (credentials.json) for Calendar + Gmail
  - Google Maps API key with the Routes API enabled
  - Microsoft Graph app registration (for Outlook)
  - TeamSnap OAuth access token
  - Household addresses / names

Then map each family member to their calendar IDs below in CALENDAR_MAP /
OUTLOOK_MAP — these are placeholders you should edit for your household.
"""
import argparse
from datetime import datetime, timedelta

import config
from sources import google_calendar, outlook_calendar, teamsnap
from sources.event_model import Event
from planner.timeline import build_timeline, render_timeline, render_plan, render_plan_html
from planner.driving_plan import build_driving_plan, summarize_conflicts
from email_draft.gmail_draft import create_plan_draft, send_plan

# Calendar maps are loaded from .env (GOOGLE_CALENDAR_MAP, OUTLOOK_CALENDAR_MAP).
# See .env.example for the format.
GOOGLE_CALENDAR_MAP = config.GOOGLE_CALENDAR_MAP

# Outlook / Microsoft 365: same idea, via Microsoft Graph.
OUTLOOK_CALENDAR_MAP = {
    "me": "Komaki",
}


def gather_events(day):
    print("Fetching Google Calendar events...")
    g_events = google_calendar.fetch_today_events(GOOGLE_CALENDAR_MAP, day)

    print("Fetching Outlook events...")
    try:
        o_events = outlook_calendar.fetch_today_events(OUTLOOK_CALENDAR_MAP, day)
    except Exception as exc:
        print(f"  (skipping Outlook — {exc})")
        o_events = []

    print(f"Fetching TeamSnap ({config.TEAMSNAP_TEAM_NAME}) events for Sanjo...")
    try:
        t_events = teamsnap.fetch_today_events(person="Sanjo", day=day)
    except Exception as exc:
        print(f"  (skipping TeamSnap — {exc})")
        t_events = []

    return g_events, o_events, t_events


def split_kid_and_driver_events(all_events):
    """Kids' events need rides; drivers' own events constrain their availability."""
    kid_events = [e for e in all_events if e.person in config.NON_DRIVERS]
    driver_calendars = {d: [] for d in config.DRIVERS}
    for e in all_events:
        if e.person in driver_calendars:
            driver_calendars[e.person].append(e)
    return kid_events, driver_calendars


def main():
    parser = argparse.ArgumentParser(description="Generate the family driving plan.")
    parser.add_argument("--date", help="Date to plan for (YYYY-MM-DD), defaults to today")
    parser.add_argument("--tomorrow", action="store_true", help="Plan for tomorrow")
    parser.add_argument("--draft-email", action="store_true",
                        help="Create a Gmail draft of the plan")
    parser.add_argument("--send", action="store_true",
                        help="Send the plan email to all recipients (Komaki + Ryan)")
    args = parser.parse_args()

    now = datetime.now().astimezone()
    if args.tomorrow:
        day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").astimezone()
    else:
        day = now

    g_events, o_events, t_events = gather_events(day)
    all_events = g_events + o_events + t_events

    # For today, skip events that have already ended. For any other date, show all.
    after = now if (not args.date and not args.tomorrow) else None

    timeline = build_timeline(all_events, after=after)
    print("\n" + render_timeline(timeline) + "\n")

    # Build driver calendars from ALL events (no location filter) so their own
    # appointments (e.g. job interviews) correctly block them from driving.
    _, driver_calendars = split_kid_and_driver_events(all_events)
    kid_events = [e for e in timeline if e.person in config.NON_DRIVERS]
    legs = build_driving_plan(kid_events, driver_calendars)

    plan_text = render_plan(legs, [], day)
    print(plan_text)

    subject = f"Driving plan for {day:%a %b %-d}"
    if args.send:
        html_body = render_plan_html(legs, [], day)
        msg_id = send_plan(subject, html_body)
        print(f"\nEmail sent (id={msg_id}) to: {', '.join(config.PLAN_RECIPIENTS)}")
    elif args.draft_email:
        html_body = render_plan_html(legs, [], day)
        draft_id = create_plan_draft(subject, html_body)
        print(f"\nGmail draft created (id={draft_id}) — addressed to "
              f"{config.PLAN_RECIPIENT_EMAIL}. Review and send it from Gmail.")


if __name__ == "__main__":
    main()
