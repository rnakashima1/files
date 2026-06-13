"""Flask onboarding + account web app for the family driving planner.

Routes
------
  /signup            create an account (email + password)
  /verify            confirm the email-inbox verification code
  /login  /logout    session login
  /forgot  /reset    password reset by emailed link
  /onboard           household setup (people, address, #cars, calendars,
                     recipients) — writes the planner's .env
  /done              confirmation
  /draft-today       run the planner now and create a Gmail draft of the plan

Run it with web/run.py (or the project README's code word). This app
configures the planner and can kick off a one-off plan draft on demand.
"""
import os
import subprocess
import sys
import secrets
import tempfile
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (Flask, flash, redirect, render_template, request,
                   session, url_for)

import config
from web import env_writer
from web.auth import UserStore, AuthError
from web.mailer import send_email

app = Flask(__name__)
app.secret_key = env_writer.ensure_secret_key()
store = UserStore()


# --------------------------------------------------------------------------
# CSRF + auth helpers
# --------------------------------------------------------------------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


@app.context_processor
def inject_csrf():
    return {"csrf_token": csrf_token}


def _csrf_ok():
    sent = request.form.get("_csrf", "")
    return sent and secrets.compare_digest(sent, session.get("_csrf", ""))


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


@app.before_request
def _guard_csrf():
    if request.method == "POST" and not _csrf_ok():
        flash("Your session expired. Please try again.", "error")
        return redirect(request.path)


# --------------------------------------------------------------------------
# Account flows
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("onboard") if session.get("user") else url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pw = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if pw != confirm:
            flash("Passwords don't match.", "error")
            return render_template("signup.html", email=email)
        try:
            code = store.create_user(email, pw)
        except AuthError as e:
            flash(str(e), "error")
            return render_template("signup.html", email=email)
        result = _send_verification(email, code)
        flash(result, "info")
        return redirect(url_for("verify", email=email))
    return render_template("signup.html", email="")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    email = request.values.get("email", "").strip()
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        try:
            store.verify_email(email, code)
        except AuthError as e:
            flash(str(e), "error")
            return render_template("verify.html", email=email)
        session["user"] = store._key(email)
        flash("Email verified — welcome! Let's set up your household.", "info")
        return redirect(url_for("onboard"))
    return render_template("verify.html", email=email)


@app.route("/resend-code", methods=["POST"])
def resend_code():
    email = request.form.get("email", "").strip()
    try:
        code = store.new_verification_code(email)
        flash(_send_verification(email, code), "info")
    except AuthError as e:
        flash(str(e), "error")
    return redirect(url_for("verify", email=email))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pw = request.form.get("password", "")
        try:
            store.check_login(email, pw)
        except AuthError as e:
            flash(str(e), "error")
            return render_template("login.html", email=email)
        session.clear()
        session["user"] = store._key(email)
        return redirect(url_for("onboard"))
    return render_template("login.html", email="")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        token = store.create_reset_token(email)
        if token:
            link = url_for("reset", email=email, token=token, _external=True)
            send_email(email, "Reset your driving-planner password",
                       f"Use this link within 1 hour to reset your password:\n\n{link}\n\n"
                       "If you didn't request this, you can ignore this email.")
        # Same message whether or not the account exists.
        flash("If that email has an account, a reset link is on its way.", "info")
        return redirect(url_for("login"))
    return render_template("forgot.html")


@app.route("/reset", methods=["GET", "POST"])
def reset():
    email = request.values.get("email", "").strip()
    token = request.values.get("token", "").strip()
    if request.method == "POST":
        pw = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if pw != confirm:
            flash("Passwords don't match.", "error")
            return render_template("reset.html", email=email, token=token)
        try:
            store.reset_password(email, token, pw)
        except AuthError as e:
            flash(str(e), "error")
            return render_template("reset.html", email=email, token=token)
        flash("Password updated — please log in.", "info")
        return redirect(url_for("login"))
    return render_template("reset.html", email=email, token=token)


# --------------------------------------------------------------------------
# Onboarding
# --------------------------------------------------------------------------
@app.route("/onboard", methods=["GET", "POST"])
@login_required
def onboard():
    if request.method == "POST":
        return _save_onboarding()
    # Pre-fill from any existing config so re-running edits current settings.
    cal_by_name = {name: cid for cid, name in config.GOOGLE_CALENDAR_MAP.items()}
    roster = set(config.DRIVERS) | set(config.NON_DRIVERS)
    people = (
        [{"name": n, "role": "driver", "calid": cal_by_name.get(n, "")}
         for n in config.DRIVERS]
        + [{"name": n, "role": "child", "calid": cal_by_name.get(n, "")}
           for n in config.NON_DRIVERS])
    extras = [{"calid": cid, "label": name}
              for cid, name in config.GOOGLE_CALENDAR_MAP.items() if name not in roster]
    existing = {
        "home_address": config.HOME_ADDRESS,
        "num_cars": config.NUM_CARS,
        "people": people,
        "extras": extras,
        "recipients": config.PLAN_RECIPIENTS,
        "maps_key": config.GOOGLE_MAPS_API_KEY,
        "teamsnap_team": config.TEAMSNAP_TEAM_NAME,
        "teamsnap_person": config.TEAMSNAP_PERSON,
        "ms_client_id": config.MS_CLIENT_ID,
        "ms_tenant_id": config.MS_TENANT_ID,
        "outlook_owner": (config.OUTLOOK_CALENDAR_MAP or {}).get("me", ""),
    }
    return render_template("onboard.html", account=session.get("user"), existing=existing)


