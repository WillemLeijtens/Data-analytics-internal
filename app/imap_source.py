"""IMAP mail source for the automatic import — the "forwarding mailbox"
route.

Instead of granting the app access to your own mailbox, you set an Outlook
rule that forwards the weekly report mails to a dedicated throwaway mailbox,
and the app reads only that one. If its credentials ever leaked, the blast
radius is a mailbox that contains nothing but forwarded reports.

Note on providers: a second mailbox inside your own Microsoft 365 tenant
will NOT work here — Microsoft disabled basic auth (IMAP with a password)
for Exchange Online, so that route needs OAuth (see outlook.py). Use a
non-Microsoft mailbox: Gmail with an App Password, or a mailbox at your web
host / another provider.

Configured entirely through environment variables (never the database), so
the password lives in .env alongside the app password:
    IMAP_HOST, IMAP_PORT (993), IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER (INBOX)

Messages are read with BODY.PEEK[...] so the mailbox is never modified — no
mails get marked as read, moved or deleted.
"""

from __future__ import annotations

import datetime as dt
import email
import email.header
import email.utils
import imaplib
import os
import re
from contextlib import contextmanager


class ImapError(RuntimeError):
    """Configuration/connection problem worth showing to the user verbatim."""


def _cfg() -> dict:
    host = os.environ.get("IMAP_HOST", "").strip()
    user = os.environ.get("IMAP_USER", "").strip()
    password = os.environ.get("IMAP_PASSWORD", "")
    if not (host and user and password):
        raise ImapError(
            "IMAP is niet volledig ingesteld. Zet IMAP_HOST, IMAP_USER en "
            "IMAP_PASSWORD in .env — zie README."
        )
    return {
        "host": host,
        "port": int(os.environ.get("IMAP_PORT", "993") or 993),
        "user": user,
        "password": password,
        "folder": os.environ.get("IMAP_FOLDER", "INBOX").strip() or "INBOX",
    }


def is_configured() -> bool:
    try:
        _cfg()
        return True
    except ImapError:
        return False


@contextmanager
def _connect():
    cfg = _cfg()
    try:
        conn = imaplib.IMAP4_SSL(cfg["host"], cfg["port"], timeout=30)
    except Exception as e:  # noqa: BLE001 - surface as a clean message
        raise ImapError(f"Kan geen verbinding maken met {cfg['host']}:{cfg['port']} ({e})") from e
    try:
        try:
            conn.login(cfg["user"], cfg["password"])
        except imaplib.IMAP4.error as e:
            raise ImapError(
                "Inloggen bij de IMAP-mailbox is geweigerd. Controleer "
                "IMAP_USER/IMAP_PASSWORD (bij Gmail: gebruik een "
                f"App-wachtwoord, niet je normale wachtwoord). Server zei: {e}"
            ) from e
        # readonly=True: never touch \Seen flags or anything else.
        status, _ = conn.select(cfg["folder"], readonly=True)
        if status != "OK":
            raise ImapError(f"IMAP-map '{cfg['folder']}' bestaat niet of is niet leesbaar.")
        yield conn
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


def check_connection() -> str:
    """Try a full connect+login+select and return a human-readable result."""
    cfg = _cfg()
    with _connect() as conn:
        status, data = conn.search(None, "ALL")
        count = len(data[0].split()) if status == "OK" and data and data[0] else 0
    return f"🟢 Verbonden met {cfg['user']} ({cfg['folder']}, {count} mails)"


def status_text() -> str:
    if not is_configured():
        return "⚪ IMAP niet ingesteld (IMAP_HOST / IMAP_USER / IMAP_PASSWORD)"
    try:
        return check_connection()
    except ImapError as e:
        return f"🔴 {e}"


def _decode(raw) -> str:
    """Decode a possibly RFC2047-encoded header into plain text."""
    if raw is None:
        return ""
    parts = []
    for chunk, enc in email.header.decode_header(raw):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def _received_iso(msg) -> str | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError):
        return raw


def find_messages(subject_contains: str, since_days: int = 30, limit: int = 50) -> list[dict]:
    """Recent messages whose subject contains `subject_contains`.

    Narrows server-side on date (IMAP SINCE), then matches the subject here:
    IMAP SUBJECT search is case- and charset-inconsistent across servers,
    while the candidate set after a date filter is tiny.

    Only headers are fetched at this stage — the body (with the attachment)
    is pulled later, and only for mails that still need importing.
    """
    needle = (subject_contains or "").strip().lower()
    since = (dt.datetime.utcnow() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
    out = []
    with _connect() as conn:
        status, data = conn.uid("SEARCH", None, "SINCE", since)
        if status != "OK":
            raise ImapError(f"IMAP-zoekopdracht mislukte: {status}")
        uids = (data[0] or b"").split()
        # Newest first, and cap the work per poll.
        for uid in reversed(uids[-500:]):
            status, hdr = conn.uid(
                "FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE FROM MESSAGE-ID)])"
            )
            if status != "OK" or not hdr or not isinstance(hdr[0], tuple):
                continue
            msg = email.message_from_bytes(hdr[0][1])
            subject = _decode(msg.get("Subject"))
            if needle and needle not in subject.lower():
                continue
            # Message-ID is stable across sessions and folders; UIDs are not
            # (they change if the mailbox is recreated), so dedup on the
            # header and fetch by UID.
            msg_id = (msg.get("Message-ID") or "").strip() or f"uid:{uid.decode()}"
            out.append({
                "id": msg_id,
                "ref": uid.decode(),
                "subject": subject,
                "received_at": _received_iso(msg),
                "from": _decode(msg.get("From")),
            })
            if len(out) >= limit:
                break
    return out


def get_xlsx_attachments(ref: str) -> list[tuple[str, bytes]]:
    """(filename, bytes) for every .xlsx attachment on the message with this
    UID. Non-xlsx parts and inline images are skipped."""
    with _connect() as conn:
        status, data = conn.uid("FETCH", str(ref), "(BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            raise ImapError(f"Kon mail {ref} niet ophalen.")
        msg = email.message_from_bytes(data[0][1])

    out = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        name = _decode(part.get_filename())
        if not name:
            continue
        # Some forwarders mangle the extension case or append spaces.
        if not name.strip().lower().endswith(".xlsx"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        # Strip any directory component a malformed filename might carry, so
        # a name like "../../evil.xlsx" can never escape a temp directory.
        safe = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(name.strip()))
        out.append((safe, payload))
    return out
