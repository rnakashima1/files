# family-driver

Generates a daily one-car pickup/dropoff driving plan for the household by:

1. Pulling today's events (with locations) from **Google Calendar**, **Outlook
   / Microsoft 365**, and **TeamSnap** (the "Sanjo's Fury" team).
2. Lining them up chronologically into a single timeline.
3. Building a driving plan that assigns each leg to **Komaki** or **Ryan**
   (the only two drivers — **Oto**, **Lara**, and **Sanjo** can't drive),
   respecting the fact that there is **only one car**, and flagging any
   overlaps that can't be covered.
4. Estimating drive time/distance for each leg with the **Google Maps Routes
   API**, using traffic-aware routing for the actual departure time.
5. Optionally drafting (not sending) a summary email to Komaki via Gmail.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the values below
```

You'll need to obtain, and put into `.env`:

| What | Where to get it |
|---|---|
| Google OAuth client (`credentials.json`) | Google Cloud Console → APIs & Services → Credentials → "OAuth client ID" → Desktop app. Enable the **Google Calendar API** and **Gmail API** on the project. |
| Google Maps API key | Google Cloud Console → enable the **Routes API**, then create an API key (restrict it to that API). |
| Microsoft Graph app registration | [Azure Portal](https://portal.azure.com) → App registrations → New registration → enable "Allow public client flows" → add `Calendars.Read` delegated permission. |
| TeamSnap OAuth token | Register an app at https://auth.teamsnap.com (TeamSnap API v3), or generate a personal access token from your account. |
| Household addresses & names | Edit `HOME_ADDRESS`, `DRIVERS`, `NON_DRIVERS` in `.env`. |

Then edit the `GOOGLE_CALENDAR_MAP` / `OUTLOOK_CALENDAR_MAP` dictionaries at
the top of `main.py` so each family member's calendar is mapped to their name
— these are placeholders and will need to match your actual setup (e.g. each
kid might have their own Google Calendar, shared with the household account).

## Run

```bash
python main.py                  # print today's plan
python main.py --date 2026-06-10  # plan for a specific date
python main.py --draft-email    # also create a Gmail draft addressed to Komaki
```

The first run will open a browser window for Google OAuth consent (token is
cached in `token.json`) and print a Microsoft device-code link for Outlook
auth. Subsequent runs reuse the cached tokens — this is what makes it
practical to re-run daily (e.g. via a cron job, GitHub Actions schedule, or a
small wrapper web app that calls `main.main()`).

## Notes on the driving-plan algorithm

See `planner/driving_plan.py` for the full logic. In short: every kid event
generates a DROPOFF leg (drive them there) and a PICKUP leg (drive them to
wherever's next, or home). Legs are walked in chronological order; the single
shared car can only do one leg at a time, and each leg is assigned to
whichever driver is free and not double-booked on their own calendar
(alternating Komaki/Ryan to balance the load). Anything that can't be covered
by one car and two drivers is surfaced as a **conflict** at the bottom of the
plan — e.g. "carpool with a teammate" or "reschedule" situations that need a
human decision.

## Re-running this regularly

This is plain Python with no server dependencies, so the simplest path to
"runs repeatedly" is:
- a daily **cron job** / **launchd** task calling `python main.py --draft-email`, or
- a **GitHub Actions** scheduled workflow (`on: schedule`) that runs it and
  emails/Slacks the output, or
- wrapping `main()` in a tiny Flask/FastAPI route for an on-demand "refresh
  today's plan" button in a small web app.

Whichever you choose, keep `.env`, `credentials.json`, and `token.json` out
of source control (already covered by `.gitignore`) — store them as repo/CI
secrets instead.
