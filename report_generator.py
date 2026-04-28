import os
import re
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, pass_eval_context
from markupsafe import Markup

STATIC_DIR = Path(__file__).parent / "static" / "reports"
TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _format_number(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)


def _markdown_to_html(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    paragraphs = [f"<p>{p.strip()}</p>" for p in text.strip().split("\n\n") if p.strip()]
    return "\n".join(paragraphs)


def _delta_info(today_val: int, yesterday_val: int | None) -> tuple:
    if yesterday_val is None:
        return None, "flat", ""
    diff = today_val - yesterday_val
    pct = (diff / yesterday_val * 100) if yesterday_val else 0
    if diff > 0:
        return diff, "up", f"▲ {abs(pct):.1f}% vs ontem"
    elif diff < 0:
        return diff, "down", f"▼ {abs(pct):.1f}% vs ontem"
    else:
        return 0, "flat", "= igual a ontem"


_env.filters["format_number"] = _format_number


def generate(today_metrics: dict, yesterday_metrics: dict | None, analysis: dict) -> str:
    """Renders the HTML report, saves to static/reports/{date}.html, returns file path."""
    ref_date = today_metrics["date"]

    def enrich(key):
        t = today_metrics[key]
        y = yesterday_metrics[key] if yesterday_metrics else None
        delta, delta_class, delta_label = _delta_info(t["total"], y["total"] if y else None)
        return {**t, "delta": delta, "delta_class": delta_class, "delta_label": delta_label}

    metrics = {
        "diss": enrich("diss"),
        "pac": enrich("pac"),
        "sem_evidencia": enrich("sem_evidencia"),
    }

    template = _env.get_template("report.html")
    html = template.render(
        date=ref_date,
        generated_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
        metrics=metrics,
        alerts=analysis.get("alerts", []),
        insights_html=_markdown_to_html(analysis.get("insights", "")),
    )

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    file_path = STATIC_DIR / f"{ref_date}.html"
    file_path.write_text(html, encoding="utf-8")
    return str(file_path)
