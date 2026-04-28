import os
from simple_salesforce import Salesforce
from datetime import date, timedelta


def get_sf_client() -> Salesforce:
    return Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
        domain=os.environ.get("SF_DOMAIN", "login"),  # use 'test' for sandbox
    )


def fetch_metrics(sf: Salesforce, reference_date: date | None = None) -> dict:
    if reference_date is None:
        reference_date = date.today()

    # Reports API — pull existing dashboard reports by ID
    # IDs are configured via env vars so they can be updated without code changes
    report_diss_id = os.environ.get("SF_REPORT_DISS_ID")
    report_pac_id = os.environ.get("SF_REPORT_PAC_ID")
    report_sem_evidencia_id = os.environ.get("SF_REPORT_SEM_EVIDENCIA_ID")

    metrics = {
        "date": reference_date.isoformat(),
        "diss": _pull_report_or_query(sf, report_diss_id, _query_diss, reference_date),
        "pac": _pull_report_or_query(sf, report_pac_id, _query_pac, reference_date),
        "sem_evidencia": _pull_report_or_query(sf, report_sem_evidencia_id, _query_sem_evidencia, reference_date),
    }

    return metrics


def _pull_report_or_query(sf: Salesforce, report_id: str | None, fallback_fn, ref_date: date) -> dict:
    """Use Reports API if report ID is configured, else fall back to SOQL query."""
    if report_id:
        try:
            return _pull_report(sf, report_id)
        except Exception:
            pass
    return fallback_fn(sf, ref_date)


def _pull_report(sf: Salesforce, report_id: str) -> dict:
    result = sf.restful(f"analytics/reports/{report_id}", method="GET")
    facts = result.get("factMap", {})
    # Grand total row — T!T is the standard key for report totals
    grand_total = facts.get("T!T", {})
    aggregates = grand_total.get("aggregates", [])
    total = int(aggregates[0]["value"]) if aggregates else 0
    return {"total": total, "by_period": []}


def _query_diss(sf: Salesforce, ref_date: date) -> dict:
    """Fallback SOQL — adjust object/field names after confirming SF schema."""
    periods = _build_period_ranges(ref_date)
    by_period = []
    for label, start, end in periods:
        soql = (
            f"SELECT COUNT() FROM Case "
            f"WHERE DISS__c = true "
            f"AND CreatedDate >= {start}T00:00:00Z AND CreatedDate <= {end}T23:59:59Z"
        )
        result = sf.query(soql)
        by_period.append({"label": label, "count": result["totalSize"]})

    total = sum(p["count"] for p in by_period)
    return {"total": total, "by_period": by_period}


def _query_pac(sf: Salesforce, ref_date: date) -> dict:
    periods = _build_period_ranges(ref_date)
    by_period = []
    for label, start, end in periods:
        soql = (
            f"SELECT COUNT() FROM Case "
            f"WHERE PAC__c = true "
            f"AND CreatedDate >= {start}T00:00:00Z AND CreatedDate <= {end}T23:59:59Z"
        )
        result = sf.query(soql)
        by_period.append({"label": label, "count": result["totalSize"]})

    total = sum(p["count"] for p in by_period)
    return {"total": total, "by_period": by_period}


def _query_sem_evidencia(sf: Salesforce, ref_date: date) -> dict:
    periods = _build_period_ranges(ref_date)
    by_period = []
    for label, start, end in periods:
        soql = (
            f"SELECT COUNT() FROM Case "
            f"WHERE HasAttachment = false "
            f"AND CreatedDate >= {start}T00:00:00Z AND CreatedDate <= {end}T23:59:59Z"
        )
        result = sf.query(soql)
        by_period.append({"label": label, "count": result["totalSize"]})

    total = sum(p["count"] for p in by_period)
    return {"total": total, "by_period": by_period}


def _build_period_ranges(ref_date: date) -> list[tuple[str, str, str]]:
    """
    Placeholder period definitions — update labels/ranges once the 4 dashboard
    color rows are clarified by the user.
    """
    return [
        ("Período 1", (ref_date - timedelta(days=90)).isoformat(), (ref_date - timedelta(days=61)).isoformat()),
        ("Período 2", (ref_date - timedelta(days=60)).isoformat(), (ref_date - timedelta(days=31)).isoformat()),
        ("Período 3", (ref_date - timedelta(days=30)).isoformat(), (ref_date - timedelta(days=8)).isoformat()),
        ("Período 4", (ref_date - timedelta(days=7)).isoformat(), ref_date.isoformat()),
    ]
