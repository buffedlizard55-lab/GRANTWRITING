"""Record normalization: status, inclusion, quotes, and field quality.

Every conclusion that is not copied from a source field is labeled.
"""

from __future__ import annotations

import re
from datetime import date

from pipeline.codes import (
    APPLICANT_TYPE,
    FUNDING_CATEGORY,
    FUNDING_INSTRUMENT,
    OPPORTUNITY_CATEGORY,
    RESEARCH_AGENCY_NAME_PHRASES,
    RESEARCH_AGENCY_PREFIXES,
    RESEARCH_TERM_PATTERN,
    SBIR_STTR_PATTERN,
    TOP_AGENCY_NAMES,
)
from pipeline.textutil import (
    html_to_text,
    iso_date,
    parse_bool_yes_no,
    parse_date,
    parse_int,
    parse_money,
    split_sentences,
)
from pipeline.topics import classify_topics

OBJECTIVE_PATTERNS = (
    re.compile(r"\b(purpose of this|seeks to|seeks proposals|this (program|opportunity|solicitation|foa|nofo) (seeks|supports|funds|will support)|areas of interest|research objectives|the goal of)\b", re.I),
)
REQUIREMENT_PATTERNS = (
    re.compile(r"\b(applicants must|eligible applicants|must include|are required to|principal investigator|project director must|cost sharing|matching requirement)\b", re.I),
)
REGISTRATION_PATTERNS = (
    re.compile(r"\b(SAM\.gov|System for Award Management|Unique Entity Identifier|\bUEI\b|Grants\.gov registration|eRA Commons|Research\.gov)\b", re.I),
)
CANCELLATION_PATTERN = re.compile(
    r"\b(this (opportunity|solicitation|announcement|foa|nofo) (has been |is )?(cancelled|canceled)|solicitation (cancelled|canceled)|no longer accepting applications)\b",
    re.I,
)
DURATION_PATTERN = re.compile(
    r"\b(project period|period of performance|award period|up to \d+ years?|\d+\s*-\s*year)\b",
    re.I,
)
LOI_PATTERN = re.compile(
    r"\b(letter of intent|letters of intent|pre-application|preliminary proposal|concept paper)\b",
    re.I,
)


def top_agency_code(code: str | None) -> str:
    if not code:
        return ""
    return str(code).split("-")[0].strip().upper()


def grouping_name(code: str | None) -> str | None:
    top = top_agency_code(code)
    return TOP_AGENCY_NAMES.get(top)


def label_code(table: dict[str, str], code: str) -> dict:
    cleaned = (code or "").strip().upper()
    return {"code": cleaned, "label": table.get(cleaned)}


def inclusion_basis(agency_code: str, agency_name: str, categories: list[str], instruments: list[str], text: str) -> list[dict]:
    bases = []
    codes = {c.upper() for c in categories if c}
    if "ST" in codes:
        bases.append(
            {
                "id": "funding_category_ST",
                "label": "Official funding category includes Science and Technology and other Research and Development (ST).",
            }
        )
    agency = (agency_code or "").upper()
    for prefix in RESEARCH_AGENCY_PREFIXES:
        # Match the full code, a hyphenated sub-agency, or a longer official code
        # that continues the prefix (HHS-NIH11). Do not match a short prefix that
        # is only a substring of an unrelated code.
        if agency == prefix or agency.startswith(prefix + "-") or (
            len(prefix) >= 5 and agency.startswith(prefix)
        ):
            bases.append(
                {
                    "id": "research_agency_prefix",
                    "label": (
                        f"Agency code {agency_code} matches the platform research-funder "
                        f"prefix {prefix}. This is a platform rule, not a Grants.gov flag."
                    ),
                }
            )
            break
    name = (agency_name or "").lower()
    for phrase in RESEARCH_AGENCY_NAME_PHRASES:
        if phrase in name:
            bases.append(
                {
                    "id": "research_agency_name",
                    "label": f"Official agency name contains “{phrase}”. Platform inclusion rule.",
                }
            )
            break
    if re.search(SBIR_STTR_PATTERN, text or "", re.I) or re.search(SBIR_STTR_PATTERN, agency_name or "", re.I):
        bases.append(
            {
                "id": "sbir_sttr",
                "label": "Title, number, or description contains SBIR or STTR.",
            }
        )
    instrument_ids = {i.upper() for i in instruments}
    grant_like = not instrument_ids or instrument_ids & {"G", "CA", "GRANT", "COOPERATIVE AGREEMENT"}
    if grant_like and re.search(RESEARCH_TERM_PATTERN, text or "", re.I):
        bases.append(
            {
                "id": "research_terms_and_grant_instrument",
                "label": "Grant or cooperative agreement whose official text contains a high-precision research phrase (research and development, scientific research, BAA, NOFO, or FOA).",
            }
        )
    # De-duplicate by id, preserve order.
    seen = set()
    unique = []
    for item in bases:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        unique.append(item)
    return unique


