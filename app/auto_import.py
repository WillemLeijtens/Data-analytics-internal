"""Automatic Outlook import: poll the mailbox for messages whose subject
matches a configured filter, download their .xlsx attachments, and run them
through exactly the same ingestion pipeline as a manual upload.

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
import ingestion
import outlook

SUBJECT_KEY = "auto_import_subject"
ENABLED_KEY = "auto_import_enabled"
LAST_POLL_KEY = "auto_import_last_poll"
LAST_RESULT_KEY = "auto_import_last_result"
DEFAULT_SUBJECT = "DWH"


def get_subject_filter() -> str:
    return db.get_meta(SUBJECT_KEY) or DEFAULT_SUBJECT


def is_enabled() -> bool:
    # Default off: nothing should reach out to a mailbox until it's been
    # switched on deliberately in Settings.
    return (db.get_meta(ENABLED_KEY) or "0") == "1"


def import_attachment(name: str, content: bytes, message_id: str, subject: str,
                      received_at: str) -> tuple[bool, str]:
    """Parse + load one attachment. Returns (ok, message). Parse failures are
    caught and reported; they must not take the poller down."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        parsed = ingestion.parse_workbook(tmp_path, name)
        rows, warnings = db.load_parsed_file(parsed)
        note = f"{rows} rows loaded ({parsed.brand}/{parsed.country}/{parsed.banner})"
        if warnings:
            note += f"; {len(warnings)} warning(s): " + "; ".join(warnings)
        db.record_email_import(message_id, name, subject, received_at, "ok", note)
        return True, note
    except Exception as e:  # noqa: BLE001 - any parse failure is data-specific
        note = f"{type(e).__name__}: {e}"
        db.record_email_import(message_id, name, subject, received_at, "failed", note)
        return False, note
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def poll_once(subject_filter: str | None = None, since_days: int = 30) -> dict:
    """One pass over the mailbox. Returns a summary dict; also stores it as
    the app's 'last result' so the UI can show what happened."""
    subject_filter = subject_filter if subject_filter is not None else get_subject_filter()
    summary = {"checked": 0, "imported": 0, "failed": 0, "skipped": 0, "error": None}
    try:
        messages = outlook.find_messages(subject_filter, since_days=since_days)
    except Exception as e:  # noqa: BLE001 - network/auth: retry next run
        summary["error"] = f"{type(e).__name__}: {e}"
        db.set_meta_value(LAST_POLL_KEY, dt.datetime.utcnow().isoformat())
        db.set_meta_value(LAST_RESULT_KEY, f"Fout: {summary['error']}")
        return summary

    for msg in messages:
        summary["checked"] += 1
        try:
            attachments = outlook.get_xlsx_attachments(msg["id"])
        except Exception as e:  # noqa: BLE001 - transient: leave unrecorded
            summary["error"] = f"{type(e).__name__}: {e}"
            break
        for name, content in attachments:
            if db.is_email_processed(msg["id"], name):
                summary["skipped"] += 1
                continue
            ok, _note = import_attachment(
                name, content, msg["id"], msg["subject"], msg["received_at"]
            )
            summary["imported" if ok else "failed"] += 1

    db.set_meta_value(LAST_POLL_KEY, dt.datetime.utcnow().isoformat())
    if summary["error"]:
        result = f"Fout: {summary['error']}"
    else:
        result = (
            f"{summary['imported']} geïmporteerd, {summary['failed']} mislukt, "
            f"{summary['skipped']} al eerder verwerkt "
            f"({summary['checked']} mail(s) bekeken)"
        )
    db.set_meta_value(LAST_RESULT_KEY, result)
    return summary


def main():
    ap = argparse.ArgumentParser(description="Outlook auto-import for sellout files")
    ap.add_argument("--loop", action="store_true", help="keep polling instead of exiting")
    ap.add_argument("--interval", type=int, default=900, help="seconds between polls")
    ap.add_argument("--since-days", type=int, default=30, help="how far back to look")
    ap.add_argument("--force", action="store_true",
                    help="poll even when auto-import is switched off in Settings")
    args = ap.parse_args()

    db.init_db()
    while True:
        if not args.force and not is_enabled():
            print("[auto-import] disabled in Settings — nothing to do", flush=True)
        else:
            summary = poll_once(since_days=args.since_days)
            print(f"[auto-import] {dt.datetime.utcnow().isoformat()} {summary}", flush=True)
        if not args.loop:
            break
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()
