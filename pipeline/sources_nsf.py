"""NSF official sources.

Funding interests: https://www.nsf.gov/rss/rss_www_funding.xml
Award search API (public, no key): https://api.nsf.gov/services/v1/awards.json
API field guide: https://resources.research.gov/common/webapi/awardapisearch-v1.htm
Bulk download (POST): https://www.nsf.gov/awardsearch/download?DownloadFileName=YEAR&All=true

Award records are historical obligations, not open solicitations.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from pipeline.http_util import HttpError, fetch_text, post_json
from pipeline.textutil import html_to_text, parse_date, parse_money

RSS_URL = "https://www.nsf.gov/rss/rss_www_funding.xml"
AWARDS_URL = "https://api.nsf.gov/services/v1/awards.json"
AWARD_PAGE = "https://www.nsf.gov/awardsearch/show-award/?AWD_ID={id}"
PRINT_FIELDS = ",".join(
    [
        "id",
        "title",
        "agency",
        "awardeeName",
        "awardeeStateCode",
        "awardeeCity",
        "fundsObligatedAmt",
        "estimatedTotalAmt",
        "date",
        "startDate",
        "expDate",
        "abstractText",
        "piFirstName",
        "piLastName",
        "pdPIName",
        "fundProgramName",
        "program",
        "dirAbbr",
        "divAbbr",
        "cfdaNumber",
        "activeAwd",
        "transType",
    ]
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fetch_funding_rss() -> list[dict]:
    xml_text = fetch_text(RSS_URL, timeout=90)
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        record = {}
        for child in list(item):
            name = _local(child.tag)
            record[name] = (child.text or "").strip()
        title = html_to_text(record.get("title"))
        link = record.get("link") or ""
        if not title or not link.startswith("http"):
            continue
        pub = record.get("pubDate") or ""
        pub_iso = None
        if pub:
            try:
                pub_iso = parsedate_to_datetime(pub).date().isoformat()
            except (TypeError, ValueError, IndexError):
                parsed = parse_date(pub)
                pub_iso = parsed.isoformat() if parsed else None
        items.append(
            {
                "title": title,
                "link": link,
                "description": record.get("description") or "",
                "pub_date": pub_iso,
                "source_url": RSS_URL,
            }
        )
    if not items:
        raise RuntimeError("NSF funding RSS parsed zero items.")
    return items


def _award_from_api(row: dict, retrieved_at: str) -> dict | None:
    award_id = str(row.get("id") or "").strip()
    title = html_to_text(row.get("title") or "")
    if not award_id or not title:
        return None
    pi = " ".join(
        part
        for part in (row.get("piFirstName") or "", row.get("piLastName") or "")
        if part
    ).strip() or (row.get("pdPIName") or None)
    abstract = html_to_text(row.get("abstractText") or "")
    if len(abstract) > 1200:
        abstract = abstract[:1199].rstrip() + "…"
    return {
        "id": f"nsf-award-{award_id}",
        "source_record_id": award_id,
        "title": title,
        "agency": "NSF",
        "agency_name": "National Science Foundation",
        "awardee_name": row.get("awardeeName") or None,
        "awardee_city": row.get("awardeeCity") or None,
        "awardee_state": row.get("awardeeStateCode") or None,
        "pi_name": pi,
        "amount_obligated": parse_money(row.get("fundsObligatedAmt")),
        "estimated_total": parse_money(row.get("estimatedTotalAmt")),
        "award_date": _nsf_date(row.get("date")),
        "start_date": _nsf_date(row.get("startDate")),
        "end_date": _nsf_date(row.get("expDate")),
        "abstract": abstract or None,
        "program": row.get("fundProgramName") or row.get("program") or None,
        "directorate": row.get("dirAbbr") or None,
        "division": row.get("divAbbr") or None,
        "cfda": row.get("cfdaNumber") or None,
        "active": row.get("activeAwd"),
        "transaction_type": row.get("transType") or None,
        "urls": {"official": AWARD_PAGE.format(id=award_id)},
        "source": {
            "id": "nsf_awards_api",
            "name": "NSF Award Search API",
            "retrieved_at": retrieved_at,
            "endpoint": AWARDS_URL,
        },
        "verified_at": retrieved_at,
        "record_type": "historical_award",
        "fact_boundary": "Historical award. This is what NSF awarded, not an open solicitation. PI email addresses from the API are not republished.",
    }


def _nsf_date(value) -> str | None:
    parsed = parse_date(str(value) if value else None)
    return parsed.isoformat() if parsed else None


def fetch_awards(retrieved_at: str, start_date: str = "10/01/2024", max_pages: int = 40, rpp: int = 25) -> dict:
    """Page the public awards API.

    NSF documents rpp upper limit of 25 and 1-based offsets
    (offset=1, then 26, ...). Pagination stops on an empty page or repeated ids.
    The result is a sample unless pages exhaust the API. Coverage is returned
    explicitly and must not be described as a complete census unless exhausted.
    """
    awards = []
    seen = set()
    offset = 1
    pages = 0
    error = None
    for _ in range(max_pages):
        url = (
            f"{AWARDS_URL}?startDateStart={start_date.replace('/', '%2F')}"
            f"&rpp={rpp}&offset={offset}&printFields={PRINT_FIELDS}"
        )
        try:
            # GET via fetch_text; the endpoint is GET.
            import json
            from pipeline.http_util import fetch_bytes

            raw, _info = fetch_bytes(url, timeout=90)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            error = str(exc)
            break
        rows = ((payload.get("response") or {}).get("award")) or []
        if isinstance(rows, dict):
            rows = [rows]
        pages += 1
        if not rows:
            break
        new = 0
        for row in rows:
            record = _award_from_api(row, retrieved_at)
            if not record or record["source_record_id"] in seen:
                continue
            seen.add(record["source_record_id"])
            awards.append(record)
            new += 1
        if new == 0:
            error = "Pagination repeated the same award ids; stopped rather than looping."
            break
        offset += rpp
        time.sleep(0.2)
    exhausted = error is None and pages < max_pages
    return {
        "awards": awards,
        "pages": pages,
        "exhausted": exhausted,
        "error": error,
        "query": {"startDateStart": start_date, "rpp": rpp, "max_pages": max_pages, "endpoint": AWARDS_URL},
        "coverage": (
            "API pagination ended before the page cap, so this pull reached an empty page."
            if exhausted
            else "Partial sample. Do not treat counts or sums as a complete NSF award census."
        ),
    }


def fetch_awards_by_keyword(keyword: str, retrieved_at: str, rpp: int = 25) -> list[dict]:
    """One page of awards for a keyword. Used only as a labeled sample."""
    import json
    from urllib.parse import quote
    from pipeline.http_util import fetch_bytes

    url = f"{AWARDS_URL}?keyword={quote(keyword)}&rpp={rpp}&printFields={PRINT_FIELDS}"
    raw, _info = fetch_bytes(url, timeout=90)
    payload = json.loads(raw.decode("utf-8"))
    rows = ((payload.get("response") or {}).get("award")) or []
    if isinstance(rows, dict):
        rows = [rows]
    out = []
    for row in rows:
        record = _award_from_api(row, retrieved_at)
        if record:
            record["sample_query"] = keyword
            out.append(record)
    return out