def derive_status(
    *,
    doc_type: str,
    post: date | None,
    close: date | None,
    archive: date | None,
    as_of: date,
    description: str,
    record_kind: str,
) -> tuple[str, str, list[str]]:
    flags: list[str] = []
    if CANCELLATION_PATTERN.search(description or ""):
        flags.append("possible_cancellation_language")
        return (
            "verification_required",
            "Official text contains cancellation language. Status is not treated as open. Confirm on the official page.",
            flags,
        )
    if record_kind == "program":
        flags.append("standing_program")
        if close and close < as_of:
            return "closed", "Program feed item has a close date before the as-of date.", flags
        if close and close >= as_of:
            return "open", "Program feed item has a published close date on or after the as-of date.", flags
        flags.append("deadline_not_published")
        return (
            "open_program",
            "Standing program page. No application deadline was published in the feed item. This is not the same as an open Grants.gov synopsis.",
            flags,
        )
    if doc_type == "forecast" or record_kind == "forecast":
        if close and close < as_of:
            flags.append("forecast_close_date_passed")
            return (
                "closed",
                "Forecast record whose estimated close date is before the as-of date. Not listed as open.",
                flags,
            )
        if post and post < as_of:
            flags.append("forecast_post_date_passed")
            return (
                "upcoming",
                "Forecast record. Estimated synopsis post date is before the as-of date and no posted synopsis replaced it in this extract. Not treated as open.",
                flags,
            )
        return (
            "upcoming",
            "Grants.gov forecast record. The opportunity is announced but not posted as an open synopsis in this extract.",
            flags,
        )
    if archive and archive < as_of and (not close or close < as_of):
        return "archived", "Archive date published in the extract is before the as-of date.", flags
    if close and close < as_of:
        flags.append("deadline_passed")
        return "closed", "Published close date is before the as-of date. Not listed as an open opportunity.", flags
    if close and close == as_of:
        flags.append("closes_today")
        flags.append("deadline_is_date_only")
        return (
            "open",
            "Published close date is the as-of date. The source published a date, not a time. Confirm the cutoff time on the official page.",
            flags,
        )
    if close and close > as_of:
        flags.append("deadline_is_date_only")
        return "open", "Posted synopsis with a close date on or after the as-of date.", flags
    flags.append("deadline_not_published")
    if archive and archive < as_of:
        return "archived", "Archive date is before the as-of date and no close date was published.", flags
    return (
        "open",
        "Posted synopsis with no close date in the extract. Treated as open only because it is still in the active extract; the deadline was not published. Verification required.",
        flags,
    )


def extract_quotes(description: str, patterns: tuple[re.Pattern[str], ...], limit: int = 5) -> list[dict]:
    quotes = []
    for sentence in split_sentences(description):
        for pattern in patterns:
            match = pattern.search(sentence)
            if match:
                text = sentence.strip()
                if len(text) > 700:
                    text = text[:699].rstrip() + "…"
                quotes.append({"text": text, "matched": match.group(0), "kind": "extracted_quote"})
                break
        if len(quotes) >= limit:
            break
    return quotes


