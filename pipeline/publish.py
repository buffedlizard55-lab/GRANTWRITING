"""Build aggregates, changes, and the static catalog files."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from pipeline import __version__
from pipeline.codes import APPLICANT_TYPE, FUNDING_CATEGORY, FUNDING_INSTRUMENT, STATUS_VALUES
from pipeline.textutil import EASTERN

STATUS_FEED = {"open", "upcoming", "open_program"}


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return int(round((ordered[mid - 1] + ordered[mid]) / 2))


def field_coverage(records: list[dict]) -> dict:
    total = len(records) or 1
    def has(pred) -> dict:
        count = sum(1 for record in records if pred(record))
        return {"count": count, "percent": round(100 * count / total, 1), "of": len(records)}

    return {
        "title": has(lambda r: bool(r.get("title"))),
        "agency": has(lambda r: bool(r.get("agency_name"))),
        "number": has(lambda r: bool(r.get("number"))),
        "close_date": has(lambda r: bool((r.get("dates") or {}).get("close"))),
        "post_date": has(lambda r: bool((r.get("dates") or {}).get("post"))),
        "description": has(lambda r: len(r.get("description") or "") > 80),
        "eligibility_codes": has(lambda r: bool(r.get("applicant_types"))),
        "eligibility_text": has(lambda r: bool(r.get("eligibility_text"))),
        "award_ceiling": has(lambda r: (r.get("funding") or {}).get("ceiling") is not None),
        "award_floor": has(lambda r: (r.get("funding") or {}).get("floor") is not None),
        "estimated_total": has(lambda r: (r.get("funding") or {}).get("estimated_total") is not None),
        "expected_awards": has(lambda r: (r.get("funding") or {}).get("expected_awards") is not None),
        "cost_sharing": has(lambda r: (r.get("funding") or {}).get("cost_sharing") is not None),
        "aln": has(lambda r: bool(r.get("aln"))),
        "contact_email": has(lambda r: bool((r.get("contact") or {}).get("email"))),
        "official_url": has(lambda r: bool((r.get("urls") or {}).get("official"))),
        "topics": has(lambda r: bool(r.get("topics"))),
    }


def aggregates(records: list[dict], awards: list[dict]) -> dict:
    by_status = Counter(r["status"] for r in records)
    by_kind = Counter(r["record_kind"] for r in records)
    agency_rows = {}
    topic_rows = {}
    for record in records:
        code = record.get("top_agency_code") or record.get("agency_code") or "UNKNOWN"
        row = agency_rows.setdefault(
            code,
            {
                "code": code,
                "grouping_label": record.get("top_agency_grouping_label"),
                "names": Counter(),
                "open": 0,
                "upcoming": 0,
                "open_program": 0,
                "closed": 0,
                "other": 0,
                "ceilings": [],
                "estimated_totals": [],
                "topics": Counter(),
            },
        )
        if record.get("agency_name"):
            row["names"][record["agency_name"]] += 1
        status = record["status"]
        if status in row:
            row[status] += 1
        elif status == "closed":
            row["closed"] += 1
        else:
            row["other"] += 1
        ceiling = (record.get("funding") or {}).get("ceiling")
        estimated = (record.get("funding") or {}).get("estimated_total")
        if status in STATUS_FEED and isinstance(ceiling, int):
            row["ceilings"].append(ceiling)
        if status in STATUS_FEED and isinstance(estimated, int):
            row["estimated_totals"].append(estimated)
        for topic in record.get("topics") or []:
            row["topics"][topic["id"]] += 1
            topic_row = topic_rows.setdefault(
                topic["id"],
                {
                    "id": topic["id"],
                    "label": topic["label"],
                    "method_counts": Counter(),
                    "open": 0,
                    "upcoming": 0,
                    "open_program": 0,
                    "agencies": set(),
                    "sample_ids": [],
                },
            )
            topic_row["method_counts"][topic.get("method") or "keyword"] += 1
            if status in topic_row:
                topic_row[status] += 1
            if record.get("top_agency_code"):
                topic_row["agencies"].add(record["top_agency_code"])
            if len(topic_row["sample_ids"]) < 8 and status in STATUS_FEED:
                topic_row["sample_ids"].append(record["id"])

    agencies = []
    for row in agency_rows.values():
        agencies.append(
            {
                "code": row["code"],
                "grouping_label": row["grouping_label"],
                "source_name_most_common": row["names"].most_common(1)[0][0] if row["names"] else None,
                "open": row["open"],
                "upcoming": row["upcoming"],
                "open_program": row["open_program"],
                "closed": row["closed"],
                "other": row["other"],
                "published_ceiling_count": len(row["ceilings"]),
                "median_published_ceiling": _median(row["ceilings"]),
                "published_estimated_total_count": len(row["estimated_totals"]),
                "sum_published_estimated_totals": sum(row["estimated_totals"]) if row["estimated_totals"] else None,
                "sum_note": "Sum only of opportunities in the current feed that published an estimated total. Not available funding. Opportunities without a published total are excluded.",
                "top_topics": [{"id": tid, "count": count} for tid, count in row["topics"].most_common(6)],
            }
        )
    agencies.sort(key=lambda item: (-(item["open"] + item["upcoming"] + item["open_program"]), item["code"]))

    topics = []
    for row in topic_rows.values():
        topics.append(
            {
                "id": row["id"],
                "label": row["label"],
                "open": row["open"],
                "upcoming": row["upcoming"],
                "open_program": row["open_program"],
                "agency_count": len(row["agencies"]),
                "agencies": sorted(row["agencies"]),
                "sample_ids": row["sample_ids"],
                "methods": dict(row["method_counts"]),
                "classification": "derived_keyword_or_agency_default",
            }
        )
    topics.sort(key=lambda item: (-(item["open"] + item["upcoming"]), -item["agency_count"], item["label"]))
    multi = [t for t in topics if t["agency_count"] >= 2 and (t["open"] + t["upcoming"]) >= 2]

    estimated_values = [
        r["funding"]["estimated_total"]
        for r in records
        if r["status"] in STATUS_FEED and isinstance((r.get("funding") or {}).get("estimated_total"), int)
    ]
    award_amounts = [a["amount_obligated"] for a in awards if isinstance(a.get("amount_obligated"), int)]
    return {
        "note": "All counts are computed from this catalog only. They are derived statistics, not independent official totals.",
        "by_status": dict(by_status),
        "by_record_kind": dict(by_kind),
        "agencies": agencies,
        "topics": topics,
        "multi_agency_topics": multi[:40],
        "unclassified_current": sum(
            1 for r in records if r["status"] in STATUS_FEED and not r.get("topics")
        ),
        "funding_published": {
            "current_feed_with_estimated_total": len(estimated_values),
            "sum_of_published_estimated_totals": sum(estimated_values) if estimated_values else None,
            "median_published_estimated_total": _median(estimated_values),
            "warning": "Do not read this sum as the amount of research funding available. It adds only the estimated program totals agencies chose to publish, it double-counts nothing on purpose but it also excludes every opportunity that left the field blank, and an estimated total is not an amount set aside for one applicant.",
        },
        "awards_in_catalog": {
            "count": len(awards),
            "with_amount": len(award_amounts),
            "sum_of_amounts_in_this_file": sum(award_amounts) if award_amounts else None,
            "warning": "Award files may be samples. Use the award coverage note before treating a sum as agency funding.",
        },
    }


def diff_catalogs(previous: list[dict] | None, current: list[dict]) -> dict:
    if not previous:
        return {
            "compared_to_previous_catalog": False,
            "note": "First catalog retained by this pipeline. New ids are new to the catalog, not necessarily newly posted by the agency. Use dates.post for the agency post date.",
            "new_ids": [r["id"] for r in current],
            "removed_ids": [],
            "changed": [],
            "newly_closed": [],
        }
    prev = {r["id"]: r for r in previous}
    curr = {r["id"]: r for r in current}
    changed = []
    watch = (
        ("status", lambda r: r.get("status")),
        ("dates.close", lambda r: (r.get("dates") or {}).get("close")),
        ("dates.post", lambda r: (r.get("dates") or {}).get("post")),
        ("funding.ceiling", lambda r: (r.get("funding") or {}).get("ceiling")),
        ("funding.estimated_total", lambda r: (r.get("funding") or {}).get("estimated_total")),
        ("title", lambda r: r.get("title")),
        ("eligibility_codes", lambda r: tuple(a.get("code") for a in r.get("applicant_types") or [])),
    )
    for rid, record in curr.items():
        old = prev.get(rid)
        if not old:
            continue
        fields = [name for name, fn in watch if fn(old) != fn(record)]
        if fields:
            changed.append({"id": rid, "fields": fields, "status": record.get("status"), "previous_status": old.get("status")})
    newly_closed = [
        rid
        for rid, record in curr.items()
        if rid in prev and prev[rid].get("status") in STATUS_FEED and record.get("status") == "closed"
    ]
    return {
        "compared_to_previous_catalog": True,
        "note": "Removed means the id is not in the new catalog. That is not the same as a documented cancellation.",
        "new_ids": sorted(set(curr) - set(prev)),
        "removed_ids": sorted(set(prev) - set(curr)),
        "changed": changed[:500],
        "changed_count": len(changed),
        "newly_closed": newly_closed,
    }


def _append_history(out_dir: Path, meta: dict, summary: dict) -> None:
    path = out_dir / "history.json"
    runs = []
    if path.exists():
        try:
            runs = json.loads(path.read_text(encoding="utf-8")).get("runs") or []
        except json.JSONDecodeError:
            runs = []
    snapshot = {
        "generated_at": meta.get("generated_at"),
        "as_of_date": meta.get("as_of_date"),
        "by_status": summary.get("by_status"),
        "agency_open": {row["code"]: row["open"] for row in summary.get("agencies") or []},
    }
    if runs and runs[-1].get("generated_at") == snapshot["generated_at"]:
        runs[-1] = snapshot
    else:
        runs.append(snapshot)
    write_json(
        path,
        {
            "note": "Derived counts from each catalog build. A change between runs is a change in this catalog, not by itself an official statement that an agency increased funding.",
            "runs": runs[-60:],
        },
    )


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_previous_opportunities(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and "opportunities" in data:
        return data["opportunities"]
    if isinstance(data, list):
        return data
    return None


def publish(out_dir: Path, meta: dict, opportunities: list[dict], awards: list[dict], obligations: list[dict]) -> dict:
    previous = load_previous_opportunities(out_dir / "opportunities.json")
    changes = diff_catalogs(previous, opportunities)
    coverage = field_coverage(opportunities)
    summary = aggregates(opportunities, awards)
    generated_at = datetime.now(EASTERN).isoformat(timespec="seconds")
    meta = {
        **meta,
        "schema_version": 1,
        "pipeline_version": __version__,
        "generated_at": generated_at,
        "timezone": "America/New_York",
        "counts": {
            "opportunities": len(opportunities),
            "by_status": summary["by_status"],
            "awards": len(awards),
            "obligations": len(obligations),
        },
        "field_coverage": coverage,
        "changes_summary": {
            "compared_to_previous_catalog": changes["compared_to_previous_catalog"],
            "new": len(changes["new_ids"]),
            "removed": len(changes["removed_ids"]),
            "changed": changes.get("changed_count", len(changes["changed"])),
            "newly_closed": len(changes["newly_closed"]),
        },
    }
    # Lean list file keeps the browser payload smaller. Detail text stays, but
    # search_blob is not duplicated beyond the description already stored.
    write_json(out_dir / "opportunities.json", {"opportunities": opportunities})
    write_json(out_dir / "awards.json", {"awards": awards})
    write_json(out_dir / "obligations.json", {"obligations": obligations})
    write_json(out_dir / "aggregates.json", summary)
    write_json(out_dir / "changes.json", changes)
    write_json(out_dir / "meta.json", meta)
    _append_history(out_dir, meta, summary)
    write_json(
        out_dir / "codes.json",
        {
            "note": "Labels are the Grants.gov XML extract field guide values. They are codes, not opportunity facts.",
            "source": "https://www.grants.gov/help/xml-extract/",
            "applicant_types": [{"code": code, "label": label} for code, label in APPLICANT_TYPE.items()],
            "funding_categories": [{"code": code, "label": label} for code, label in FUNDING_CATEGORY.items()],
            "instruments": [{"code": code, "label": label} for code, label in FUNDING_INSTRUMENT.items()],
            "statuses": list(STATUS_VALUES),
        },
    )
    return meta
