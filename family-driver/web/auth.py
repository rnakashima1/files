"""Local account store: signup, password hashing, email verification, login,
and password reset.

Security model
--------------
- Passwords are never stored in plaintext. We keep only a salted hash
  (werkzeug PBKDF2-SHA256) in auth_store.json, written with 0600 permissions.
- Email-verification codes and password-reset tokens are also stored only as
  hashes, with short expiry windows, and compared in constant time.
- Login and verification attempts are rate-limited with a temporary lockout.

This file deals only with credentials. Household PII (names, addresses,
calendar IDs, recipients) lives in the .env, written by env_writer.py.
"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash, check_password_hash

# PBKDF2-SHA256 is supported everywhere; werkzeug's newer scrypt default needs an
# OpenSSL build that some Python installs (e.g. macOS LibreSSL) don't provide.
_HASH_METHOD = "pbkdf2:sha256"


def _hash(value: str) -> str:
    return generate_password_hash(value, method=_HASH_METHOD)


# auth_store.json sits next to the planner code (gitignored — never committed).
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_FILE = os.path.join(_BASE, "auth_store.json")

VERIFY_CODE_TTL = timedelta(minutes=30)
RESET_TOKEN_TTL = timedelta(hours=1)
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
MIN_PASSWORD_LEN = 8


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _parse(s):
    return datetime.fromisoformat(s) if s else None


class AuthError(Exception):
    """Raised for any authentication failure with a user-safe message."""


class UserStore:
    def __init__(self, path: str = STORE_FILE):
        self.path = path
        self._users = self._load()

    # ---- persistence ----------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self):
        # Write then chmod 0600 so password hashes aren't world-readable.
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._users, f, indent=2)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _key(email: str) -> str:
        return (email or "").strip().lower()

    def get(self, email: str) -> dict:
        return self._users.get(self._key(email))

    def exists(self, email: str) -> bool:
        return self._key(email) in self._users

    # ---- signup + verification -----------------------------------------
    def create_user(self, email: str, password: str) -> str:
        """Create an unverified account and return a fresh verification code."""
        email_k = self._key(email)
        if not email_k or "@" not in email_k:
            raise AuthError("Please enter a valid email address.")
        if self.exists(email_k):
            raise AuthError("An account with that email already exists.")
        if len(password or "") < MIN_PASSWORD_LEN:
            raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")

        code = self._new_code()
        self._users[email_k] = {
            "email": email_k,
            "password_hash": _hash(password),
            "email_verified": False,
            "created_at": _iso(_now()),
            "verify": {
                "code_hash": _hash(code),
                "expires": _iso(_now() + VERIFY_CODE_TTL),
                "attempts": 0,
            },
            "reset": None,
            "failed_logins": 0,
            "locked_until": None,
        }
        self._save()
        return code

    def new_verification_code(self, email: str) -> str:
        """Re-issue a verification code (e.g. the first one expired)."""
        user = self.get(email)
        if not user:
            raise AuthError("No account with that email.")
        if user["email_verified"]:
            raise AuthError("That email is already verified.")
        code = self._new_code()
        user["verify"] = {
            "code_hash": _hash(code),
            "expires": _iso(_now() + VERIFY_CODE_TTL),
            "attempts": 0,
        }
        self._save()
        return code

    def verify_email(self, email: str, code: str) -> bool:
        user = self.get(email)
        if not user or not user.get("verify"):
            raise AuthError("Nothing to verify for that account.")
        v = user["verify"]
        if _parse(v["expires"]) < _now():
            raise AuthError("That code has expired — request a new one.")
        if v.get("attempts", 0) >= MAX_FAILED_LOGINS:
            raise AuthError("Too many attempts — request a new code.")
        if not check_password_hash(v["code_hash"], (code or "").strip()):
            v["attempts"] = v.get("attempts", 0) + 1
            self._save()
            raise AuthError("That code is incorrect.")
        user["email_verified"] = True
        user["verify"] = None
        self._save()
        return True

    # ---- login ----------------------------------------------------------
    def check_login(self, email: str, password: str) -> dict:
        user = self.get(email)
        # Run a dummy hash check even when the user is missing, so response
        # time doesn't reveal whether the email exists.
        if not user:
            check_password_hash(
                "pbkdf2:sha256:600000$x$" + "0" * 64, password or "")
            raise AuthError("Incorrect email or password.")

        locked = _parse(user.get("locked_until"))
        if locked and locked > _now():
            raise AuthError("Account temporarily locked. Try again later.")

        if not check_password_hash(user["password_hash"], password or ""):
            user["failed_logins"] = user.get("failed_logins", 0) + 1
            if user["failed_logins"] >= MAX_FAILED_LOGINS:
                user["locked_until"] = _iso(_now() + LOCKOUT)
                user["failed_logins"] = 0
            self._save()
            raise AuthError("Incorrect email or password.")

        if not user["email_verified"]:
            raise AuthError("Please verify your email before logging in.")

        user["failed_logins"] = 0
        user["locked_until"] = None
        self._save()
        return user

    # ---- password reset -------------------------------------------------
    def create_reset_token(self, email: str):
        """Return (token, exists). If no such account, token is None — callers
        should show the same message regardless, to avoid leaking which emails
        are registered."""
        user = self.get(email)
        if not user:
            return None
        token = secrets.token_urlsafe(32)
        user["reset"] = {
            "token_hash": _hash(token),
            "expires": _iso(_now() + RESET_TOKEN_TTL),
        }
        self._save()
        return token

    def reset_password(self, email: str, token: str, new_password: str):
        user = self.get(email)
        if not user or not user.get("reset"):
            raise AuthError("This reset link is invalid or has expired.")
        r = user["reset"]
        if _parse(r["expires"]) < _now():
            raise AuthError("This reset link has expired — request a new one.")
        if not check_password_hash(r["token_hash"], (token or "").strip()):
            raise AuthError("This reset link is invalid or has expired.")
        if len(new_password or "") < MIN_PASSWORD_LEN:
            raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
        user["password_hash"] = _hash(new_password)
        user["reset"] = None
        # A successful reset also clears any lockout.
        user["failed_logins"] = 0
        user["locked_until"] = None
        self._save()
        return True

    @staticmethod
    def _new_code() -> str:
        # 6-digit numeric code, zero-padded.
        return f"{secrets.randbelow(1_000_000):06d}"
