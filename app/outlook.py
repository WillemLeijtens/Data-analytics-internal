"""Microsoft Graph client for the automatic Outlook import.

Auth model: delegated OAuth via MSAL's device-code flow. You sign in once
interactively (a code you type at microsoft.com/devicelogin); after that the
refresh token in the persisted cache keeps the poller running unattended.
This is the only workable option for a headless server — Microsoft has
retired basic auth (IMAP/POP with a password) for Exchange Online and
Outlook.com, so an "app password" route no longer exists.

Scope is Mail.Read only: the importer reads messages and downloads
attachments, and never modifies or deletes anything in the mailbox.
"""

from __future__ import annotations

import base64
import datetime as dt
import os
from pathlib import Path

import msal
import requests

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]

# Token cache lives beside the database, on the persistent volume, so a
# container rebuild doesn't force a new interactive sign-in.
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "msal_cache.json"


class OutlookError(RuntimeError):
    """Configuration/auth problem worth showing to the user verbatim."""


def _client_id() -> str:
    cid = os.environ.get("AZURE_CLIENT_ID", "").strip()
    if not cid:
        raise OutlookError(
            "AZURE_CLIENT_ID is not set. Register an app in Azure and put its "
            "Application (client) ID in .env — see README."
        )
    return cid


def _authority() -> str:
    # "common" accepts both work/school and personal Microsoft accounts; set
    # AZURE_TENANT_ID to your tenant to restrict it to your organisation.
    tenant = os.environ.get("AZURE_TENANT_ID", "common").strip() or "common"
    return f"https://login.microsoftonline.com/{tenant}"


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(cache.serialize())
        # Refresh tokens are as good as a password for this mailbox.
        os.chmod(CACHE_PATH, 0o600)


def _app(cache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        _client_id(), authority=_authority(), token_cache=cache
    )


def is_connected() -> bool:
    """True when a cached account exists (i.e. someone has signed in)."""
    try:
        cache = _load_cache()
        return bool(_app(cache).get_accounts())
    except OutlookError:
        return False


def signed_in_account() -> str | None:
    try:
        cache = _load_cache()
        accounts = _app(cache).get_accounts()
        return accounts[0].get("username") if accounts else None
    except OutlookError:
        return None


def get_token() -> str:
    """Access token from the cache, refreshed silently. Raises OutlookError
    when no one has signed in yet or the refresh token has expired (e.g. the
    poller was down for months, or a conditional-access policy forced
    re-auth) — in both cases the fix is to run start_device_login again."""
    cache = _load_cache()
    app = _app(cache)
    accounts = app.get_accounts()
    if not accounts:
        raise OutlookError("Not signed in to Outlook yet — start the device login first.")
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    _save_cache(cache)
    if not result or "access_token" not in result:
        raise OutlookError(
            "Outlook sign-in has expired. Run the device login again to reconnect."
        )
    return result["access_token"]


def start_device_login() -> dict:
    """Begin the device-code flow. Returns the flow dict, which carries the
    user_code and verification_uri to show on screen; pass it back to
    finish_device_login() to complete the sign-in."""
    cache = _load_cache()
    app = _app(cache)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise OutlookError(f"Could not start device login: {flow.get('error_description', flow)}")
    return flow


def finish_device_login(flow: dict) -> str:
    """Block until the user completes the sign-in (or the code expires), then
    persist the token cache. Returns the signed-in username."""
    cache = _load_cache()
    app = _app(cache)
    result = app.acquire_token_by_device_flow(flow)
    _save_cache(cache)
    if "access_token" not in result:
        raise OutlookError(f"Sign-in failed: {result.get('error_description', result)}")
    return result.get("id_token_claims", {}).get("preferred_username", "unknown")


def _get(url: str, token: str, **params):
    r = requests.get(
        url, headers={"Authorization": f"Bearer {token}"}, params=params or None, timeout=30
    )
    if r.status_code == 401:
        raise OutlookError("Outlook rejected the token (401) — sign in again.")
    if r.status_code == 403:
        raise OutlookError(
            "Outlook denied access (403). Check that the app has the Mail.Read "
            "delegated permission and that consent was granted."
        )
    r.raise_for_status()
    return r.json()


def find_messages(subject_contains: str, since_days: int = 30, limit: int = 50) -> list[dict]:
    """Messages with attachments received in the last `since_days`, whose
    subject contains `subject_contains` (case-insensitive).

    The subject match is done here rather than in the Graph query on purpose:
    Graph's $filter has no `contains()` for subject, and $search can't be
    combined with $filter/$orderby — so we filter server-side on the cheap,
    reliable predicates (has attachments, recent, newest first) and match the
    subject on the small result set."""
    token = get_token()
    since = (dt.datetime.utcnow() - dt.timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _get(
        f"{GRAPH}/me/messages",
        token,
        **{
            "$filter": f"hasAttachments eq true and receivedDateTime ge {since}",
            "$orderby": "receivedDateTime desc",
            "$top": str(limit),
            "$select": "id,subject,receivedDateTime,from",
        },
    )
    needle = (subject_contains or "").strip().lower()
    out = []
    for m in data.get("value", []):
        subject = m.get("subject") or ""
        if needle and needle not in subject.lower():
            continue
        out.append({
            "id": m["id"],
            "subject": subject,
            "received_at": m.get("receivedDateTime"),
            "from": (m.get("from", {}).get("emailAddress", {}) or {}).get("address"),
        })
    return out


def get_xlsx_attachments(message_id: str) -> list[tuple[str, bytes]]:
    """(filename, bytes) for every .xlsx file attachment on a message.
    Inline/item attachments and other file types are skipped."""
    token = get_token()
    data = _get(f"{GRAPH}/me/messages/{message_id}/attachments", token)
    out = []
    for att in data.get("value", []):
        if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue
        name = att.get("name") or ""
        if not name.lower().endswith(".xlsx"):
            continue
        content = att.get("contentBytes")
        if not content:
            continue
        out.append((name, base64.b64decode(content)))
    return out
