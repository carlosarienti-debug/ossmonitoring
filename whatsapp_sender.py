import os
import httpx


def send_alert(summary: str, report_url: str, date: str, alerts: list[str]) -> None:
    base_url = os.environ["EVOLUTION_API_URL"].rstrip("/")
    api_key = os.environ["EVOLUTION_API_KEY"]
    instance = os.environ["EVOLUTION_INSTANCE"]
    phone = os.environ["WHATSAPP_PHONE"]  # 5511961960411

    alert_line = "\n🔴 *ALERTA:* " + " | ".join(alerts) if alerts else ""

    text = (
        f"📊 *OS Monitor VW — {date}*\n\n"
        f"{summary}"
        f"{alert_line}\n\n"
        f"📄 Relatório completo:\n{report_url}"
    )

    url = f"{base_url}/message/sendText/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"number": phone, "text": text}

    with httpx.Client(timeout=15) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
