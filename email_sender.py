import os
import base64
from pathlib import Path
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition


def send_report(report_html_path: str, date: str, alerts: list[str]) -> None:
    subject = f"{'🔴 ALERTA — ' if alerts else ''}OS Monitor VW — {date}"

    html_content = Path(report_html_path).read_text(encoding="utf-8")

    message = Mail(
        from_email=os.environ["EMAIL_FROM"],
        to_emails=os.environ["EMAIL_TO"],
        subject=subject,
        html_content=html_content,
    )

    client = SendGridAPIClient(os.environ["SENDGRID_API_KEY"])
    client.send(message)
