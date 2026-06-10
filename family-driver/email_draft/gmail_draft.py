"""Creates (but does NOT send) a Gmail draft containing the day's driving plan,
addressed to config.PLAN_RECIPIENT_EMAIL. Reuses the same Google OAuth
credentials/token as the Calendar module (just needs an additional scope).

Sending is left as a deliberate manual step — open Gmail, review, hit Send.
"""
import base64
import json
import os
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _get_credentials():
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(config.GOOGLE_OAUTH_TOKEN_FILE, SCOPES)
    except FileNotFoundError:
        pass
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.GOOGLE_OAUTH_CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(config.GOOGLE_OAUTH_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def _build_message(subject: str, body: str, to: str) -> str:
    """Build a base64url-encoded RFC 2822 message. Detects HTML vs plain text."""
    from email.mime.multipart import MIMEMultipart
    if body.lstrip().startswith("<"):
        msg = MIMEMultipart("alternative")
        msg["to"] = to
        msg["subject"] = subject
        msg.attach(MIMEText(body, "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")
        msg["to"] = to
        msg["subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_plan_draft(subject: str, body: str, to_email: str = None) -> str:
    """Creates a Gmail draft and returns its draft ID. Does not send it."""
    to_email = to_email or (config.PLAN_RECIPIENTS[0] if config.PLAN_RECIPIENTS else "")
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    raw = _build_message(subject, body, to_email)
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft["id"]


def send_plan(subject: str, body: str, to_emails: list = None,
              day_key: str = None) -> str:
    """Sends the plan email immediately. Returns the sent message ID.

    Records the thread in plan_state.json so --check-replies can watch for
    answers to the plan's open questions.
    """
    recipients = to_emails or config.PLAN_RECIPIENTS
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    raw = _build_message(subject, body, ", ".join(recipients))
    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    if day_key:
        _save_state({"day": day_key, "thread_id": sent["threadId"],
                     "subject": subject, "processed": [sent["id"]]})
    return sent["id"]


STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plan_state.json")


def _save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _extract_text(payload) -> str:
    """Pull plain text out of a Gmail message payload (recursing into parts)."""
    import base64 as b64
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return b64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    text = ""
    for part in payload.get("parts", []) or []:
        text += _extract_text(part)
    return text


def fetch_new_replies():
    """Return (state, [(msg_id, sender, text), ...]) for unprocessed replies
    on the most recent plan thread. Skips messages we sent ourselves."""
    state = load_state()
    if not state.get("thread_id"):
        return state, []
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    thread = service.users().threads().get(
        userId="me", id=state["thread_id"], format="full").execute()
    processed = set(state.get("processed", []))
    replies = []
    for msg in thread.get("messages", []):
        if msg["id"] in processed:
            continue
        if "SENT" in (msg.get("labelIds") or []):
            processed.add(msg["id"])
            continue
        headers = {h["name"].lower(): h["value"]
                   for h in msg.get("payload", {}).get("headers", [])}
        text = _extract_text(msg.get("payload", {}))
        replies.append((msg["id"], headers.get("from", ""), text))
    state["processed"] = list(processed)
    return state, replies


def send_reply_on_thread(state: dict, body: str, extra_processed: list = None) -> str:
    """Send an updated plan as a reply on the recorded thread."""
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    subject = state.get("subject", "Driving plan")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    raw = _build_message(subject, body, ", ".join(config.PLAN_RECIPIENTS))
    sent = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": state["thread_id"]}
    ).execute()
    state.setdefault("processed", []).append(sent["id"])
    for mid in extra_processed or []:
        if mid not in state["processed"]:
            state["processed"].append(mid)
    _save_state(state)
    return sent["id"]