def _save_onboarding():
    f = request.form
    names = f.getlist("person_name")
    roles = f.getlist("person_role")
    calids = f.getlist("person_calid")

    drivers, non_drivers, cal_pairs = [], [], []
    for i, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        role = roles[i] if i < len(roles) else "child"
        (drivers if role == "driver" else non_drivers).append(name)
        calid = (calids[i].strip() if i < len(calids) else "")
        if calid:
            cal_pairs.append((calid, name))

    if not drivers:
        flash("Add at least one parent/driver.", "error")
        return redirect(url_for("onboard"))

    # Extra shared calendars (id:label rows), e.g. a Family calendar.
    for cid, label in zip(f.getlist("extra_calid"), f.getlist("extra_label")):
        if cid.strip() and label.strip():
            cal_pairs.append((cid.strip(), label.strip()))

    recipients = [r.strip() for r in f.getlist("recipient") if r.strip()]

    updates = {
        "HOME_ADDRESS": f.get("home_address", "").strip(),
        "NUM_CARS": f.get("num_cars", "1").strip() or "1",
        "DRIVERS": env_writer.join_list(drivers),
        "NON_DRIVERS": env_writer.join_list(non_drivers),
        "GOOGLE_CALENDAR_MAP": env_writer.join_pairs(cal_pairs),
        "PLAN_RECIPIENTS": env_writer.join_list(recipients),
    }

    # Optional Outlook owner mapping.
    outlook_owner = f.get("outlook_owner", "").strip()
    if outlook_owner:
        updates["OUTLOOK_CALENDAR_MAP"] = f"me:{outlook_owner}"
        updates["MS_CLIENT_ID"] = f.get("ms_client_id", "").strip()
        updates["MS_TENANT_ID"] = f.get("ms_tenant_id", "common").strip() or "common"

    # Optional TeamSnap.
    ts_token = f.get("teamsnap_token", "").strip()
    if ts_token:
        updates["TEAMSNAP_ACCESS_TOKEN"] = ts_token
        updates["TEAMSNAP_TEAM_NAME"] = f.get("teamsnap_team", "").strip()
        updates["TEAMSNAP_PERSON"] = f.get("teamsnap_person", "").strip()

    env_writer.update_env(updates)

    # Optional pasted Google OAuth client JSON.
    creds_json = f.get("google_credentials", "").strip()
    cred_note = ""
    if creds_json:
        try:
            env_writer.save_credentials_json(creds_json)
            cred_note = " Google client credentials saved."
        except ValueError as e:
            flash(f"Saved settings, but the Google credentials were not: {e}", "error")
            return redirect(url_for("done"))

    flash("Household settings saved to .env." + cred_note, "info")
    return redirect(url_for("done"))


@app.route("/done")
@login_required
def done():
    return render_template("done.html", today=_pacific_today())


@app.route("/draft-today", methods=["POST"])
@login_required
def draft_today():
    """Build the plan for the chosen date, create a Gmail draft, and show a
    preview of the actual email. Runs main.py in a subprocess so it reads the
    freshly-saved .env; the rendered HTML is captured via --html-out."""
    date = (request.form.get("date") or "").strip() or _pacific_today()
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        flash("Please pick a valid date.", "error")
        return redirect(url_for("done"))

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fd, html_path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    email_html, ok, error = "", False, ""
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", "--date", date,
             "--draft-email", "--html-out", html_path],
            cwd=base, capture_output=True, text=True, timeout=180)
        ok = proc.returncode == 0
        if ok:
            with open(html_path) as f:
                email_html = f.read()
        else:
            error = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
            error = error[0]
    except subprocess.TimeoutExpired:
        error = "Timed out after 3 minutes while building the plan."
    except Exception as exc:  # noqa: BLE001
        error = f"Couldn't run the planner: {exc}"
    finally:
        try:
            os.remove(html_path)
        except OSError:
            pass

    nice_date = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %-d, %Y")
    return render_template("plan_result.html", ok=ok, email_html=email_html,
                           error=error, date=nice_date,
                           recipients=", ".join(config.PLAN_RECIPIENTS))


def _pacific_today():
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
def _send_verification(email, code):
    result = send_email(
        email, "Your driving-planner verification code",
        f"Welcome! Your email verification code is:\n\n    {code}\n\n"
        "Enter it on the verification page. It expires in 30 minutes.")
    if result["delivered"]:
        return f"A 6-digit verification code was emailed to {email}."
    return ("Couldn't send email automatically — the verification code was "
            "written to web/data/last_email.txt (configure Gmail to email it "
            "for real).")


if __name__ == "__main__":
    # Local only. Debug off by default; set FLASK_DEBUG=1 to enable.
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")),
            debug=os.getenv("FLASK_DEBUG") == "1")
