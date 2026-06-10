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
from planner import overrides
from email_draft import gmail_draft
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


def build_plan_for_day(day, after=None):
    """Fetch events, apply reply-overrides, and build the plan.

    Returns (legs, questions, all_events)."""
    day_key = f"{day:%Y-%m-%d}"
    g_events, o_events, t_events = gather_events(day)
    all_events = g_events + o_events + t_events
    overrides.apply_overrides(all_events, day_key)

    timeline = build_timeline(all_events, after=after)
    print("\n" + render_timeline(timeline) + "\n")

    # Build driver calendars from ALL events (no location filter) so their own
    # appointments (e.g. job interviews) correctly block them from driving.
    _, driver_calendars = split_kid_and_driver_events(all_events)
    kid_events = [e for e in timeline if e.person in config.NON_DRIVERS]
    legs = build_driving_plan(kid_events, driver_calendars)

    # Events we couldn't plan for — missing location or unknown attendee.
    upcoming = [e for e in all_events if after is None or e.end > after]
    questions = overrides.collect_questions(upcoming)
    return legs, questions, all_events


def check_replies():
    """Read replies on the latest plan thread; if they answer open questions,
    store the answers and reply with an updated plan."""
    state, replies = gmail_draft.fetch_new_replies()
    if not replies:
        print("No new replies.")
        return
    day_key = state["day"]
    day = datetime.strptime(day_key, "%Y-%m-%d").astimezone()
    g_events, o_events, t_events = gather_events(day)
    all_events = g_events + o_events + t_events

    new_answers = []
    reply_ids = []
    for msg_id, sender, text in replies:
        reply_ids.append(msg_id)
        for title, fix in overrides.parse_reply_lines(text, all_events):
            overrides.set_override(day_key, title, **fix)
            new_answers.append(f"{title}: {fix}")
            print(f"  Answer from {sender}: {title} -> {fix}")

    if not new_answers:
        # Nothing parseable — mark replies processed so we don't loop on them.
        state.setdefault("processed", []).extend(reply_ids)
        gmail_draft._save_state(state)
        print("Replies contained no recognizable answers.")
        return

    now = datetime.now().astimezone()
    after = now if day.date() == now.date() else None
    legs, questions, _ = build_plan_for_day(day, after=after)
    html_body = render_plan_html(legs, [], day, questions=questions)
    msg_id = gmail_draft.send_reply_on_thread(state, html_body, extra_processed=reply_ids)
    print(f"Updated plan sent on thread (id={msg_id}).")


def main():
    parser = argparse.ArgumentParser(description="Generate the family driving plan.")
    parser.add_argument("--date", help="Date to plan for (YYYY-MM-DD), defaults to today")
    parser.add_argument("--tomorrow", action="store_true", help="Plan for tomorrow")
    parser.add_argument("--draft-email", action="store_true",
                        help="Create a Gmail draft of the plan")
    parser.add_argument("--send", action="store_true",
                        help="Send the plan email to all recipients (Komaki + Ryan)")
    parser.add_argument("--check-replies", action="store_true",
                        help="Check the latest plan email for replies answering "
                             "open questions; send an updated plan if so")
    args = parser.parse_args()

    if args.check_replies:
        check_replies()
        return

    now = datetime.now().astimezone()
    if args.tomorrow:
        day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").astimezone()
    else:
        day = now

    # For today, skip events that have already ended. For any other date, show all.
    after = now if (not args.date and not args.tomorrow) else None
    legs, questions, _ = build_plan_for_day(day, after=after)

    plan_text = render_plan(legs, [], day)
    print(plan_text)
    if questions:
        print("\nOPEN QUESTIONS")
        for ev, kind in questions:
            print(f"  {ev.title} — {'who is going?' if kind == 'who' else 'where is it?'}")

    subject = f"Driving plan for {day:%a %b %-d}"
    if args.send:
        html_body = render_plan_html(legs, [], day, questions=questions)
        msg_id = send_plan(subject, html_body, day_key=f"{day:%Y-%m-%d}")
        print(f"\nEmail sent (id={msg_id}) to: {', '.join(config.PLAN_RECIPIENTS)}")
    elif args.draft_email:
        html_body = render_plan_html(legs, [], day, questions=questions)
        draft_id = create_plan_draft(subject, html_body)
        print(f"\nGmail draft created (id={draft_id}). Review and send it from Gmail.")


if __name__ == "__main__":
    main()
