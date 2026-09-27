"""Refresh the verified catalog from official sources.

Grants.gov extract is required. NSF, NIH, and USAspending failures are recorded
and do not erase a successful opportunity catalog. An empty or invalid catalog
is not published.
"""

from __future__ import annotations

import argparse
import json
import traceback
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from pipeline.http_util import HttpError
from pipeline.model import normalize_grant_record, normalize_program_record
from pipeline.publish import publish
from pipeline.sources_grantsgov import (
    SEARCH_URL,
    collect_via_api,
    discover_extract,
    download_extract,
    parse_extract,
    search_hit_count,
    search_ids,
    spot_check,
)
from pipeline.sources_nih import collect_samples
from pipeline.sources_nsf import fetch_awards, fetch_funding_rss
from pipeline.sources_usaspending import collect_for_catalog_alns
from pipeline.textutil import EASTERN, eastern_today
from pipeline.topics import classify_topics
from pipeline.validate_catalog import CatalogError, assert_valid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "data"
CACHE = ROOT / "pipeline" / "cache"

LIMITATIONS = [
    "Grants.gov is the system of record for federal grant opportunities. Some research funding, including many contract BAAs, is announced on SAM.gov and is not in this catalog unless the agency also posts it to Grants.gov.",
    "A blank amount, deadline, eligibility list, or contact is published as not published. It is not treated as zero and it is not guessed.",
    "Topic tags are keyword classifications of official text, or a labeled NIH agency default when no term matched. They are not official agency categories.",
    "Inclusion of a non-ST opportunity from a research agency is a platform rule. The rule id is stored on the record.",
    "Status is derived from the extract dates and the America/New_York as-of date. A close date is a date, not a time, unless the source published a time — this extract publishes dates.",
    "Forecasts are upcoming, not open. Cancellation language in the description sets status to verification required rather than open.",
    "NSF RSS items are standing program pages. They are not given an invented deadline.",
    "Historical award files are samples unless the coverage note says the source was exhausted. Sums of sample amounts are not agency budgets.",
    "USAspending rows are obligations under assistance listings that appear on cataloged opportunities. They are not solicitations.",
    "This platform does not estimate the probability of winning an award.",
    "Simpler.Grants.gov requires an API key and is not used.",
    "The daily extract can lag the website by hours. Last verified is the pipeline retrieval time, not a claim that a program officer confirmed the record.",
]


def _now() -> str:
    return datetime.now(EASTERN).isoformat(timespec="seconds")


def _keep(record: dict, as_of) -> bool:
    status = record["status"]
    if status in {"open", "open_program", "verification_required"}:
        return True
    if status == "upcoming":
        post = (record.get("dates") or {}).get("estimated_post") or (record.get("dates") or {}).get("post")
        if post and post < (as_of - timedelta(days=540)).isoformat():
            return False
        return True
    if status == "closed":
        close = (record.get("dates") or {}).get("close")
        return bool(close and close >= (as_of - timedelta(days=120)).isoformat())
    return False


def _dedupe(records: list[dict]) -> list[dict]:
    chosen: dict[str, dict] = {}
    for record in records:
        current = chosen.get(record["id"])
        if current is None:
            chosen[record["id"]] = record
            continue
        prefer_new = current["record_kind"] == "forecast" and record["record_kind"] == "opportunity"
        winner = record if prefer_new else current
        winner["flags"] = sorted(set(winner.get("flags") or []) | {"duplicate_source_record_merged"})
        chosen[record["id"]] = winner
    return list(chosen.values())


def _excluded_summary(records: list[dict]) -> dict:
    rows = [r for r in records if not r["inclusion"]["research_relevant"]]
    by_agency = Counter((r.get("top_agency_code") or "UNKNOWN") for r in rows)
    by_category = Counter(
        code
        for r in rows
        for code in (c["code"] for c in r.get("funding_categories") or [])
    )
    return {
        "excluded_not_research_relevant": len(rows),
        "by_top_agency": by_agency.most_common(30),
        "by_funding_category": by_category.most_common(20),
        "note": "Excluded from the published catalog by the platform research-scope rules. Not a claim that the opportunity is unofficial.",
    }


def _attach_award_topics(awards: list[dict]) -> None:
    for award in awards:
        award["topics"] = classify_topics(
            [award.get("title") or "", award.get("abstract") or "", award.get("program") or ""]
        )


