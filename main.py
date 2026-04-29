import os
import json
import logging
from datetime import date, timedelta
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static" / "reports"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")


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
        run_campaign_from_gmail,
        CronTrigger(minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4]),
        id="daily_campaign",
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
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def upload_page():
    template_path = Path(__file__).parent / "templates" / "upload.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


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

    messages = campaign.personalize_with_claude(template, contacts[:20])
    # For larger lists use simple substitution
    if len(contacts) > 20:
        extra = [campaign.personalize_message(template, c) for c in contacts[20:]]
        messages = messages + extra

    result_messages = [
        {"phone": c["phone"], "name": c["name"], "message": m}
        for c, m in zip(contacts, messages)
    ]

    sent = 0
    if mode == "send":
        sent, _ = await campaign.dispatch_whatsapp(contacts, messages)
    else:
        sent = len(contacts)

    return JSONResponse({
        "sent": sent,
        "skipped": 0,
        "mode": mode,
        "messages": result_messages,
    })


@app.get("/debug/gmail")
def debug_gmail():
    return gmail_reader.check_connection()


@app.post("/campaign/run")
async def trigger_campaign():
    await run_campaign_from_gmail()
    return {"status": "ok"}
