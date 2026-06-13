"""Builds the merged daily timeline (Step 1) and renders a human/email-friendly
write-up of the resulting driving plan (used for both console output and the
Gmail draft body)."""
from datetime import datetime
from typing import List
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import config
from sources.event_model import Event, merge_and_sort
from planner.driving_plan import Leg

LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _local(dt: datetime) -> datetime:
    """Convert a datetime to Pacific time."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(LOCAL_TZ)


def _fmt(dt: datetime) -> str:
    """Format a (already-localized) datetime as '2:01 p.m.'"""
    return dt.strftime("%-I:%M") + (" a.m." if dt.hour < 12 else " p.m.")


def build_timeline(*event_lists, after: datetime = None) -> List[Event]:
    """Merge events from every source (Google Calendar, Outlook, TeamSnap),
    drop anything without a location, optionally drop past events, and sort chronologically."""
    return merge_and_sort(*event_lists, after=after)


def render_timeline(events: List[Event]) -> str:
    if not events:
        return "No location-based events found for today."
    lines = ["TODAY'S EVENTS WITH LOCATIONS", "-" * 40]
    for e in events:
        s, en = _local(e.start), _local(e.end)
        lines.append(f"{_fmt(s)}-{_fmt(en)}  {e.person:7s} {e.title}  @ {e.location}")
    return "\n".join(lines)


def render_plan_html(legs: List[Leg], conflicts: List[str], day: datetime,
                     questions: list = None, assumptions: list = None) -> str:
    """Render the driving plan as an HTML email body."""
    rows = []

    def row(content, indent=False):
        pad = "padding-left:20px;" if indent else ""
        rows.append(f'<div style="margin:4px 0;{pad}">{content}</div>')

    rows.append(
        f'<h2 style="font-family:sans-serif;color:#333;margin-bottom:8px">'
        f'🗓️ Driving Plan — {day:%A, %B %-d, %Y}</h2>'
    )
    rows.append('<hr style="border:none;border-top:2px solid #eee;margin:8px 0">')

    def _questions_html():
        if not questions:
            return
        rows.append(
            '<h3 style="font-family:sans-serif;color:#b8860b;margin:16px 0 4px">'
            '❓ Open questions</h3>'
        )
        for ev, kind in questions:
            s = _local(ev.start)
            if kind == "who":
                ask = "who is going?"
            else:
                ask = "where is it? (no address on the calendar)"
            rows.append(
                f'<div style="margin:4px 0">📅 <strong>{ev.title}</strong>'
                f' ({_fmt(s)}, {ev.person}) — {ask}</div>'
            )
        rows.append(
            '<p style="font-family:sans-serif;font-size:12px;color:#888;margin:6px 0 0">'
            'Reply to this email with one line per answer, like<br>'
            '<code>Komaki lunch: 1234 Lincoln Ave, San Jose</code> &nbsp;(location)<br>'
            '<code>Playdate: Lara</code> &nbsp;(attendee)<br>'
            'Replies are checked every 30 minutes and an updated plan is sent back '
            'on this thread.</p>'
        )

    def _assumptions_html():
        if not assumptions:
            return
        rows.append(
            '<h3 style="font-family:sans-serif;color:#3b5bdb;margin:16px 0 4px">'
            '📋 Assumptions</h3>')
        for a in assumptions:
            rows.append(f'<div style="margin:4px 0">🅿️ {a}</div>')

    if not legs:
        rows.append('<p style="font-family:sans-serif;color:#555">No driving needed today.</p>')
        _questions_html()
        _assumptions_html()
        return ('<html><body style="font-family:sans-serif;font-size:14px;color:#333;'
                'max-width:600px;margin:0 auto;padding:16px">\n'
                + "\n".join(rows) + "\n</body></html>")

    def _maps_link(origin, destination):
        params = urlencode({
            "api": "1",
            "origin": origin,
            "destination": destination,
            "travelmode": "driving",
        })
        url = f"https://www.google.com/maps/dir/?{params}"
        return (f'<a href="{url}" style="color:#1a73e8;font-size:12px;'
                f'text-decoration:none">🗺 Directions</a>')

    def _car(color):
        """Car emoji on a colored background — gives the appearance of a colored car."""
        return (f'<span style="background:{color};border-radius:4px;'
                f'padding:1px 3px;font-size:13px">🚗</span>')

    rows.append(
        '<p style="font-family:sans-serif;font-size:13px;color:#888;margin:0 0 12px">'
        f'{_car("#1a73e8")} = drop-off &nbsp;&nbsp; '
        f'{_car("#c0392b")} = pick-up &nbsp;&nbsp; ⚠️ = needs Uber<br>'
        '<span style="color:#1a73e8">■ Ryan</span> &nbsp;&nbsp; '
        '<span style="color:#c0392b">■ Komaki</span></p>'
    )

    DRIVER_COLORS = {"Ryan": "#1a73e8", "Komaki": "#c0392b"}

    for leg in legs:
        driver = leg.driver or "UNASSIGNED"
        driver_color = DRIVER_COLORS.get(driver, "#555")
        eta_note = f"~{leg.drive_minutes:.0f} min" if leg.drive_minutes else ""
        depart = _local(leg.depart_by)
        es, ee = _local(leg.event.start), _local(leg.event.end)
        time_str = f'<span style="font-weight:bold">{_fmt(depart)}</span>'
        driver_html = f'<span style="color:{driver_color}">{driver}</span>'

        # DROPOFF: drive from origin to destination (event location).
        # PICKUP: drive from where the car actually is to the pickup location,
        #         then home — show as a two-stop route when car isn't already there.
        if leg.kind == "PICKUP":
            nav_from = leg.from_location or leg.destination
            nav_to = leg.origin  # the pickup location
            if nav_from == nav_to:
                maps = _maps_link(nav_to, leg.destination)  # already there, show trip home
            else:
                maps = _maps_link(nav_from, nav_to)         # drive to pickup
        else:
            maps = _maps_link(leg.origin, leg.destination)

        if leg.self_drive and not leg.uber:
            if leg.kind == "DROPOFF":
                desc = (f'{driver_html} drives <strong>themself</strong>'
                        f' to {leg.destination}')
                icon = _car("#1a73e8")
                detail = f'📅 <em>{leg.event.title}</em> ({_fmt(es)}–{_fmt(ee)})'
                maps = _maps_link(leg.origin, leg.destination)
            else:
                desc = (f'{driver_html} drives <strong>themself</strong> home'
                        f' from {leg.origin}')
                icon = _car("#c0392b")
                detail = f'📅 <em>{leg.event.title}</em> (ends {_fmt(ee)})'
                maps = _maps_link(leg.origin, leg.destination)
            row(f'{time_str} &nbsp; {icon} &nbsp;{desc}'
                + (f' ({eta_note})' if eta_note else '') + f' &nbsp; {maps}')
            row(f'<span style="color:#888;font-size:12px">{detail}</span>', indent=True)
        elif leg.uber:
            row(
                f'{time_str} &nbsp; ⚠️ <span style="color:#c0392b;font-weight:bold">UBER</span>'
                f' &nbsp; {leg.rider} [{leg.kind}] '
                f'{leg.origin} → {leg.destination}'
                + (f' ({eta_note})' if eta_note else '')
                + f' &nbsp; {maps}'
            )
            row(
                f'<span style="color:#888;font-size:12px">'
                f'for <em>{leg.event.title}</em> ({_fmt(es)}–{_fmt(ee)})'
                f' — {leg.conflict_reason}</span>',
                indent=True
            )
        elif leg.kind == "PICKUP":
            home = config.HOME_ADDRESS
            chained_from = leg.from_location
            if chained_from and chained_from != home and chained_from != leg.origin:
                depart_note = (f' <span style="color:#888;font-size:12px">'
                               f'(driving directly from {chained_from})</span>')
            else:
                depart_note = ''
            watch_note = (f' <span style="color:#3b5bdb;font-size:12px">'
                          f'(🅿️ {leg.assumption})</span>') if leg.assumption else ''
            row(
                f'{time_str} &nbsp; {_car("#c0392b")} &nbsp;'
                f'{driver_html}'
                f' leaves to pick up <strong>{leg.rider}</strong>'
                f' from {leg.origin}'
                + (f' ({eta_note})' if eta_note else '')
                + f', home by {_fmt(_local(leg.arrive_by))}'
                + depart_note
                + watch_note
                + f' &nbsp; {maps}'
            )
            row(
                f'<span style="color:#888;font-size:12px">'
                f'📅 <em>{leg.event.title}</em> (ends {_fmt(ee)})</span>',
                indent=True
            )
        else:
            row(
                f'{time_str} &nbsp; {_car("#1a73e8")} &nbsp;'
                f'{driver_html}'
                f' drops off <strong>{leg.rider}</strong>'
                f' at {leg.destination}'
                + (f' ({eta_note})' if eta_note else '')
                + f' &nbsp; {maps}'
            )
            row(
                f'<span style="color:#888;font-size:12px">'
                f'📅 <em>{leg.event.title}</em> ({_fmt(es)}–{_fmt(ee)})</span>',
                indent=True
            )

    _questions_html()
    _assumptions_html()

    rows.append('<hr style="border:none;border-top:1px solid #eee;margin:12px 0">')
    uber_legs = [l for l in legs if l.uber]
    if uber_legs:
        rows.append(
            f'<p style="font-family:sans-serif;color:#c0392b;font-weight:bold">'
            f'⚠️ {len(uber_legs)} leg(s) need an Uber — see above.</p>'
        )
    else:
        rows.append(
            '<p style="font-family:sans-serif;color:#27ae60">'
            '✅ No conflicts — one car covers everything today. 🚗</p>'
        )

    return (
        '<html><body style="font-family:sans-serif;font-size:14px;color:#333;'
        'max-width:600px;margin:0 auto;padding:16px">\n'
        + "\n".join(rows)
        + "\n</body></html>"
    )


def render_plan(legs: List[Leg], conflicts: List[str], day: datetime,
                assumptions: list = None) -> str:
    lines = [f"DRIVING PLAN — {day:%A, %B %-d, %Y}", "=" * 50, ""]
    if not legs:
        lines.append("No driving needed today — no location-based events.")
        return "\n".join(lines)

    lines.append("Legend: DROPOFF = drive child TO an event, PICKUP = drive child FROM it.\n")
    for leg in legs:
        driver = leg.driver or "** UNASSIGNED — needs a decision **"
        eta_note = f" (~{leg.drive_minutes:.0f} min drive" + (
            f", {leg.distance_km} km)" if leg.distance_km else ")")
        depart = _local(leg.depart_by)
        es, ee = _local(leg.event.start), _local(leg.event.end)
        if leg.self_drive and not leg.uber:
            if leg.kind == "DROPOFF":
                lines.append(
                    f"  {_fmt(depart)}  {driver:8s} drives themself "
                    f"to {leg.destination}{eta_note}\n"
                    f"          for '{leg.event.title}' ({_fmt(es)}-{_fmt(ee)})"
                )
            else:
                lines.append(
                    f"  {_fmt(depart)}  {driver:8s} drives themself home "
                    f"from {leg.origin}{eta_note}\n"
                    f"          ('{leg.event.title}' ends {_fmt(ee)})"
                )
        elif leg.uber:
            lines.append(
                f"  {_fmt(depart)}  ⚠️  UBER  drives {leg.rider:6s} "
                f"[{leg.kind}] {leg.origin} -> {leg.destination}{eta_note}\n"
                f"          for '{leg.event.title}' ({_fmt(es)}-{_fmt(ee)})\n"
                f"          ↳ {leg.conflict_reason}"
            )
        elif leg.kind == "PICKUP":
            lines.append(
                f"  {_fmt(depart)}  {driver:8s} leaves to pick up {leg.rider:6s} "
                f"→ {leg.origin}{eta_note}, home by {_fmt(_local(leg.arrive_by))}\n"
                f"          for '{leg.event.title}' (ends {_fmt(ee)})"
            )
        else:
            lines.append(
                f"  {_fmt(depart)}  {driver:8s} drives {leg.rider:6s} "
                f"[DROPOFF] {leg.origin} -> {leg.destination}{eta_note}\n"
                f"          for '{leg.event.title}' ({_fmt(es)}-{_fmt(ee)})"
            )

    if assumptions:
        lines.append("\nASSUMPTIONS")
        for a in assumptions:
            lines.append(f"  • {a}")

    uber_legs = [l for l in legs if l.uber]
    if uber_legs:
        lines.append("\n" + "!" * 50)
        lines.append(f"⚠️  {len(uber_legs)} leg(s) need an Uber — see above.")
    else:
        lines.append("\nNo scheduling conflicts detected — one car covers everything. 🚗")

    return "\n".join(lines)
