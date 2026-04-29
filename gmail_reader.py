import imaplib
import email
import os
import io
from email.header import decode_header


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def fetch_latest_salesforce_report() -> tuple[bytes, str] | None:
    """
    Connect to Gmail, find the latest Salesforce report email,
    return (attachment_bytes, filename) or None if not found.
    """
    gmail = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")

    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(gmail, password)
        imap.select("INBOX")

        # Search for Salesforce report emails (subject contains "Relatório" or sender is salesforce)
        search_criteria = [
            'FROM "salesforce.com"',
            'SUBJECT "Relatório"',
            'SUBJECT "Relatorio"',
            'SUBJECT "Report"',
            'SUBJECT "Emplacamento"',
            'SUBJECT "Comprador"',
        ]

        email_ids = []
        for criteria in search_criteria:
            _, data = imap.search(None, criteria)
            ids = data[0].split()
            email_ids.extend(ids)

        if not email_ids:
            return None

        # Get most recent
        latest_id = sorted(email_ids)[-1]
        _, msg_data = imap.fetch(latest_id, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        # Look for CSV or Excel attachment
        for part in msg.walk():
            content_type = part.get_content_type()
            filename = part.get_filename()

            if filename:
                decoded_name, charset = decode_header(filename)[0]
                if isinstance(decoded_name, bytes):
                    filename = decoded_name.decode(charset or "utf-8", errors="replace")
                else:
                    filename = decoded_name

            if filename and (filename.endswith(".csv") or filename.endswith(".xlsx") or filename.endswith(".xls")):
                return part.get_payload(decode=True), filename

            # Also try inline CSV content
            if content_type == "text/csv":
                return part.get_payload(decode=True), "report.csv"

        # No attachment — try to parse inline table from HTML body
        return None


def check_connection() -> dict:
    """Test Gmail IMAP connection."""
    gmail = os.environ.get("GMAIL_ADDRESS", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")

    debug = {
        "gmail_len": len(gmail),
        "password_len": len(password),
        "gmail_preview": gmail[:8] + "..." if gmail else "(vazio)",
        "password_empty": password == "",
    }

    if not gmail or not password:
        return {"status": "error", "error": "GMAIL_ADDRESS ou GMAIL_APP_PASSWORD não configurados", **debug}

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        imap.login(gmail, password)
        imap.select("INBOX")
        _, data = imap.search(None, "ALL")
        count = len(data[0].split()) if data[0] else 0
        imap.logout()
        return {"status": "ok", "inbox_count": count, "account": gmail, **debug}
    except imaplib.IMAP4.error as e:
        return {"status": "error", "error": str(e), **debug}
    except Exception as e:
        return {"status": "error", "error": type(e).__name__ + ": " + str(e), **debug}
