"""Gmail send — one confirmed message at a time.

The user brings their own Google Cloud OAuth client (desktop app type), so no
credentials ship with this project and nothing is sent through a third party.
Scope is ``gmail.send`` only: this code can send a message and cannot read the
user's mailbox.

The consent dance opens a browser, which is hostile in the middle of an MCP
tool call, so authorisation lives in ``mba-mcp auth`` and the send path only
ever refreshes an existing token.
"""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from pathlib import Path

from .config import Config

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


class GmailNotConfigured(RuntimeError):
    """Gmail credentials are missing, expired, or the libraries aren't installed."""


def _load_libs():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise GmailNotConfigured(
            "Gmail support needs the optional dependencies: "
            "pip install 'mba-mcp[gmail]'"
        ) from exc
    return Request, Credentials, InstalledAppFlow, build


def valid_recipient(address: str | None) -> bool:
    """One address, no lists — bulk sending is a hard non-goal."""
    return bool(address and _EMAIL_RE.match(address.strip()))


def build_message(to: str, subject: str, body: str, sender: str | None = None) -> dict:
    """Build the single raw message payload the Gmail API expects."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if sender:
        message["From"] = sender
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return {"raw": raw}


def authorize(config: Config) -> Path:
    """Run the OAuth consent flow and cache the token. Interactive; CLI only."""
    Request, Credentials, InstalledAppFlow, _ = _load_libs()

    if not config.gmail_client_secret.is_file():
        raise GmailNotConfigured(
            f"No OAuth client secret at {config.gmail_client_secret}. Create a "
            "Desktop-app OAuth client in Google Cloud, download the JSON, and "
            "point GMAIL_OAUTH_CLIENT_SECRET at it."
        )

    creds = _cached_credentials(config, Credentials, Request)
    if creds is None or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.gmail_client_secret), SCOPES
        )
        creds = flow.run_local_server(port=0)
        _save_token(config.gmail_token, creds.to_json())
    return config.gmail_token


def _cached_credentials(config: Config, Credentials, Request):
    if not config.gmail_token.is_file():
        return None
    creds = Credentials.from_authorized_user_file(str(config.gmail_token), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(config.gmail_token, creds.to_json())
    return creds


def _save_token(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)


def send_one(config: Config, to: str, subject: str, body: str) -> str:
    """Send exactly one message from the user's own Gmail. Returns its id.

    Callers are responsible for the human confirmation; this function performs
    a single API call and never iterates over recipients.
    """
    if not valid_recipient(to):
        raise GmailNotConfigured(f"'{to}' is not a single valid email address.")

    Request, Credentials, _, build = _load_libs()
    creds = _cached_credentials(config, Credentials, Request)
    if creds is None or not creds.valid:
        raise GmailNotConfigured(
            "Gmail is not authorised yet (or the token expired). Run "
            "'mba-mcp auth' in a terminal to grant access, then try again."
        )

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    sent = service.users().messages().send(
        userId="me", body=build_message(to.strip(), subject, body)
    ).execute()
    return sent.get("id", "")
