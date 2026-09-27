"""Check the catalog that the site will serve. Used by CI after refresh."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pipeline.textutil import parse_date
from pipeline.validate_catalog import assert_valid

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"


def main() -> int:
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    opportunities = json.loads((DATA / "opportunities.json").read_text(encoding="utf-8"))["opportunities"]
    awards = json.loads((DATA / "awards.json").read_text(encoding="utf-8")).get("awards", [])
    obligations = json.loads((DATA / "obligations.json").read_text(encoding="utf-8")).get("obligations", [])
    as_of = parse_date(meta.get("as_of_date"))
    if as_of is None:
        print("meta.as_of_date is missing")
        return 1
    if meta.get("fixture"):
        print("Refusing to treat a fixture catalog as the published site.")
        return 1
    assert_valid(opportunities, awards + obligations, as_of)
    open_past = [
        record["id"]
        for record in opportunities
        if record.get("status") == "open" and (record.get("dates") or {}).get("close") and record["dates"]["close"] < as_of.isoformat()
    ]
    if open_past:
        print("Open records with past close dates:", open_past[:10])
        return 1
    print(f"Published catalog ok: {len(opportunities)} opportunities, as of {as_of.isoformat()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PUBLISHED CATALOG INVALID: {exc}")
        raise SystemExit(1)
