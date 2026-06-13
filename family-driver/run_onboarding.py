#!/usr/bin/env python3
"""Launch the local onboarding + account web app.

Run from the family-driver directory:
    python run_onboarding.py
then open http://127.0.0.1:5000 in your browser.

This serves only on localhost. It configures the planner (writes .env); it does
not fetch calendars or send the daily plan itself.
"""
import os

from web.app import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  Onboarding app running at  http://127.0.0.1:{port}\n"
          f"  Press Ctrl+C to stop.\n")
    app.run(host="127.0.0.1", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
