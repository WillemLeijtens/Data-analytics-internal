"""Automatic mail import: poll the mailbox for messages whose subject
matches a configured filter, download their .xlsx attachments, and run them
through exactly the same ingestion pipeline as a manual upload.

Every setting (source, subject filter, on/off) is stored PER RETAILER —
meta keys are suffixed with the retailer id (e.g. 'auto_import_subject:KRUIDVAT');
the DB migration copied the old unsuffixed Kruidvat-era keys over. The poll
loop walks all registered retailers and polls each one that is switched on,
parsing attachments with that retailer's own parser.

Run once:      python app/auto_import.py
Run as poller: python app/auto_import.py --loop --interval 900

Retry policy — deliberate split:
  * A file that fails to PARSE is recorded as handled with status 'failed'.
    Retrying it every 15 minutes forever would spam the log and never
    succeed; it's surfaced in the app so it can be fixed and re-uploaded.
  * A NETWORK or AUTH failure aborts the poll without recording anything, so
    the same mail is retried on the next run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
import retailers

SUBJECT_KEY = "auto_import_subject"
ENABLED_KEY = "auto_import_enabled"
LAST_POLL_KEY = "auto_import_last_poll"
LAST_RESULT_KEY = "auto_import_last_result"
SOURCE_KEY = "auto_import_source"
DEFAULT_SUBJECT = "DWH"
DEFAULT_SOURCE = "imap"

# Two interchangeable mail sources, both exposing find_messages() /
# get_xlsx_attachments() / status_text():
#   imap    — a dedicated forwarding mailbox (an Outlook rule forwards the
#             reports there). The app never touches your own mailbox.
#   outlook — direct Microsoft Graph access to your own mailbox (OAuth).
SOURCES = {"imap": "Doorstuur-mailbox (IMAP)", "outlook": "Eigen Outlook-mailbox (Graph)"}


def meta_key(base: str, retailer: str) -> str:
    return f"{base}:{retailer}"


def get_source_kind(retailer: str) -> str:
    kind = db.get_meta(meta_key(SOURCE_KEY, retailer)) or DEFAULT_SOURCE
    return kind if kind in SOURCES else DEFAULT_SOURCE


def get_source(kind: str):
    """Import the requested source module lazily, so a missing/misconfigured
    source never breaks the rest of the app at import time."""
    if kind == "outlook":
        import outlook
        return outlook
    import imap_source
    return imap_source


def get_subject_filter(retailer: str) -> str:
    return db.get_meta(meta_key(SUBJECT_KEY, retailer)) or DEFAULT_SUBJECT


def is_enabled(retailer: str) -> bool:
    # Default off: nothing should reach out to a mailbox until it's been
    # switched on deliberately in Settings.
    return (db.get_meta(meta_key(ENABLED_KEY, retailer)) or "0") == "1"


def import_attachment(profile: retailers.RetailerProfile, name: str, content: bytes,
                      message_id: str, subject: str, received_at: str) -> tuple[bool, str]:
    """Parse + load one attachment with the retailer's own parser. Returns
    (ok, message). Parse failures are caught and reported; they must not take
    the poller down."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        parsed = profile.parser(tmp_path, name)
        rows, warnings = db.load_parsed_file(parsed)
        note = f"{rows} rows loaded ({parsed.brand}/{parsed.country}/{parsed.banner})"
        if warnings:
            note += f"; {len(warnings)} warning(s): " + "; ".join(warnings)
        db.record_email_import(message_id, name, profile.id, subject, received_at, "ok", note)
        return True, note
    except Exception as e:  # noqa: BLE001 - any parse failure is data-specific
        note = f"{type(e).__name__}: {e}"
        db.record_email_import(message_id, name, profile.id, subject, received_at, "failed", note)
        return False, note
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def poll_once(retailer: str, subject_filter: str | None = None,
              since_days: int = 30, source=None) -> dict:
    """One pass over the mailbox for one retailer. Returns a summary dict;
    also stores it as that retailer's 'last result' so the UI can show what
    happened."""
    profile = retailers.get_profile(retailer)
    if subject_filter is None:
        subject_filter = get_subject_filter(profile.id)
    source = source or get_source(get_source_kind(profile.id))
    summary = {"checked": 0, "imported": 0, "failed": 0, "skipped": 0, "error": None}
    try:
        messages = source.find_messages(subject_filter, since_days=since_days)
    except Exception as e:  # noqa: BLE001 - network/auth: retry next run
        summary["error"] = f"{type(e).__name__}: {e}"
        db.set_meta_value(meta_key(LAST_POLL_KEY, profile.id), dt.datetime.utcnow().isoformat())
        db.set_meta_value(meta_key(LAST_RESULT_KEY, profile.id), f"Fout: {summary['error']}")
        return summary

    for msg in messages:
        summary["checked"] += 1
        try:
            attachments = source.get_xlsx_attachments(msg.get("ref", msg["id"]))
        except Exception as e:  # noqa: BLE001 - transient: leave unrecorded
            summary["error"] = f"{type(e).__name__}: {e}"
            break
        for name, content in attachments:
            if db.is_email_processed(msg["id"], name):
                summary["skipped"] += 1
                continue
            ok, _note = import_attachment(
                profile, name, content, msg["id"], msg["subject"], msg["received_at"]
            )
            summary["imported" if ok else "failed"] += 1

    db.set_meta_value(meta_key(LAST_POLL_KEY, profile.id), dt.datetime.utcnow().isoformat())
    if summary["error"]:
        result = f"Fout: {summary['error']}"
    else:
        result = (
            f"{summary['imported']} geïmporteerd, {summary['failed']} mislukt, "
            f"{summary['skipped']} al eerder verwerkt "
            f"({summary['checked']} mail(s) bekeken)"
        )
    db.set_meta_value(meta_key(LAST_RESULT_KEY, profile.id), result)
    return summary


def main():
    ap = argparse.ArgumentParser(description="Mail auto-import for sellout files")
    ap.add_argument("--loop", action="store_true", help="keep polling instead of exiting")
    ap.add_argument("--interval", type=int, default=900, help="seconds between polls")
    ap.add_argument("--since-days", type=int, default=30, help="how far back to look")
    ap.add_argument("--force", action="store_true",
                    help="poll every retailer even when switched off in Settings")
    args = ap.parse_args()

    db.init_db()
    while True:
        ran_any = False
        for retailer_id in retailers.RETAILERS:
            if not args.force and not is_enabled(retailer_id):
                continue
            ran_any = True
            summary = poll_once(retailer_id, since_days=args.since_days)
            print(f"[auto-import] {dt.datetime.utcnow().isoformat()} "
                  f"{retailer_id} {summary}", flush=True)
        if not ran_any:
            print("[auto-import] disabled in Settings for every retailer — "
                  "nothing to do", flush=True)
        if not args.loop:
            break
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()