def normalize_grant_record(raw: dict, as_of: date, retrieved_at: str, source: dict) -> dict | None:
    """Turn a parsed Grants.gov extract record into a catalog record.

    Returns None when the record cannot be identified. Does not fill missing facts.
    """
    source_id = (raw.get("opportunity_id") or "").strip()
    title = html_to_text(raw.get("title") or "")
    if not source_id or not title:
        return None
    agency_code = (raw.get("agency_code") or "").strip()
    agency_name = html_to_text(raw.get("agency_name") or "") or agency_code
    description = html_to_text(raw.get("description") or "")
    description, truncated = (description[:12000], len(description) > 12000) if len(description) > 12000 else (description, False)
    number = (raw.get("number") or "").strip() or None
    doc_type = raw.get("doc_type") or "synopsis"
    record_kind = "forecast" if doc_type == "forecast" else "opportunity"

    post = parse_date(raw.get("post_date"))
    close = parse_date(raw.get("close_date"))
    archive = parse_date(raw.get("archive_date"))
    updated = parse_date(raw.get("last_updated"))
    estimated_post = parse_date(raw.get("estimated_post_date"))
    estimated_award = parse_date(raw.get("estimated_award_date"))
    estimated_start = parse_date(raw.get("estimated_project_start"))
    if record_kind == "forecast" and estimated_post and not post:
        post = estimated_post
    if record_kind == "forecast" and not close:
        close = parse_date(raw.get("estimated_close_date"))

    status, status_basis, flags = derive_status(
        doc_type=doc_type,
        post=post,
        close=close,
        archive=archive,
        as_of=as_of,
        description=description,
        record_kind=record_kind,
    )
    if truncated:
        flags.append("description_truncated")
    if post and close and close < post:
        flags.append("close_date_before_post_date")

    categories = []
    for code in raw.get("funding_categories") or []:
        item = label_code(FUNDING_CATEGORY, code)
        if item["code"]:
            if not item["label"]:
                flags.append("unknown_funding_category_code")
            categories.append(item)
    category_explanation = html_to_text(raw.get("category_explanation") or "") or None

    instruments = []
    for code in raw.get("instruments") or []:
        item = label_code(FUNDING_INSTRUMENT, code)
        if item["code"]:
            if not item["label"]:
                flags.append("unknown_instrument_code")
            instruments.append(item)

    applicants = []
    for code in raw.get("applicant_types") or []:
        item = label_code(APPLICANT_TYPE, code)
        if item["code"]:
            if not item["label"]:
                flags.append("unknown_applicant_code")
            applicants.append(item)
    if any(a["code"] == "99" for a in applicants):
        flags.append("unrestricted_eligibility")
    if not applicants:
        flags.append("eligibility_codes_not_published")

    eligibility_text = html_to_text(raw.get("eligibility_text") or "") or None
    if not eligibility_text:
        flags.append("eligibility_text_not_published")

    ceiling = parse_money(raw.get("award_ceiling"))
    floor = parse_money(raw.get("award_floor"))
    estimated = parse_money(raw.get("estimated_funding"))
    expected = parse_int(raw.get("expected_awards"))
    cost_sharing = parse_bool_yes_no(raw.get("cost_sharing"))
    if ceiling is None and floor is None and estimated is None:
        flags.append("amounts_not_published")
    if cost_sharing is True:
        flags.append("cost_sharing_required")
    if cost_sharing is None:
        flags.append("cost_sharing_not_published")

    alns = []
    for entry in raw.get("alns") or []:
        if isinstance(entry, dict):
            number_aln = (entry.get("number") or "").strip()
            title_aln = html_to_text(entry.get("title") or "") or None
        else:
            number_aln = str(entry).strip()
            title_aln = None
        if number_aln:
            alns.append({"number": number_aln, "title": title_aln})

    contact = {
        "name": html_to_text(raw.get("contact_name") or "") or None,
        "email": (raw.get("contact_email") or "").strip() or None,
        "phone": html_to_text(raw.get("contact_phone") or "") or None,
        "text": html_to_text(raw.get("contact_text") or "") or None,
    }
    if not any(contact.values()):
        flags.append("contact_not_published")

    text_for_scope = " ".join(
        part for part in (title, number or "", description, agency_name) if part
    )
    bases = inclusion_basis(
        agency_code,
        agency_name,
        [c["code"] for c in categories],
        [i["code"] for i in instruments],
        text_for_scope,
    )
    topics = classify_topics([title, description, category_explanation or "", agency_name])
    if not topics and any(b["id"] in {"research_agency_prefix", "research_agency_name"} for b in bases):
        if "national institutes of health" in agency_name.lower() or agency_code.upper().startswith("HHS-NIH"):
            topics = [
                {
                    "id": "biomedical",
                    "label": "Biomedical research",
                    "matched_terms": [],
                    "method": "agency_default",
                    "note": "No topic term matched the text. Labeled biomedical because the official agency is NIH. Not a statement that the announcement is limited to biomedical research.",
                }
            ]

    official = f"https://www.grants.gov/search-results-detail/{source_id}"
    opportunity_category = None
    if raw.get("opportunity_category"):
        opportunity_category = label_code(OPPORTUNITY_CATEGORY, raw["opportunity_category"])

    missing = [flag for flag in flags if flag.endswith("_not_published")]
    return {
        "id": f"gg-{source_id}",
        "source_record_id": source_id,
        "number": number,
        "title": title,
        "agency_code": agency_code or None,
        "agency_name": agency_name or None,
        "top_agency_code": top_agency_code(agency_code) or None,
        "top_agency_grouping_label": grouping_name(agency_code),
        "status": status,
        "status_basis": status_basis,
        "doc_type": doc_type,
        "record_kind": record_kind,
        "opportunity_category": opportunity_category,
        "instruments": instruments,
        "funding_categories": categories,
        "category_explanation": category_explanation,
        "applicant_types": applicants,
        "eligibility_text": eligibility_text,
        "description": description,
        "objective_quotes": extract_quotes(description, OBJECTIVE_PATTERNS),
        "requirement_quotes": extract_quotes(description, REQUIREMENT_PATTERNS),
        "registration_quotes": extract_quotes(description, REGISTRATION_PATTERNS, limit=4),
        "duration_quotes": extract_quotes(description, (DURATION_PATTERN,), limit=3),
        "loi_quotes": extract_quotes(description, (LOI_PATTERN,), limit=3),
        "dates": {
            "post": iso_date(post),
            "close": iso_date(close),
            "archive": iso_date(archive),
            "last_updated": iso_date(updated),
            "estimated_post": iso_date(estimated_post),
            "estimated_award": iso_date(estimated_award),
            "estimated_project_start": iso_date(estimated_start),
        },
        "funding": {
            "ceiling": ceiling,
            "floor": floor,
            "estimated_total": estimated,
            "expected_awards": expected,
            "cost_sharing": cost_sharing,
        },
        "aln": alns,
        "contact": contact,
        "urls": {
            "official": official,
            "application": official,
            "source_catalog": source.get("catalog_url"),
            "extract_file": source.get("file_url"),
        },
        "topics": topics,
        "is_sbir_sttr": any(b["id"] == "sbir_sttr" for b in bases) or bool(re.search(SBIR_STTR_PATTERN, text_for_scope, re.I)),
        "inclusion": {
            "research_relevant": bool(bases),
            "basis": bases,
        },
        "flags": sorted(set(flags)),
        "field_quality": {"missing": missing},
        "source": {
            "id": source["id"],
            "name": source["name"],
            "retrieved_at": retrieved_at,
            "extract_file": source.get("file_name"),
        },
        "verified_at": retrieved_at,
        "fact_boundary": "Fields other than topics, inclusion, flags, status_basis, and extracted quotes are copied from the official extract. Topics and inclusion are platform classifications. Quotes are sentences copied from the official description.",
    }


