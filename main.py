import os
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

import salesforce_client
import claude_analysis
import report_generator
import email_sender
import whatsapp_sender

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static" / "reports"
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def _data_file(ref_date: date) -> Path:
    return DATA_DIR / f"{ref_date.isoformat()}.json"


def _load_metrics(ref_date: date) -> dict | None:
    p = _data_file(ref_date)
    if p.exists():
        return json.loads(p.read_text())
    return None


def _save_metrics(metrics: dict) -> None:
    p = _data_file(date.fromisoformat(metrics["date"]))
    p.write_text(json.dumps(metrics, ensure_ascii=False, indent=2))


async def run_daily_report(ref_date: date | None = None) -> dict:
    if ref_date is None:
        ref_date = date.today()

    log.info(f"Iniciando relatório para {ref_date}")

    sf = salesforce_client.get_sf_client()
    today_metrics = salesforce_client.fetch_metrics(sf, ref_date)
    _save_metrics(today_metrics)

    yesterday_metrics = _load_metrics(ref_date - timedelta(days=1))

    analysis = claude_analysis.analyze(today_metrics, yesterday_metrics)

    report_path = report_generator.generate(today_metrics, yesterday_metrics, analysis)
    report_url = f"{BASE_URL}/reports/{ref_date.isoformat()}"

    try:
        email_sender.send_report(report_path, ref_date.isoformat(), analysis.get("alerts", []))
        log.info("E-mail enviado")
    except Exception as e:
        log.error(f"Falha no e-mail: {e}")

    try:
        whatsapp_sender.send_alert(
            summary=analysis.get("summary_whatsapp", ""),
            report_url=report_url,
            date=ref_date.strftime("%d/%m/%Y"),
            alerts=analysis.get("alerts", []),
        )
        log.info("WhatsApp enviado")
    except Exception as e:
        log.error(f"Falha no WhatsApp: {e}")

    log.info(f"Relatório concluído: {report_url}")
    return {"status": "ok", "report_url": report_url, "alerts": analysis.get("alerts", [])}


scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cron_expr = os.environ.get("REPORT_CRON", "0 8 * * 1-5")  # seg-sex 08:00 BRT
    parts = cron_expr.split()
    scheduler.add_job(
        run_daily_report,
        CronTrigger(minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4]),
        id="daily_report",
        replace_existing=True,
    )
    scheduler.start()
    log.info(f"Scheduler iniciado — cron: {cron_expr}")
    yield
    scheduler.shutdown()


app = FastAPI(title="SF Monitor — VW Brasil", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/sf-check")
def debug_sf_check():
    username = os.environ.get("SF_USERNAME", "")
    password = os.environ.get("SF_PASSWORD", "")
    token = os.environ.get("SF_SECURITY_TOKEN", "")
    try:
        import salesforce_client
        sf = salesforce_client.get_sf_client()
        return {
            "auth": "OK",
            "instance": sf.sf_instance,
            "username_len": len(username),
            "password_len": len(password),
            "token_len": len(token),
            "username_preview": username[:6] + "..." if username else "",
        }
    except Exception as e:
        return {
            "auth": "FAILED",
            "error": str(e),
            "username_len": len(username),
            "password_len": len(password),
            "token_len": len(token),
            "username_preview": username[:6] + "..." if username else "",
        }


@app.get("/reports/{report_date}", response_class=HTMLResponse)
def get_report(report_date: str):
    report_file = STATIC_DIR / f"{report_date}.html"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    return HTMLResponse(content=report_file.read_text(encoding="utf-8"))


@app.post("/run")
async def trigger_report(report_date: str | None = None):
    """Trigger manual — útil para testes e reprocessamento."""
    ref = date.fromisoformat(report_date) if report_date else None
    result = await run_daily_report(ref)
    return JSONResponse(result)
