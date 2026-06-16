"""Interpret a free-form email reply into structured driving-plan directives,
using Claude (Anthropic API).

The daily plan email asks open questions and accepts replies. People rarely
answer in the rigid "Event: answer" format the keyword parser expects — they
write prose ("Sanjo has a ride, so skip those", "Ryan drives Lara to ATA").
This module hands that prose to Claude along with the day's events and gets back
the same directive dicts the override system already applies (skip / location /
person / driver / start / end).

Credential model: a single SERVICE credential processes all replies — end users
are never asked for a key. Resolution order: ANTHROPIC_API_KEY, then
ANTHROPIC_AUTH_TOKEN (an OAuth token from a Claude subscription), else the
SDK's default resolution (env / `ant auth login` profile) when
ANTHROPIC_USE_LOGIN is set. With none configured, returns None so the caller
falls back to the keyword parser.
"""
import json
import os
from zoneinfo import ZoneInfo

import config

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

SYSTEM = (
    "You convert a parent's free-form email reply into structured edits to a "
    "family's one-car daily driving plan. You are given the day's events. Map "
    "the reply to zero or more directives, each targeting exactly one event by "
    "its exact title from the provided list.\n\n"
    "Each directive is a JSON object: {\"event_title\": <one of the given "
    "titles>, plus any of these optional fields the reply clearly implies}:\n"
    "- \"skip\": true  — the event needs no driving from this family (the child "
    "has a ride from someone else, it's cancelled, or a parent is going on "
    "their own).\n"
    "- \"location\": a full street address the reply provides for the event.\n"
    "- \"person\": reassign the event to this family member (must be one of the "
    "given names).\n"
    "- \"driver\": force this parent to drive the event (must be one of the "
    "given drivers).\n"
    "- \"start\" / \"end\": corrected event times as 24-hour \"HH:MM\".\n\n"
    "Rules: only use event titles from the list. Never invent an address. If "
    "part of the reply doesn't clearly map to an event, leave it out. Respond "
    "with ONLY a JSON object of the form {\"directives\": [ ... ]} — no prose, "
    "no markdown fences."
)


def _events_brief(events):
    brief = []
    for e in events:
        s = e.start.astimezone(LOCAL_TZ) if e.start.tzinfo else e.start
        en = e.end.astimezone(LOCAL_TZ) if e.end.tzinfo else e.end
        brief.append({
            "title": e.title,
            "person": e.person,
            "start": s.strftime("%H:%M"),
            "end": en.strftime("%H:%M"),
            "location": e.location or "",
        })
    return brief


def _make_client():
    """Build an Anthropic client from the service credential, or None if no
    credential is configured."""
    if not (config.ANTHROPIC_API_KEY or config.ANTHROPIC_AUTH_TOKEN
            or os.getenv("ANTHROPIC_USE_LOGIN")):
        return None
    import anthropic
    if config.ANTHROPIC_API_KEY:
        return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    if config.ANTHROPIC_AUTH_TOKEN:
        return anthropic.Anthropic(auth_token=config.ANTHROPIC_AUTH_TOKEN)
    return anthropic.Anthropic()  # resolve from env / `ant auth login` profile


def interpret(text, events):
    """Return a list of (event_title, fix_dict), or None when the LLM is
    unavailable (the caller should then fall back to the keyword parser)."""
    try:
        client = _make_client()
    except ImportError:
        return None
    if client is None:
        return None
    try:
        payload = {
            "drivers": list(config.DRIVERS),
            "children": list(config.NON_DRIVERS),
            "events": _events_brief(events),
            "reply": text,
        }
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
        raw = "".join(b.text for b in resp.content
                      if getattr(b, "type", None) == "text")
        data = _extract_json(raw)
        return _to_pairs(data) if data else []
    except Exception as exc:  # noqa: BLE001 — never crash the planner on this
        print(f"  (LLM reply interpretation failed — {exc}); using keyword parser")
        return None


def _extract_json(raw):
    raw = (raw or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except ValueError:
        return None


def _to_pairs(data):
    valid_people = set(config.DRIVERS) | set(config.NON_DRIVERS)
    drivers = set(config.DRIVERS)
    pairs = []
    for d in data.get("directives", []):
        if not isinstance(d, dict):
            continue
        title = d.get("event_title") or d.get("title")
        if not title:
            continue
        fix = {}
        if d.get("skip") is True:
            fix["skip"] = True
        if d.get("location"):
            fix["location"] = d["location"]
        if d.get("person") in valid_people:
            fix["person"] = d["person"]
        if d.get("driver") in drivers:
            fix["driver"] = d["driver"]
        for k in ("start", "end"):
            v = d.get(k)
            if isinstance(v, str) and ":" in v:
                fix[k] = v
        if fix:
            pairs.append((title, fix))
    return pairs
