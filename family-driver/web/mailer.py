"""Send transactional emails (verification codes, password-reset links) for the
onboarding app.

Primary path: the Gmail API, reusing the same OAuth credentials/token the
planner uses to send the daily summary (email_draft.gmail_draft).

Fallback: if Gmail isn't configured yet (no token.json / credentials), the
message is written to web/data/last_email.txt so local setup isn't blocked.
The code/link is NEVER shown in the browser — the recipient must read it from
their inbox (or, during local setup, from that file).
"""
import os
from datetime import datetime

from googleapiclient.discovery import build

from email_draft import gmail_draft

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_FALLBACK_FILE = os.path.join(_DATA_DIR, "last_email.txt")


def send_email(to: str, subject: str, body: str) -> dict:
    """Try to send via Gmail. Returns {"delivered": bool, "via": str}.

    Never raises on delivery failure — falls back to a local file so the
    developer can complete setup. Always reports honestly which path was used.
    """
    try:
        creds = gmail_draft._get_credentials()
        service = build("gmail", "v1", credentials=creds)
        raw = gmail_draft._build_message(subject, body, to)
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"delivered": True, "via": "gmail"}
    except Exception as exc:  # noqa: BLE001 — any auth/network error → fallback
        _write_fallback(to, subject, body, str(exc))
        return {"delivered": False, "via": "file", "error": str(exc)}


def _write_fallback(to, subject, body, error):
    os.makedirs(_DATA_DIR, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    with open(_FALLBACK_FILE, "w") as f:
        f.write(f"[{stamp}] Gmail send failed ({error})\n")
        f.write(f"To: {to}\nSubject: {subject}\n\n{body}\n")
    try:
        os.chmod(_FALLBACK_FILE, 0o600)
    except OSError:
        pass
