# family-driver — Version 0.1

Generates a daily one-car pickup/dropoff driving plan for a household by:

1. Pulling today's events (with locations) from **Google Calendar**, **Outlook
   / Microsoft 365**, and (optionally) a child's **TeamSnap** team.
2. Lining them up chronologically into a single timeline.
3. Building a driving plan that assigns each leg to one of the household's
   **drivers** (parents), respecting the number of shared cars, and flagging
   any overlaps that can't be covered (suggesting Uber).
4. Estimating traffic-aware drive time/distance for each leg with the **Google
   Maps Routes API**.
5. Emailing a formatted summary (with per-leg Google Maps links) to the
   configured recipients, and accepting email replies that answer open
   questions (missing locations / attendees).

There are **no family names hard-coded** anywhere — every household value lives
in `.env`, which the onboarding web app writes for you.

## What's new in 0.1

- **Onboarding web app** (`web/`, run via `run_onboarding.py`): a local site to
  create an account and configure a household — drivers vs. non-drivers, home
  address, number of cars, calendar credentials, and summary recipients.
- **Accounts**: email + password login with salted password hashing
  (`auth_store.json`, never committed), **email-inbox verification**, and
  **password reset** by emailed link.
- **Fully generalized config**: drivers/children, colours, calendars, TeamSnap
  person, and known locations all come from `.env`.

## Quick start (onboarding)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_onboarding.py        # open http://127.0.0.1:5000
```

Create an account, verify your email, then fill in the household form. It
writes your local `.env` (and saves any pasted Google OAuth client JSON to
`credentials.json`). You can return to `/onboard` anytime to edit.

> The onboarding app serves on **localhost only**. Passwords are stored as
> salted hashes; verification codes and reset tokens are stored hashed with
> short expiries. PII goes to `.env`; none of these files are committed
> (see `.gitignore`).

## Credentials you'll need

| What | Where to get it |
|---|---|
| Google OAuth client (`credentials.json`) | Google Cloud Console → APIs & Services → Credentials → "OAuth client ID" → Desktop app. Enable the **Google Calendar API** and **Gmail API**. |
| Google Maps API key | Google Cloud Console → enable the **Routes API**, then create an API key. |
| Microsoft Graph app (optional) | [Azure Portal](https://portal.azure.com) → App registrations → enable public client flows → add `Calendars.Read`. |
| TeamSnap token (optional) | Register an app at https://auth.teamsnap.com or generate a personal token. |

## Run the planner

```bash
python main.py                    # print today's plan
python main.py --date 2026-06-10  # plan for a specific date
python main.py --tomorrow         # plan for tomorrow
python main.py --draft-email      # also create a Gmail draft
python main.py --send             # email all recipients
python main.py --check-replies    # apply emailed answers, send an updated plan
```

The first run opens a browser for Google OAuth consent (cached in `token.json`).

## Notes on the algorithm

See `planner/driving_plan.py`. Every event generates a DROPOFF leg and a PICKUP
leg; legs are walked chronologically; the shared car can only do one leg at a
time; each leg goes to whichever driver is free. A driver going alone to their
own event drives themself. Anything that can't be covered is surfaced as a
needs-Uber conflict.

Keep `.env`, `credentials.json`, `token.json`, and `auth_store.json` out of
source control (already covered by `.gitignore`).
