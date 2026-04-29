import io
import re
import asyncio
import logging
import pandas as pd
import anthropic
import os
import httpx

log = logging.getLogger(__name__)

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def parse_contacts(file_bytes: bytes, filename: str) -> list[dict]:
    """Parse CSV or Excel file, return list of {name, phone, model, ...}"""
    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
    else:
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)

    df.columns = [_normalize_col(c) for c in df.columns]

    name_col = _find_col(df, ["nome", "name", "cliente", "comprador"])
    phone_col = _find_col(df, ["telefone", "celular", "phone", "fone", "whatsapp", "tel"])
    model_col = _find_col(df, ["modelo", "veiculo", "vehicle", "carro", "model"])

    contacts = []
    for _, row in df.iterrows():
        name = str(row.get(name_col, "")).strip() if name_col else ""
        phone = _clean_phone(str(row.get(phone_col, "")).strip()) if phone_col else ""
        model = str(row.get(model_col, "")).strip() if model_col else ""

        if not phone:
            continue

        extra = {k: str(v).strip() for k, v in row.items()
                 if k not in [name_col, phone_col, model_col] and str(v).strip() not in ["", "nan"]}

        contacts.append({"name": name or "Cliente", "phone": phone, "model": model, "extra": extra})

    return contacts


def _normalize_col(col: str) -> str:
    return col.lower().strip().replace(" ", "_").replace("/", "_")


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in df.columns:
        for candidate in candidates:
            if candidate in c:
                return c
    return None


def _clean_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return ""
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


def personalize_message(template: str, contact: dict) -> str:
    """Use Claude to personalize the message for the contact."""
    name = contact["name"]
    model = contact["model"] or "veículo VW"

    # Fast personalization via simple template substitution
    msg = template.replace("{nome}", name).replace("{model}", model).replace("{modelo}", model)
    return msg


def personalize_with_claude(template: str, contacts: list[dict]) -> list[str]:
    """Batch personalization using Claude for richer messages."""
    if not contacts:
        return []

    # Skip Claude if template has no placeholders — just use direct substitution
    if "{nome}" not in template and "{modelo}" not in template and "{name}" not in template:
        return [personalize_message(template, c) for c in contacts]

    contacts_str = "\n".join(
        f"{i+1}. Nome: {c['name']}, Modelo: {c['model'] or 'VW'}"
        for i, c in enumerate(contacts[:20])
    )

    prompt = f"""Você é um especialista em marketing automotivo VW Brasil.

Substitua SOMENTE as variáveis {{nome}} e {{modelo}} no template abaixo para cada cliente.
Se o template NÃO contiver {{nome}} ou {{modelo}}, copie o template exatamente como está, sem adicionar nome, saudação personalizada ou qualquer informação extra.

Template base:
{template}

Clientes:
{contacts_str}

Responda APENAS com as mensagens numeradas, uma por linha, sem explicações:
1. [mensagem]
2. [mensagem]
..."""

    message = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    lines = message.content[0].text.strip().split("\n")
    messages = []
    for line in lines:
        line = line.strip()
        if line and line[0].isdigit():
            msg = re.sub(r"^\d+\.\s*", "", line)
            messages.append(msg)

    # Fallback to template substitution if Claude returns fewer messages
    while len(messages) < len(contacts):
        i = len(messages)
        if i < len(contacts):
            messages.append(personalize_message(template, contacts[i]))

    return messages[:len(contacts)]


DEFAULT_TEMPLATE = (
    "Olá ! Seu Volkswagen merece um app especial. "
    "Com *Meu Volkswagen* você agenda revisões, acompanha recalls e acessa "
    "benefícios exclusivos. Baixe grátis 👇\n"
    "https://go.vw.com.br/to/myvw?country=BR"
)

_daily_sent_count: dict[str, int] = {}


def _is_allowed_time() -> bool:
    """Check if current time is within allowed send window (8h-18h BRT)."""
    from datetime import datetime
    import pytz
    brt = pytz.timezone("America/Sao_Paulo")
    now = datetime.now(brt)
    return 8 <= now.hour < 18


def _daily_count_key() -> str:
    from datetime import date
    return date.today().isoformat()


def _get_daily_sent() -> int:
    return _daily_sent_count.get(_daily_count_key(), 0)


def _increment_daily_sent():
    key = _daily_count_key()
    _daily_sent_count[key] = _daily_sent_count.get(key, 0) + 1


async def dispatch_whatsapp(contacts: list[dict], messages: list[str]) -> tuple[int, int]:
    """Send WhatsApp messages with rate limiting, time window and daily cap."""
    base_url = os.environ["EVOLUTION_API_URL"].rstrip("/")
    api_key = os.environ["EVOLUTION_API_KEY"]
    instance = os.environ["EVOLUTION_INSTANCE"]

    max_daily = int(os.environ.get("CAMPAIGN_MAX_DAILY", "100"))
    interval_secs = float(os.environ.get("CAMPAIGN_INTERVAL_SECS", "3"))

    sent = 0
    failed = 0
    skipped_time = 0
    skipped_cap = 0

    async with httpx.AsyncClient(timeout=15) as client:
        for contact, message in zip(contacts, messages):
            if not _is_allowed_time():
                skipped_time += 1
                continue

            if _get_daily_sent() >= max_daily:
                skipped_cap += 1
                continue

            try:
                url = f"{base_url}/message/sendText/{instance}"
                headers = {"apikey": api_key, "Content-Type": "application/json"}
                payload = {"number": contact["phone"], "text": message}
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                sent += 1
                _increment_daily_sent()
                log.info(f"Enviado para {contact['phone']}")
            except Exception as e:
                log.error(f"Falha ao enviar para {contact['phone']}: {e}")
                failed += 1

            await asyncio.sleep(interval_secs)

    return sent, failed
