import os
import json
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

import campaign
import gmail_reader
import whatsapp_sender
import queue_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static" / "reports"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")


async def _send_report_whatsapp(text: str):
    """Send a report message to WHATSAPP_PHONE via Evolution API."""
    try:
        base_url = os.environ["EVOLUTION_API_URL"].rstrip("/")
        api_key = os.environ["EVOLUTION_API_KEY"]
        instance = os.environ["EVOLUTION_INSTANCE"]
        phone = os.environ.get("WHATSAPP_PHONE", "")
        if not phone:
            return
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"{base_url}/message/sendText/{instance}",
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json={"number": phone, "text": text},
            )
    except Exception as e:
        log.error(f"Falha ao enviar relatório WhatsApp: {e}")


async def run_queue_batch():
    """Scheduled job: send next batch from persistent queue."""
    from datetime import date, timedelta
    max_daily = int(os.environ.get("CAMPAIGN_MAX_DAILY", "500"))
    batch, remaining = queue_store.pop_batch(max_daily)
    if not batch:
        log.info("Fila vazia — nenhum envio agendado hoje")
        await _send_report_whatsapp("📋 *Campanha Meu VW* — Fila vazia, nenhum envio hoje.")
        return

    total_original = remaining + len(batch)
    contacts = [{"phone": item["phone"], "name": item["name"], "model": ""} for item in batch]
    messages = [item["message"] for item in batch]

    log.info(f"Iniciando lote: {len(batch)} mensagens, {remaining} restantes na fila")
    sent, failed = await campaign.dispatch_whatsapp(contacts, messages)
    log.info(f"Lote concluído: {sent} enviados, {failed} falhas, {remaining} ainda na fila")

    progress = round((1 - remaining / total_original) * 100) if total_original > 0 else 100
    days_left = -(-remaining // max_daily) if remaining > 0 else 0
    conclusion = (date.today() + timedelta(days=days_left)).strftime("%d/%m/%Y") if days_left > 0 else "Hoje"

    report = (
        f"📊 *Campanha Meu VW — Relatório Diário*\n\n"
        f"✅ Enviados hoje: {sent}\n"
        f"❌ Falhas: {failed}\n"
        f"📋 Restantes na fila: {remaining:,}\n"
        f"📈 Progresso: {progress}% concluído\n"
        f"⏱ Previsão de conclusão: {conclusion}"
    )
    await _send_report_whatsapp(report)


async def run_campaign_from_gmail():
    """Scheduled job: read Gmail, parse report, dispatch WhatsApp."""
    log.info("Iniciando campanha via Gmail")
    result = gmail_reader.fetch_latest_salesforce_report()
    if not result:
        log.warning("Nenhum relatório encontrado no Gmail")
        return
    file_bytes, filename = result
    contacts = campaign.parse_contacts(file_bytes, filename)
    if not contacts:
        log.warning("Nenhum contato válido encontrado")
        return
    template = os.environ.get("CAMPAIGN_TEMPLATE", campaign.DEFAULT_TEMPLATE)
    messages = campaign.personalize_with_claude(template, contacts)
    sent, failed = await campaign.dispatch_whatsapp(contacts, messages)
    log.info(f"Campanha concluída: {sent} enviados, {failed} falhas")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cron_expr = os.environ.get("CAMPAIGN_CRON", "0 9 * * 1-5")
    parts = cron_expr.split()
    scheduler.add_job(
        run_queue_batch,
        CronTrigger(minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4]),
        id="daily_queue",
        replace_existing=True,
    )
    scheduler.start()
    log.info(f"Scheduler iniciado — cron: {cron_expr}")
    yield
    scheduler.shutdown()


app = FastAPI(title="Meu VW Campaign — VW Brasil", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "queue": queue_store.queue_size()}


@app.get("/", response_class=HTMLResponse)
def upload_page():
    template_path = Path(__file__).parent / "templates" / "upload.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


@app.get("/queue/status")
def queue_status():
    size = queue_store.queue_size()
    max_daily = int(os.environ.get("CAMPAIGN_MAX_DAILY", "500"))
    days = (size + max_daily - 1) // max_daily if size > 0 else 0
    return {"total": size, "max_daily": max_daily, "estimated_days": days}


@app.post("/queue/clear")
def queue_clear():
    queue_store.clear_queue()
    return {"status": "ok", "total": 0}


@app.post("/upload")
async def upload_contacts(
    file: UploadFile = File(...),
    template: str = Form(...),
    mode: str = Form("preview"),
):
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    try:
        contacts = campaign.parse_contacts(file_bytes, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler arquivo: {e}")

    if not contacts:
        raise HTTPException(status_code=400, detail="Nenhum contato válido encontrado. Verifique as colunas: nome, telefone, modelo")

    messages = campaign.personalize_with_claude(template, contacts)

    if mode == "queue":
        items = [
            {"phone": c["phone"], "name": c["name"], "message": m}
            for c, m in zip(contacts, messages)
        ]
        total = queue_store.add_to_queue(items)
        max_daily = int(os.environ.get("CAMPAIGN_MAX_DAILY", "500"))
        days = (total + max_daily - 1) // max_daily
        return JSONResponse({
            "mode": "queue",
            "added": len(items),
            "total_in_queue": total,
            "max_daily": max_daily,
            "estimated_days": days,
            "messages": [{"phone": c["phone"], "name": c["name"], "message": m}
                         for c, m in zip(contacts[:5], messages[:5])],
        })

    if mode == "preview":
        return JSONResponse({
            "mode": "preview",
            "sent": len(contacts),
            "failed": 0,
            "skipped": 0,
            "messages": [{"phone": c["phone"], "name": c["name"], "message": m}
                         for c, m in zip(contacts, messages)],
        })

    # mode == "send" — immediate send (for small lists)
    sent, failed = await campaign.dispatch_whatsapp(contacts, messages)
    return JSONResponse({
        "mode": "send",
        "sent": sent,
        "failed": failed,
        "skipped": 0,
        "messages": [{"phone": c["phone"], "name": c["name"], "message": m}
                     for c, m in zip(contacts, messages)],
    })


@app.get("/debug/gmail")
def debug_gmail():
    return gmail_reader.check_connection()


@app.post("/campaign/run")
async def trigger_campaign():
    await run_campaign_from_gmail()
    return {"status": "ok"}


@app.post("/queue/run")
async def trigger_queue():
    """Manually trigger a queue batch send."""
    await run_queue_batch()
    return {"status": "ok", "remaining": queue_store.queue_size()}