def normalize_program_record(item: dict, as_of: date, retrieved_at: str) -> dict | None:
    title = html_to_text(item.get("title") or "")
    link = (item.get("link") or "").strip()
    if not title or not link:
        return None
    description = html_to_text(item.get("description") or "")
    post = parse_date(item.get("pub_date"))
    status, status_basis, flags = derive_status(
        doc_type="program",
        post=post,
        close=None,
        archive=None,
        as_of=as_of,
        description=description,
        record_kind="program",
    )
    topics = classify_topics([title, description])
    record_id = re.sub(r"[^a-z0-9]+", "-", link.lower()).strip("-")[-80:]
    return {
        "id": f"nsf-program-{record_id}",
        "source_record_id": link,
        "number": None,
        "title": title,
        "agency_code": "NSF",
        "agency_name": "U.S. National Science Foundation",
        "top_agency_code": "NSF",
        "top_agency_grouping_label": "National Science Foundation",
        "status": status,
        "status_basis": status_basis,
        "doc_type": "program",
        "record_kind": "program",
        "opportunity_category": None,
        "instruments": [],
        "funding_categories": [],
        "category_explanation": None,
        "applicant_types": [],
        "eligibility_text": None,
        "description": description[:12000],
        "objective_quotes": extract_quotes(description, OBJECTIVE_PATTERNS),
        "requirement_quotes": extract_quotes(description, REQUIREMENT_PATTERNS),
        "registration_quotes": extract_quotes(description, REGISTRATION_PATTERNS, limit=3),
        "duration_quotes": extract_quotes(description, (DURATION_PATTERN,), limit=2),
        "loi_quotes": extract_quotes(description, (LOI_PATTERN,), limit=2),
        "dates": {
            "post": iso_date(post),
            "close": None,
            "archive": None,
            "last_updated": iso_date(post),
            "estimated_post": None,
            "estimated_award": None,
            "estimated_project_start": None,
        },
        "funding": {
            "ceiling": None,
            "floor": None,
            "estimated_total": None,
            "expected_awards": None,
            "cost_sharing": None,
        },
        "aln": [],
        "contact": {"name": None, "email": None, "phone": None, "text": None},
        "urls": {"official": link, "application": link, "source_catalog": "https://www.nsf.gov/rss/rss_www_funding.xml"},
        "topics": topics,
        "is_sbir_sttr": False,
        "inclusion": {
            "research_relevant": True,
            "basis": [
                {
                    "id": "nsf_funding_feed",
                    "label": "Item from the official NSF funding opportunities RSS feed.",
                }
            ],
        },
        "flags": sorted(set(flags + ["amounts_not_published", "eligibility_codes_not_published", "deadline_not_published"])),
        "field_quality": {"missing": ["deadline", "amounts", "eligibility_codes"]},
        "source": {
            "id": "nsf_funding_rss",
            "name": "NSF funding opportunities RSS",
            "retrieved_at": retrieved_at,
        },
        "verified_at": retrieved_at,
        "fact_boundary": "Title, link, description, and publication date come from the NSF RSS item. No deadline or amount is inferred. Topics are keyword classifications.",
    }