def build_from_extract(raw_records: list[dict], as_of, retrieved_at: str, source: dict) -> tuple[list[dict], dict]:
    normalized = []
    dropped_unidentifiable = 0
    for raw in raw_records:
        record = normalize_grant_record(raw, as_of, retrieved_at, source)
        if record is None:
            dropped_unidentifiable += 1
            continue
        normalized.append(record)
    normalized = _dedupe(normalized)
    excluded = _excluded_summary(normalized)
    research = [r for r in normalized if r["inclusion"]["research_relevant"]]
    kept = [r for r in research if _keep(r, as_of)]
    omitted_old = len(research) - len(kept)
    kept.sort(key=lambda r: ((r.get("dates") or {}).get("close") or "9999-99-99", r["title"]))
    stats = {
        "parsed": len(raw_records),
        "identifiable": len(normalized) + 0,
        "dropped_unidentifiable": dropped_unidentifiable,
        "after_dedupe": len(normalized),
        "research_relevant": len(research),
        "published": len(kept),
        "omitted_old_or_archived_research_records": omitted_old,
        "excluded": excluded,
    }
    # fix identifiable count
    stats["identifiable"] = len(normalized) + dropped_unidentifiable
    return kept, stats


def cross_check(opportunities: list[dict]) -> dict:
    report: dict = {"endpoint": SEARCH_URL}
    try:
        posted = search_hit_count("posted|forecasted")
        science = search_hit_count("posted|forecasted", funding_categories="ST")
        report["posted_or_forecasted_all_categories"] = posted
        report["posted_or_forecasted_ST"] = science
    except Exception as exc:
        report["status"] = "unavailable"
        report["error"] = str(exc)
        return report

    our_st = [
        r
        for r in opportunities
        if r["status"] in {"open", "upcoming"}
        and any(c["code"] == "ST" for c in r.get("funding_categories") or [])
        and r["record_kind"] != "program"
    ]
    api_count = (report.get("posted_or_forecasted_ST") or {}).get("hit_count")
    report["catalog_open_or_upcoming_ST"] = len(our_st)
    if isinstance(api_count, int) and api_count >= 0:
        delta = abs(api_count - len(our_st))
        report["absolute_difference"] = delta
        report["status"] = "ok" if api_count == 0 or delta / max(api_count, 1) <= 0.15 else "discrepancy"
        report["interpretation"] = (
            "Compares Grants.gov search2 hitCount for posted|forecasted and funding category ST "
            "with catalog records that are open or upcoming, category ST, and not NSF program pages. "
            "A difference can come from extract timing, closed-but-listed rows, or parser loss. "
            "search2 still returns forecasts whose forecast date is years old. This catalog omits forecasts "
            "whose post or estimated post date is more than 18 months before the as-of date, so those ids "
            "can appear in in_api_not_in_catalog without being open opportunities. The difference is shown, not hidden."
        )
        if api_count <= 1500:
            try:
                id_pull = search_ids("posted|forecasted", funding_categories="ST", rows=250, max_pages=8)
                api_ids = set(id_pull["ids"])
                our_ids = {r["source_record_id"] for r in our_st}
                report["id_overlap"] = {
                    "api_ids_retrieved": len(api_ids),
                    "api_hit_count": id_pull["hit_count"],
                    "in_api_not_in_catalog": sorted(api_ids - our_ids)[:40],
                    "in_api_not_in_catalog_count": len(api_ids - our_ids),
                    "in_catalog_not_in_api_sample": sorted(our_ids - api_ids)[:40] if len(api_ids) >= api_count else [],
                }
            except Exception as exc:
                report["id_overlap_error"] = str(exc)
    else:
        report["status"] = "unavailable"
    open_ids = [r["source_record_id"] for r in opportunities if r["status"] == "open" and r["id"].startswith("gg-")]
    try:
        report["spot_check"] = spot_check(open_ids, {r["source_record_id"]: r for r in opportunities}, sample_size=5)
    except Exception as exc:
        report["spot_check"] = {"status": "unavailable", "error": str(exc)}
    return report


