"""Read and update the planner's .env file from onboarding form data.

All household PII (names, addresses, calendar IDs, recipient emails, API keys
and tokens) is persisted here, in the local .env that config.py reads. Updates
are done key-by-key so existing keys/comments are preserved, and the file is
written with 0600 permissions.
"""
import json
import os
import secrets

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(_BASE, ".env")
CREDENTIALS_PATH = os.path.join(_BASE, "credentials.json")


def _read_lines(path):
    try:
        with open(path) as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return []


def _secure(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def update_env(updates: dict, env_path: str = ENV_PATH):
    """Set each KEY=value in updates, updating in place or appending. Values are
    written verbatim (no quoting); callers should pre-join lists with commas."""
    lines = _read_lines(env_path)
    remaining = dict(updates)

    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# --- added/updated by onboarding ---")
        for key, val in remaining.items():
            out.append(f"{key}={val}")

    with open(env_path, "w") as f:
        f.write("\n".join(out) + "\n")
    _secure(env_path)


def ensure_secret_key(env_path: str = ENV_PATH) -> str:
    """Ensure FLASK_SECRET_KEY exists in .env; generate one if missing."""
    for line in _read_lines(env_path):
        if line.strip().startswith("FLASK_SECRET_KEY="):
            val = line.split("=", 1)[1].strip()
            if val:
                return val
    key = secrets.token_urlsafe(48)
    update_env({"FLASK_SECRET_KEY": key}, env_path)
    return key


def save_credentials_json(content: str, path: str = CREDENTIALS_PATH):
    """Validate and save a pasted Google OAuth client-secrets JSON blob."""
    data = json.loads(content)  # raises ValueError if not valid JSON
    if not isinstance(data, dict) or not ({"installed", "web"} & set(data)):
        raise ValueError(
            "That doesn't look like a Google OAuth client file "
            "(expected an 'installed' or 'web' top-level key).")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    _secure(path)


def join_list(values):
    """Join a list of strings into a comma-separated .env value, skipping blanks."""
    return ",".join(v.strip() for v in values if v and v.strip())


def join_pairs(pairs):
    """Join [(a, b), ...] into 'a:b,c:d', skipping entries with a blank key."""
    return ",".join(f"{a.strip()}:{b.strip()}" for a, b in pairs if a and a.strip())
