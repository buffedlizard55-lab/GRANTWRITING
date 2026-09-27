"""Grants.gov daily XML extract and search2 / fetchOpportunity cross-check.

Primary source: the official daily extract listed at
https://www.grants.gov/xml-extract
Schema notes: https://www.grants.gov/help/xml-extract/

search2 and fetchOpportunity require no API key:
https://www.grants.gov/api/api-guide
"""

from __future__ import annotations

import random
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

from pipeline.http_util import HttpError, download, fetch_text, post_json
from pipeline.textutil import eastern_today, parse_date

EXTRACT_PAGE = "https://www.grants.gov/xml-extract"
SEARCH_URL = "https://api.grants.gov/v1/api/search2"
FETCH_URL = "https://api.grants.gov/v1/api/fetchOpportunity"
S3_TEMPLATE = "https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/GrantsDBExtract{ymd}v2.zip"

NS = "{http://apply.grants.gov/system/OpportunityDetail-V1.0}"
SYNOPSIS_PREFIX = "OpportunitySynopsisDetail"
FORECAST_PREFIX = "OpportunityForecastDetail"

# Element local names documented in the Grants.gov XML extract field guide,
# plus a few nested names observed in public parsers of the same extract.
FIELD_NAMES = {
    "OpportunityID": "opportunity_id",
    "OpportunityNumber": "number",
    "OpportunityTitle": "title",
    "OpportunityCategory": "opportunity_category",
    "AgencyCode": "agency_code",
    "AgencyName": "agency_name",
    "PostDate": "post_date",
    "CloseDate": "close_date",
    "CloseDateExplanation": "close_date_explanation",
    "ArchiveDate": "archive_date",
    "LastUpdatedDate": "last_updated",
    "CreatedDate": "created_date",
    "EstimatedSynopsisPostDate": "estimated_post_date",
    "EstimatedSynopsisCloseDate": "estimated_close_date",
    "EstimatedAwardDate": "estimated_award_date",
    "EstimatedProjectStartDate": "estimated_project_start",
    "AwardCeiling": "award_ceiling",
    "AwardFloor": "award_floor",
    "EstimatedTotalProgramFunding": "estimated_funding",
    "ExpectedNumberOfAwards": "expected_awards",
    "Description": "description",
    "CostSharingOrMatchingRequirement": "cost_sharing",
    "AdditionalInformationOnEligibility": "eligibility_text",
    "AdditionalInformationText": "additional_text",
    "AdditionalInformationURL": "additional_url",
    "CategoryExplanation": "category_explanation",
    "GrantorContactEmail": "contact_email",
    "GrantorContactName": "contact_name",
    "GrantorContactPhoneNumber": "contact_phone",
    "GrantorContactText": "contact_text",
    "Version": "version",
    "FiscalYear": "fiscal_year",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def discover_extract(today: date | None = None) -> dict:
    """Find the newest v2 extract URL from the official extract page.

    Falls back to the documented S3 name pattern for the last few days if the
    page cannot be parsed. Does not invent a file that was not listed or named
    by that pattern; the caller must download it successfully.
    """
    today = today or eastern_today()
    notes = []
    candidates: list[tuple[str, str]] = []
    try:
        html = fetch_text(EXTRACT_PAGE, timeout=60)
    except HttpError as exc:
        notes.append(f"Extract page fetch failed: {exc}")
        html = ""
    for match in re.finditer(r"https://[^\"'\s>]+GrantsDBExtract(\d{8})v2\.zip", html):
        candidates.append((match.group(1), match.group(0)))
    for match in re.finditer(r"GrantsDBExtract(\d{8})v2\.zip", html):
        ymd = match.group(1)
        url = S3_TEMPLATE.format(ymd=ymd)
        candidates.append((ymd, url))
    if not candidates:
        notes.append("No extract link parsed from the page; trying the documented S3 name for recent dates.")
        for offset in range(0, 5):
            day = today - timedelta(days=offset)
            ymd = day.strftime("%Y%m%d")
            candidates.append((ymd, S3_TEMPLATE.format(ymd=ymd)))
    # Newest date first, unique.
    best: dict[str, str] = {}
    for ymd, url in candidates:
        best[ymd] = url
    if not best:
        raise HttpError("Could not determine a Grants.gov extract URL.")
    ymd = sorted(best)[-1]
    return {
        "file_name": f"GrantsDBExtract{ymd}v2.zip",
        "file_url": best[ymd],
        "ymd": ymd,
        "catalog_url": EXTRACT_PAGE,
        "notes": notes,
    }


def download_extract(meta: dict, cache_dir: Path) -> Path:
    dest = cache_dir / meta["file_name"]
    if dest.exists() and dest.stat().st_size > 1_000_000:
        meta["download"] = "reused_cache"
        return dest
    download(meta["file_url"], dest, timeout=300)
    meta["download"] = "downloaded"
    meta["bytes"] = dest.stat().st_size
    return dest


def _texts(elem: ET.Element) -> list[str]:
    values = []
    if elem.text and elem.text.strip():
        values.append(elem.text.strip())
    for child in list(elem):
        values.extend(_texts(child))
    return values


def _consume_field(raw: dict, name: str, node: ET.Element, seen: set[str]) -> None:
    seen.add(name)
    mapped = FIELD_NAMES.get(name)
    if name in {"CategoryOfFundingActivity", "FundingActivityCategory"}:
        raw["funding_categories"].extend(_texts(node))
    elif name in {"FundingInstrumentType", "FundingInstrument"}:
        raw["instruments"].extend(_texts(node))
    elif name in {"EligibleApplicants", "EligibleApplicant"}:
        raw["applicant_types"].extend(_texts(node))
    elif name in {"CFDANumber", "CFDANumbers", "ALN", "AssistanceListingNumber", "OpportunityCFDA", "AssistanceListing"} or "CFDA" in name or name.startswith("ALN"):
        numbers = re.findall(r"\b\d{2}\.[A-Z0-9]{3}\b", " ".join(_texts(node)))
        titles = [t for t in _texts(node) if not re.fullmatch(r"\d{2}\.[A-Z0-9]{3}", t)]
        if numbers:
            for number in numbers:
                raw["alns"].append({"number": number, "title": titles[0] if len(titles) == 1 else None})
        elif _texts(node) and name in {"CFDANumber", "ALN", "AssistanceListingNumber"}:
            raw["alns"].append({"number": _texts(node)[0], "title": None})
    elif mapped:
        texts = _texts(node)
        if not texts:
            return
        if mapped == "opportunity_category":
            raw[mapped] = next((t for t in texts if re.fullmatch(r"[A-Z]", t)), texts[0])
        elif not raw.get(mapped):
            raw[mapped] = texts[0]
    else:
        seen.add("UNMAPPED:" + name)


def parse_opportunity_element(elem: ET.Element, doc_type: str) -> tuple[dict, set[str]]:
    raw: dict = {
        "doc_type": doc_type,
        "funding_categories": [],
        "instruments": [],
        "applicant_types": [],
        "alns": [],
    }
    seen: set[str] = set()
    nodes = list(elem)
    # Some extracts nest the synopsis fields one level down. If the direct
    # children are wrappers, also read descendants — but never replace a value
    # already taken from a direct child.
    if not any(local_name(child.tag) in {"OpportunityTitle", "OpportunityID"} for child in nodes):
        nodes = [node for node in elem.iter() if node is not elem]
    for child in nodes:
        _consume_field(raw, local_name(child.tag), child, seen)
    # Codes may be comma-separated in a single text node.
    for key in ("funding_categories", "instruments", "applicant_types"):
        split: list[str] = []
        for value in raw[key]:
            for part in re.split(r"[,;|\s]+", value):
                part = part.strip().upper()
                if part and part not in split:
                    split.append(part)
        raw[key] = split
    deduped_alns = []
    seen_alns = set()
    for aln in raw["alns"]:
        if aln["number"] in seen_alns:
            continue
        seen_alns.add(aln["number"])
        deduped_alns.append(aln)
    raw["alns"] = deduped_alns
    return raw, seen


def parse_extract(path: Path) -> tuple[list[dict], dict]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            xml_names = [n for n in archive.namelist() if n.lower().endswith(".xml")]
            if not xml_names:
                raise RuntimeError(f"No XML file inside {path.name}")
            xml_name = max(xml_names, key=lambda n: archive.getinfo(n).file_size)
            extracted = path.with_suffix(".xml")
            with archive.open(xml_name) as src, extracted.open("wb") as dest:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dest.write(chunk)
        xml_path = extracted
        container = path.name
    else:
        xml_path = path
        container = path.name

    records: list[dict] = []
    tag_counts: dict[str, int] = {}
    unmapped: set[str] = set()
    # iterparse keeps memory bounded on the multi-hundred-megabyte extract.
    context = ET.iterparse(xml_path, events=("end",))
    for _event, elem in context:
        name = local_name(elem.tag)
        if name.startswith(SYNOPSIS_PREFIX) or name.startswith(FORECAST_PREFIX):
            doc_type = "forecast" if name.startswith(FORECAST_PREFIX) else "synopsis"
            raw, seen = parse_opportunity_element(elem, doc_type)
            records.append(raw)
            tag_counts[name] = tag_counts.get(name, 0) + 1
            unmapped.update(item for item in seen if item.startswith("UNMAPPED:"))
            elem.clear()
    stats = {
        "container": container,
        "xml_name": xml_path.name,
        "records_parsed": len(records),
        "tag_counts": tag_counts,
        "unmapped_tags": sorted(unmapped)[:80],
    }
    if not records:
        raise RuntimeError(
            "Extract parsed zero opportunity elements. Tag names may have changed. "
            f"Stats: {stats}"
        )
    return records, stats


def search2(payload: dict) -> dict:
    data = post_json(SEARCH_URL, payload, timeout=90)
    if data.get("errorcode") not in (0, "0", None) and data.get("msg") not in (None, "Webservice Succeeds"):
        # Some responses omit errorcode on success. Keep going only if data is present.
        if "data" not in data:
            raise HttpError(f"search2 error: {data.get('msg') or data}")
    return data


def search_hit_count(opp_statuses: str, funding_categories: str = "", agencies: str = "") -> dict:
    payload = {
        "rows": 1,
        "startRecordNum": 0,
        "oppStatuses": opp_statuses,
        "fundingCategories": funding_categories,
        "agencies": agencies,
    }
    data = search2(payload)
    inner = data.get("data") or {}
    return {
        "request": payload,
        "hit_count": inner.get("hitCount"),
        "error": data.get("msg") if data.get("errorcode") not in (0, "0", None) else None,
        "endpoint": SEARCH_URL,
    }


def search_ids(opp_statuses: str, funding_categories: str = "", rows: int = 500, max_pages: int = 20) -> dict:
    ids: list[str] = []
    hit_count = None
    start = 0
    pages = 0
    while pages < max_pages:
        data = search2(
            {
                "rows": rows,
                "startRecordNum": start,
                "oppStatuses": opp_statuses,
                "fundingCategories": funding_categories,
                "sortBy": "openDate|desc",
            }
        )
        inner = data.get("data") or {}
        hit_count = inner.get("hitCount", hit_count)
        hits = inner.get("oppHits") or []
        pages += 1
        if not hits:
            break
        for hit in hits:
            if hit.get("id") is not None:
                ids.append(str(hit["id"]))
        start += len(hits)
        if hit_count is not None and start >= int(hit_count):
            break
        if len(hits) < rows:
            break
        time.sleep(0.25)
    return {"hit_count": hit_count, "ids": ids, "pages": pages, "endpoint": SEARCH_URL}


def fetch_opportunity(opportunity_id: str) -> dict:
    data = post_json(FETCH_URL, {"opportunityId": int(opportunity_id)}, timeout=60)
    return data


def _api_close_date(payload: dict) -> str | None:
    synopsis = payload.get("synopsis") or payload.get("forecast") or {}
    for key in ("responseDate", "closeDate", "estSynopsisCloseDateStr", "responseDateStr"):
        if synopsis.get(key):
            parsed = parse_date(str(synopsis.get(key)))
            if parsed:
                return parsed.isoformat()
    return None


def api_record_to_raw(payload: dict, hit: dict | None = None) -> dict:
    """Map a fetchOpportunity payload into the extract-shaped dict the normalizer expects."""
    data = payload.get("data") or payload
    synopsis = data.get("synopsis") or data.get("forecast") or {}
    doc = (data.get("docType") or (hit or {}).get("docType") or "synopsis").lower()
    applicant_codes = []
    for item in synopsis.get("applicantTypes") or []:
        if isinstance(item, dict) and item.get("id"):
            applicant_codes.append(str(item["id"]))
        elif isinstance(item, str):
            applicant_codes.append(item)
    categories = []
    for item in synopsis.get("fundingActivityCategories") or []:
        if isinstance(item, dict) and item.get("id"):
            categories.append(str(item["id"]))
    instruments = []
    for item in synopsis.get("fundingInstruments") or []:
        if isinstance(item, dict) and item.get("id"):
            instruments.append(str(item["id"]))
    alns = []
    for item in data.get("alns") or []:
        if isinstance(item, dict):
            alns.append({"number": item.get("alnNumber") or item.get("number") or "", "title": item.get("programTitle")})
        elif item:
            alns.append({"number": str(item), "title": None})
    if not alns:
        for number in (hit or {}).get("alnist") or []:
            alns.append({"number": str(number), "title": None})
    return {
        "doc_type": "forecast" if "forecast" in doc else "synopsis",
        "opportunity_id": str(data.get("id") or (hit or {}).get("id") or ""),
        "number": data.get("opportunityNumber") or (hit or {}).get("number"),
        "title": data.get("opportunityTitle") or synopsis.get("opportunityTitle") or (hit or {}).get("title"),
        "agency_code": synopsis.get("agencyCode") or data.get("owningAgencyCode") or (hit or {}).get("agencyCode"),
        "agency_name": synopsis.get("agencyName") or (hit or {}).get("agencyName"),
        "post_date": synopsis.get("postingDate") or (hit or {}).get("openDate"),
        "close_date": synopsis.get("responseDate") or synopsis.get("closeDate") or (hit or {}).get("closeDate"),
        "archive_date": synopsis.get("archiveDate"),
        "last_updated": synopsis.get("lastUpdatedDate"),
        "award_ceiling": synopsis.get("awardCeiling"),
        "award_floor": synopsis.get("awardFloor"),
        "estimated_funding": synopsis.get("estimatedFunding") or synopsis.get("estimatedTotalFunding"),
        "expected_awards": synopsis.get("expectedNumberOfAwards") or synopsis.get("numberOfAwards"),
        "cost_sharing": synopsis.get("costSharing"),
        "description": synopsis.get("synopsisDesc") or synopsis.get("forecastDesc") or "",
        "eligibility_text": synopsis.get("applicantEligibilityDesc") or synopsis.get("eligibilityDesc"),
        "funding_categories": categories,
        "instruments": instruments,
        "applicant_types": applicant_codes,
        "alns": [item for item in alns if item.get("number")],
        "contact_name": synopsis.get("agencyContactName"),
        "contact_email": synopsis.get("agencyContactEmail"),
        "contact_phone": synopsis.get("agencyContactPhone"),
        "contact_text": synopsis.get("agencyContactDesc"),
        "opportunity_category": (data.get("opportunityCategory") or {}).get("category") if isinstance(data.get("opportunityCategory"), dict) else None,
    }


def collect_via_api(max_details: int = 250) -> tuple[list[dict], dict]:
    """Fallback when the daily extract cannot be downloaded.

    List rows come from search2. Detail fields come from fetchOpportunity for a
    capped sample, newest open date first. Records without a detail fetch keep
    only the list fields and must not invent the rest.
    """
    listing = search_ids("posted|forecasted", funding_categories="ST", rows=250, max_pages=12)
    hits_by_id = {}
    # search_ids currently returns ids only. Pull pages again with hits so list-only
    # records still have titles. Bounded by the same page cap.
    start = 0
    pages = 0
    while pages < 12:
        data = search2(
            {
                "rows": 250,
                "startRecordNum": start,
                "oppStatuses": "posted|forecasted",
                "fundingCategories": "ST",
                "sortBy": "openDate|desc",
            }
        )
        inner = data.get("data") or {}
        hits = inner.get("oppHits") or []
        pages += 1
        if not hits:
            break
        for hit in hits:
            if hit.get("id") is not None:
                hits_by_id[str(hit["id"])] = hit
        start += len(hits)
        hit_count = inner.get("hitCount")
        if hit_count is not None and start >= int(hit_count):
            break
        if len(hits) < 250:
            break
        time.sleep(0.2)
    raw_records = []
    detailed = 0
    detail_errors = 0
    for opp_id, hit in hits_by_id.items():
        if detailed < max_details:
            time.sleep(0.25)
            try:
                payload = fetch_opportunity(opp_id)
                raw = api_record_to_raw(payload, hit)
                raw["detail_fetched"] = True
                detailed += 1
            except Exception:
                raw = api_record_to_raw({"data": {"id": opp_id}}, hit)
                raw["detail_fetched"] = False
                detail_errors += 1
        else:
            raw = api_record_to_raw({"data": {"id": opp_id}}, hit)
            raw["detail_fetched"] = False
        raw_records.append(raw)
    return raw_records, {
        "mode": "search2_fallback",
        "hit_count": listing.get("hit_count"),
        "ids_seen": len(hits_by_id),
        "details_fetched": detailed,
        "detail_errors": detail_errors,
        "detail_cap": max_details,
        "note": "Extract download failed. Catalog is limited to Grants.gov search2 rows in category ST, with fetchOpportunity details for a capped subset. Amounts are missing where detail was not fetched. This is not the full research-agency catalog.",
    }


def spot_check(ids: list[str], catalog_by_source_id: dict[str, dict], sample_size: int = 5) -> dict:
    if not ids:
        return {"status": "skipped", "reason": "No open opportunity ids to check."}
    sample = ids[:]
    random.shuffle(sample)
    sample = sample[:sample_size]
    results = []
    for opp_id in sample:
        time.sleep(0.3)
        try:
            payload = fetch_opportunity(opp_id)
        except Exception as exc:  # keep the rest of the check
            results.append({"id": opp_id, "status": "fetch_failed", "error": str(exc)})
            continue
        data = payload.get("data") or {}
        synopsis = data.get("synopsis") or data.get("forecast") or {}
        catalog = catalog_by_source_id.get(str(opp_id)) or catalog_by_source_id.get(opp_id)
        comparison = {
            "id": str(opp_id),
            "status": "checked",
            "api_title": synopsis.get("opportunityTitle") or data.get("opportunityTitle"),
            "api_number": data.get("opportunityNumber") or synopsis.get("opportunityNumber"),
            "api_agency": synopsis.get("agencyCode") or data.get("owningAgencyCode"),
            "api_close": _api_close_date(data),
            "mismatches": [],
        }
        if not catalog:
            comparison["status"] = "not_in_catalog"
            results.append(comparison)
            continue
        from pipeline.textutil import html_to_text

        api_title = html_to_text(comparison["api_title"] or "")
        comparison["api_title"] = api_title or comparison["api_title"]
        if api_title and api_title != catalog["title"]:
            comparison["mismatches"].append("title")
        if comparison["api_number"] and catalog.get("number") and comparison["api_number"].strip() != catalog["number"]:
            comparison["mismatches"].append("number")
        if comparison["api_agency"] and catalog.get("agency_code") and comparison["api_agency"].strip() != catalog["agency_code"]:
            comparison["mismatches"].append("agency_code")
        if comparison["api_close"] and catalog.get("dates", {}).get("close") and comparison["api_close"] != catalog["dates"]["close"]:
            comparison["mismatches"].append("close_date")
        comparison["catalog_close"] = (catalog.get("dates") or {}).get("close")
        comparison["official_url"] = catalog.get("urls", {}).get("official")
        results.append(comparison)
    mismatches = [r for r in results if r.get("mismatches")]
    return {
        "status": "discrepancy" if mismatches else "ok",
        "endpoint": FETCH_URL,
        "checked": len(results),
        "mismatch_count": len(mismatches),
        "results": results,
    }
