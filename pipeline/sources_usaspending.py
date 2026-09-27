"""USAspending.gov assistance obligations for assistance listings that appear
on current opportunities.

POST https://api.usaspending.gov/api/v2/search/spending_by_award/
No API key. These are reported obligations, not solicitations, and not a
statement of what an agency says it wants to fund.
"""

from __future__ import annotations

import time

from pipeline.http_util import post_json

API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
AWARD_PAGE = "https://www.usaspending.gov/award/{generated_id}"

FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Description",
    "Start Date",
    "End Date",
    "CFDA Number",
    "generated_internal_id",
    "Award Type",
]


def obligations_for_alns(alns: list[str], start_date: str, end_date: str, limit: int = 25) -> dict:
    if not alns:
        return {"results": [], "note": "No assistance listings to query."}
    body = {
        "filters": {
            "award_type_codes": ["02", "03", "04", "05"],
            "time_period": [{"start_date": start_date, "end_date": end_date}],
            "program_numbers": alns,
        },
        "fields": FIELDS,
        "sort": "Award Amount",
        "order": "desc",
        "limit": limit,
        "page": 1,
    }
    payload = post_json(API_URL, body, timeout=120)
    results = []
    for row in payload.get("results") or []:
        generated = row.get("generated_internal_id")
        amount = row.get("Award Amount")
        try:
            amount_num = int(round(float(amount))) if amount is not None else None
        except (TypeError, ValueError):
            amount_num = None
        results.append(
            {
                "award_id": row.get("Award ID"),
                "recipient_name": row.get("Recipient Name"),
                "amount": amount_num,
                "awarding_agency": row.get("Awarding Agency"),
                "awarding_sub_agency": row.get("Awarding Sub Agency"),
                "description": row.get("Description"),
                "start_date": row.get("Start Date"),
                "end_date": row.get("End Date"),
                "cfda": row.get("CFDA Number"),
                "award_type": row.get("Award Type"),
                "urls": {
                    "official": AWARD_PAGE.format(generated_id=generated) if generated else "https://www.usaspending.gov/search"
                },
                "source": {
                    "id": "usaspending",
                    "name": "USAspending spending_by_award",
                    "endpoint": API_URL,
                },
                "record_type": "obligation",
                "fact_boundary": "Reported assistance obligation. Not a solicitation and not proof of what the agency will fund next.",
            }
        )
    return {
        "results": results,
        "page_metadata": payload.get("page_metadata"),
        "request": {
            "program_numbers": alns,
            "time_period": {"start_date": start_date, "end_date": end_date},
            "award_type_codes": ["02", "03", "04", "05"],
            "limit": limit,
            "sort": "Award Amount desc",
        },
        "endpoint": API_URL,
    }


def collect_for_catalog_alns(aln_numbers: list[str], start_date: str, end_date: str, batch_size: int = 15, max_batches: int = 6) -> dict:
    unique = []
    for number in aln_numbers:
        if number and number not in unique:
            unique.append(number)
    batches = []
    errors = []
    awards = []
    seen = set()
    for index in range(0, min(len(unique), batch_size * max_batches), batch_size):
        chunk = unique[index : index + batch_size]
        try:
            result = obligations_for_alns(chunk, start_date, end_date, limit=20)
            batches.append(
                {
                    "program_numbers": chunk,
                    "returned": len(result["results"]),
                    "has_next": (result.get("page_metadata") or {}).get("hasNext"),
                }
            )
            for row in result["results"]:
                key = row.get("award_id") or row["urls"]["official"]
                if key in seen:
                    continue
                seen.add(key)
                awards.append(row)
        except Exception as exc:
            errors.append({"program_numbers": chunk, "error": str(exc)})
        time.sleep(0.35)
    return {
        "awards": awards,
        "batches": batches,
        "errors": errors,
        "alns_considered": len(unique),
        "alns_queried": min(len(unique), batch_size * max_batches),
        "coverage": (
            "Obligations for a subset of assistance listings that appear on cataloged opportunities, "
            "sorted by amount within each API call, one page per batch. Not all awards under those listings, "
            "and not all federal research spending."
        ),
        "time_period": {"start_date": start_date, "end_date": end_date},
    }