def refresh(out_dir: Path, cache_dir: Path, skip_awards: bool = False, fixture: Path | None = None) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    as_of = eastern_today()
    retrieved_at = _now()
    sources = []
    errors = []

    if fixture:
        extract_meta = {
            "id": "grantsgov_extract",
            "name": "Grants.gov XML extract (fixture)",
            "file_name": fixture.name,
            "file_url": None,
            "catalog_url": "https://www.grants.gov/xml-extract",
            "notes": ["Fixture file. Not a live extract."],
        }
        raw_records, parse_stats = parse_extract(fixture)
    else:
        extract_meta = discover_extract(as_of)
        extract_meta["id"] = "grantsgov_extract"
        extract_meta["name"] = "Grants.gov daily XML extract"
        path = None
        download_error = None
        try:
            path = download_extract(extract_meta, cache_dir)
        except HttpError as exc:
            download_error = exc
            ymd = extract_meta.get("ymd") or as_of.strftime("%Y%m%d")
            for offset in range(1, 6):
                try:
                    day = datetime.strptime(ymd, "%Y%m%d").date() - timedelta(days=offset)
                except ValueError:
                    break
                alt = dict(extract_meta)
                alt["ymd"] = day.strftime("%Y%m%d")
                alt["file_name"] = f"GrantsDBExtract{alt['ymd']}v2.zip"
                alt["file_url"] = f"https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/{alt['file_name']}"
                try:
                    path = download_extract(alt, cache_dir)
                    extract_meta = alt
                    extract_meta["fallback_from_error"] = str(exc)
                    download_error = None
                    break
                except HttpError as alt_exc:
                    download_error = alt_exc
        if path is not None:
            raw_records, parse_stats = parse_extract(path)
        else:
            raw_records, parse_stats = collect_via_api()
            extract_meta["id"] = "grantsgov_api"
            extract_meta["name"] = "Grants.gov search2 and fetchOpportunity"
            extract_meta["fallback_from_error"] = str(download_error)
            errors.append({"source": "grantsgov_extract", "error": str(download_error), "fallback": "search2"})
    extract_meta["retrieved_at"] = retrieved_at
    extract_meta["parse_stats"] = parse_stats
    sources.append({k: v for k, v in extract_meta.items() if k != "notes"})

    opportunities, scope_stats = build_from_extract(
        raw_records,
        as_of,
        retrieved_at,
        {
            "id": extract_meta.get("id") or "grantsgov_extract",
            "name": extract_meta.get("name") or "Grants.gov daily XML extract",
            "catalog_url": extract_meta.get("catalog_url") or "https://www.grants.gov/xml-extract",
            "file_url": extract_meta.get("file_url"),
            "file_name": extract_meta.get("file_name"),
        },
    )

    nsf_programs = []
    if not fixture:
        try:
            items = fetch_funding_rss()
            for item in items:
                record = normalize_program_record(item, as_of, retrieved_at)
                if record:
                    nsf_programs.append(record)
            sources.append(
                {
                    "id": "nsf_funding_rss",
                    "name": "NSF funding opportunities RSS",
                    "url": "https://www.nsf.gov/rss/rss_www_funding.xml",
                    "retrieved_at": retrieved_at,
                    "status": "ok",
                    "items": len(nsf_programs),
                }
            )
        except Exception as exc:
            errors.append({"source": "nsf_funding_rss", "error": str(exc)})
            sources.append(
                {
                    "id": "nsf_funding_rss",
                    "name": "NSF funding opportunities RSS",
                    "url": "https://www.nsf.gov/rss/rss_www_funding.xml",
                    "status": "failed",
                    "error": str(exc),
                }
            )
    opportunities.extend(nsf_programs)

    check = {"status": "skipped", "reason": "Fixture run does not call Grants.gov."} if fixture else {}
    if not fixture:
        check = cross_check(opportunities)

    awards: list[dict] = []
    award_meta = []
    obligations: list[dict] = []
    if not skip_awards and not fixture:
        try:
            nsf = fetch_awards(retrieved_at, start_date="10/01/2024", max_pages=40)
            awards.extend(nsf["awards"])
            award_meta.append(
                {
                    "id": "nsf_awards_api",
                    "name": "NSF Award Search API",
                    "url": "https://api.nsf.gov/services/v1/awards.json",
                    "status": "ok" if not nsf["error"] else "partial",
                    "count": len(nsf["awards"]),
                    "pages": nsf["pages"],
                    "exhausted": nsf["exhausted"],
                    "coverage": nsf["coverage"],
                    "error": nsf["error"],
                    "query": nsf["query"],
                }
            )
        except Exception as exc:
            errors.append({"source": "nsf_awards_api", "error": str(exc)})
            award_meta.append({"id": "nsf_awards_api", "status": "failed", "error": str(exc)})
        try:
            nih = collect_samples(retrieved_at)
            awards.extend(nih["awards"])
            award_meta.append(
                {
                    "id": "nih_reporter",
                    "name": "NIH RePORTER API v2",
                    "url": "https://api.reporter.nih.gov/v2/projects/search",
                    "status": "ok" if nih["awards"] else "failed",
                    "count": len(nih["awards"]),
                    "queries": nih["queries"],
                    "errors": nih["errors"],
                    "coverage": nih["coverage"],
                }
            )
        except Exception as exc:
            errors.append({"source": "nih_reporter", "error": str(exc)})
            award_meta.append({"id": "nih_reporter", "status": "failed", "error": str(exc)})
        try:
            alns = []
            for record in opportunities:
                if record["status"] in {"open", "upcoming"}:
                    for aln in record.get("aln") or []:
                        alns.append(aln["number"])
            end = as_of.isoformat()
            start = (as_of - timedelta(days=365 * 3)).isoformat()
            usa = collect_for_catalog_alns(alns, start, end)
            obligations = usa["awards"]
            award_meta.append(
                {
                    "id": "usaspending",
                    "name": "USAspending spending_by_award",
                    "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                    "status": "ok" if not usa["errors"] else "partial",
                    "count": len(obligations),
                    "coverage": usa["coverage"],
                    "time_period": usa["time_period"],
                    "alns_queried": usa["alns_queried"],
                    "alns_considered": usa["alns_considered"],
                    "errors": usa["errors"][:5],
                }
            )
        except Exception as exc:
            errors.append({"source": "usaspending", "error": str(exc)})
            award_meta.append({"id": "usaspending", "status": "failed", "error": str(exc)})

    _attach_award_topics(awards)
    for award in awards:
        award.setdefault("urls", {})
    # Obligations use amount, not amount_obligated. Validator accepts amount.
    for row in obligations:
        row["verified_at"] = retrieved_at
        row["title"] = row.get("description") or row.get("award_id") or "USAspending obligation"
        if not row.get("description"):
            row["description"] = None

    assert_valid(opportunities, awards + obligations, as_of)

    meta = {
        "as_of_date": as_of.isoformat(),
        "sources": sources + award_meta,
        "scope_stats": scope_stats,
        "cross_check": check,
        "errors": errors,
        "limitations": LIMITATIONS,
        "research_scope": {
            "description": "A Grants.gov record is published when an inclusion basis is present and the status is current or recently closed. See inclusion.basis on each record.",
            "rules": [
                "funding_category_ST",
                "research_agency_prefix",
                "research_agency_name",
                "sbir_sttr",
                "research_terms_and_grant_instrument",
                "nsf_funding_feed",
            ],
        },
        "no_hallucination": "The pipeline does not create opportunities, amounts, deadlines, recipients, or award probabilities. Missing values stay null.",
    }
    if fixture:
        meta["fixture"] = True
    published = publish(out_dir, meta, opportunities, awards, obligations)
    (out_dir / "README.md").write_text(
        "# Generated catalog\n\nThese files are produced by `python -m pipeline.refresh`. Do not edit them by hand.\n",
        encoding="utf-8",
    )
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the federal research funding catalog from official sources.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--skip-awards", action="store_true")
    parser.add_argument("--fixture", type=Path, default=None, help="Parse a local extract XML/ZIP instead of downloading. For tests.")
    args = parser.parse_args(argv)
    try:
        meta = refresh(args.out, args.cache, skip_awards=args.skip_awards, fixture=args.fixture)
    except (CatalogError, HttpError, RuntimeError) as exc:
        print(f"REFRESH FAILED: {exc}")
        if isinstance(exc, CatalogError):
            for line in exc.errors:
                print(f"  - {line}")
        return 1
    except Exception:
        traceback.print_exc()
        return 1
    counts = meta.get("counts", {})
    print(json.dumps({"ok": True, "as_of": meta.get("as_of_date"), "counts": counts, "cross_check": (meta.get("cross_check") or {}).get("status")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
