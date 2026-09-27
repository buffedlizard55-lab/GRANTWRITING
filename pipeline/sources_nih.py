"""NIH RePORTER API v2. Public, no key.

POST https://api.reporter.nih.gov/v2/projects/search
Documentation: https://api.reporter.nih.gov/

These are funded projects, not open solicitations. A pull that does not page
through the reported total is a sample and is labeled as one.
"""

from __future__ import annotations

import time

from pipeline.http_util import post_json
from pipeline.textutil import html_to_text, parse_money

API_URL = "https://api.reporter.nih.gov/v2/projects/search"
PROJECT_URL = "https://reporter.nih.gov/project-details/{appl_id}"

INCLUDE_FIELDS = [
    "ApplId",
    "ProjectNum",
    "ProjectTitle",
    "AwardAmount",
    "Organization",
    "ContactPiName",
    "PrincipalInvestigators",
    "AgencyIcAdmin",
    "FiscalYear",
    "ProjectStartDate",
    "ProjectEndDate",
    "AbstractText",
    "OpportunityNumber",
    "ActivityCode",
    "AwardNoticeDate",
    "CfdaCode",
]


def _project(row: dict, retrieved_at: str, sample_label: str) -> dict | None:
    appl_id = row.get("appl_id") or row.get("applId")
    title = html_to_text(row.get("project_title") or row.get("projectTitle") or "")
    if not appl_id or not title:
        return None
    org = row.get("organization") or {}
    agency = row.get("agency_ic_admin") or {}
    pi = row.get("contact_pi_name")
    if not pi:
        pis = row.get("principal_investigators") or []
        if pis and isinstance(pis, list):
            pi = pis[0].get("full_name")
    abstract = html_to_text(row.get("abstract_text") or "")
    if len(abstract) > 1000:
        abstract = abstract[:999].rstrip() + "…"
    return {
        "id": f"nih-{appl_id}",
        "source_record_id": str(appl_id),
        "title": title,
        "project_number": row.get("project_num"),
        "agency": (agency.get("abbreviation") if isinstance(agency, dict) else None) or "NIH",
        "agency_name": (agency.get("name") if isinstance(agency, dict) else None) or "National Institutes of Health",
        "parent_agency": "HHS",
        "awardee_name": org.get("org_name") if isinstance(org, dict) else None,
        "awardee_city": org.get("org_city") if isinstance(org, dict) else None,
        "awardee_state": org.get("org_state") if isinstance(org, dict) else None,
        "pi_name": pi,
        "amount_obligated": parse_money(row.get("award_amount")),
        "fiscal_year": row.get("fiscal_year"),
        "start_date": _date(row.get("project_start_date")),
        "end_date": _date(row.get("project_end_date")),
        "award_notice_date": _date(row.get("award_notice_date")),
        "activity_code": row.get("activity_code"),
        "opportunity_number": row.get("opportunity_number"),
        "cfda": row.get("cfda_code"),
        "abstract": abstract or None,
        "urls": {"official": PROJECT_URL.format(appl_id=appl_id)},
        "source": {
            "id": "nih_reporter",
            "name": "NIH RePORTER API v2",
            "retrieved_at": retrieved_at,
            "endpoint": API_URL,
        },
        "verified_at": retrieved_at,
        "record_type": "historical_award",
        "sample_label": sample_label,
        "fact_boundary": "Funded project from NIH RePORTER. Not an open funding opportunity. Sample label describes how this row was selected.",
    }


def _date(value) -> str | None:
    if not value:
        return None
    text = str(value)[:10]
    return text if len(text) == 10 and text[4] == "-" else None


def search_projects(criteria: dict, retrieved_at: str, sample_label: str, limit: int = 100, offset: int = 0, sort_field: str | None = None, sort_order: str = "desc") -> dict:
    body = {
        "criteria": criteria,
        "include_fields": INCLUDE_FIELDS,
        "offset": offset,
        "limit": limit,
    }
    if sort_field:
        body["sort_field"] = sort_field
        body["sort_order"] = sort_order
    payload = post_json(API_URL, body, timeout=120)
    meta = payload.get("meta") or {}
    rows = payload.get("results") or []
    awards = []
    for row in rows:
        record = _project(row, retrieved_at, sample_label)
        if record:
            awards.append(record)
    return {
        "awards": awards,
        "total": meta.get("total"),
        "offset": offset,
        "limit": limit,
        "search_id": meta.get("search_id"),
        "endpoint": API_URL,
        "criteria": criteria,
        "sample_label": sample_label,
    }


def collect_samples(retrieved_at: str, fiscal_years: list[int] | None = None) -> dict:
    """Two labeled samples: largest awards, and a recent-offset slice.

    Neither sample is a complete NIH census. The API total is stored so the
    site can say how small the sample is.
    """
    years = fiscal_years or [2025, 2026]
    samples = []
    errors = []
    queries = [
        ("largest_awards", {"fiscal_years": years}, "award_amount"),
        ("reporter_result_order", {"fiscal_years": years}, None),
    ]
    for label, criteria, sort_field in queries:
        try:
            samples.append(
                search_projects(
                    criteria,
                    retrieved_at,
                    sample_label=label,
                    limit=150,
                    sort_field=sort_field,
                )
            )
        except Exception as exc:
            errors.append({"label": label, "error": str(exc)})
        time.sleep(0.4)
    awards = []
    seen = set()
    for sample in samples:
        for award in sample["awards"]:
            if award["id"] in seen:
                continue
            seen.add(award["id"])
            awards.append(award)
    return {
        "awards": awards,
        "queries": [
            {
                "sample_label": s["sample_label"],
                "total_reported_by_api": s["total"],
                "returned": len(s["awards"]),
                "criteria": s["criteria"],
            }
            for s in samples
        ],
        "errors": errors,
        "coverage": "Labeled samples from NIH RePORTER, not a complete project census. Do not sum this file and call it NIH funding.",
    }
