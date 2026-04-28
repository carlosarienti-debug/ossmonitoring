import os
import json
import anthropic

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def analyze(today: dict, yesterday: dict | None) -> dict:
    """
    Returns:
      {
        "summary_whatsapp": str,   # short text for WhatsApp (max ~300 chars)
        "insights": str,           # markdown for the HTML report
        "alerts": list[str],       # critical alerts (non-empty triggers alert flag)
      }
    """
    prompt = _build_prompt(today, yesterday)
    message = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text
    return _parse_response(raw)


def _build_prompt(today: dict, yesterday: dict | None) -> str:
    today_str = json.dumps(today, ensure_ascii=False, indent=2)
    yesterday_str = json.dumps(yesterday, ensure_ascii=False, indent=2) if yesterday else "Sem dados anteriores"

    return f"""Você é um analista de qualidade automotiva especializado em atendimento ao cliente VW Brasil.

Analise os indicadores abaixo e responda EXATAMENTE no formato JSON especificado.

## Dados de hoje ({today["date"]})
{today_str}

## Dados de ontem
{yesterday_str}

## Métricas explicadas
- **DISS**: Casos de Dissatisfação do cliente registrados por OS (Ordem de Serviço)
- **PAC**: Ordens de Serviço no Programa de Atenção ao Cliente
- **OS Sem Evidência**: Ordens de Serviço sem documentação/evidência anexada (risco de auditoria)

## Responda APENAS com este JSON (sem texto fora do JSON):
{{
  "summary_whatsapp": "<resumo em até 280 chars, use emojis, mencione variações vs ontem>",
  "insights": "<análise em markdown, 3-5 parágrafos, tendências, riscos, recomendações>",
  "alerts": ["<alerta crítico 1>", "<alerta crítico 2>"]
}}

Regras para alerts:
- Inclua um alerta se DISS aumentou >10% vs ontem
- Inclua um alerta se PAC aumentou >10% vs ontem
- Inclua um alerta se OS Sem Evidência > 50.000
- Se nenhum critério for atingido, retorne alerts como lista vazia []
"""


def _parse_response(raw: str) -> dict:
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return {
            "summary_whatsapp": "Erro ao analisar indicadores SF. Verifique o relatório completo.",
            "insights": raw,
            "alerts": [],
        }
