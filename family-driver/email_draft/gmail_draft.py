"""Creates (but does NOT send) a Gmail draft containing the day's driving plan,
addressed to config.PLAN_RECIPIENT_EMAIL. Reuses the same Google OAuth
credentials/token as the Calendar module (just needs an additional scope).

Sending is left as a deliberate manual step — open Gmail, review, hit Send.
"""
import base64
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
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


def send_plan(subject: str, body: str, to_emails: list = None) -> str:
    """Sends the plan email immediately. Returns the sent message ID."""
    recipients = to_emails or config.PLAN_RECIPIENTS
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    raw = _build_message(subject, body, ", ".join(recipients))
    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return sent["id"]
