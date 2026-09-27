"""Unit tests for parsing, status, inclusion, and catalog validation.

These tests do not call the network and do not use invented live grants.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pipeline.model import derive_status, inclusion_basis, normalize_grant_record
from pipeline.refresh import refresh
from pipeline.sources_grantsgov import parse_extract, parse_opportunity_element
from pipeline.textutil import html_to_text, parse_date, parse_money
from pipeline.topics import classify_topics
from pipeline.validate_catalog import validate_opportunities
import xml.etree.ElementTree as ET

FIXTURE = Path(__file__).parent / "fixtures" / "sample_extract.xml"
AS_OF = date(2026, 9, 27)
SOURCE = {
    "id": "grantsgov_extract",
    "name": "Grants.gov daily XML extract",
    "catalog_url": "https://www.grants.gov/xml-extract",
    "file_name": "fixture.xml",
}


class TextTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_date("09012026"), date(2026, 9, 1))
        self.assertEqual(parse_date("10/11/2023"), date(2023, 10, 11))
        self.assertEqual(parse_date("2026-09-27"), date(2026, 9, 27))
        self.assertEqual(parse_date("Sep 26, 2026 04:41:24 AM EDT"), date(2026, 9, 26))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("TBD"))
        self.assertIsNone(parse_date(None))

    def test_money_does_not_invent_zero(self):
        self.assertIsNone(parse_money(""))
        self.assertIsNone(parse_money("TBD"))
        self.assertIsNone(parse_money("See announcement"))
        self.assertEqual(parse_money("0"), 0)
        self.assertEqual(parse_money("$1,250,000"), 1250000)
        self.assertEqual(parse_money(500), 500)

    def test_html_strips_script(self):
        text = html_to_text("<p>Hello</p><script>alert(1)</script><br>World")
        self.assertIn("Hello", text)
        self.assertIn("World", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("<", text)


class StatusTests(unittest.TestCase):
    def test_open_future_close(self):
        status, _basis, flags = derive_status(
            doc_type="synopsis",
            post=date(2026, 9, 1),
            close=date(2026, 12, 1),
            archive=None,
            as_of=AS_OF,
            description="Research.",
            record_kind="opportunity",
        )
        self.assertEqual(status, "open")
        self.assertIn("deadline_is_date_only", flags)

    def test_closed_is_not_open(self):
        status, _basis, _flags = derive_status(
            doc_type="synopsis",
            post=date(2026, 1, 1),
            close=date(2026, 8, 1),
            archive=None,
            as_of=AS_OF,
            description="Research.",
            record_kind="opportunity",
        )
        self.assertEqual(status, "closed")

    def test_closes_today_stays_open(self):
        status, basis, flags = derive_status(
            doc_type="synopsis",
            post=date(2026, 1, 1),
            close=AS_OF,
            archive=None,
            as_of=AS_OF,
            description="Research.",
            record_kind="opportunity",
        )
        self.assertEqual(status, "open")
        self.assertIn("closes_today", flags)
        self.assertIn("time", basis.lower())

    def test_forecast_is_upcoming_not_open(self):
        status, _basis, _flags = derive_status(
            doc_type="forecast",
            post=date(2026, 11, 1),
            close=date(2027, 2, 1),
            archive=None,
            as_of=AS_OF,
            description="Forecast.",
            record_kind="forecast",
        )
        self.assertEqual(status, "upcoming")

    def test_cancellation_language_is_not_open(self):
        status, _basis, flags = derive_status(
            doc_type="synopsis",
            post=date(2026, 6, 1),
            close=date(2026, 12, 1),
            archive=None,
            as_of=AS_OF,
            description="This solicitation has been cancelled.",
            record_kind="opportunity",
        )
        self.assertEqual(status, "verification_required")
        self.assertIn("possible_cancellation_language", flags)

    def test_old_open_ended_synopsis_is_not_labeled_open(self):
        status, basis, flags = derive_status(
            doc_type="synopsis",
            post=date(2011, 7, 6),
            close=None,
            archive=None,
            as_of=AS_OF,
            description="FY 2012 climate program.",
            record_kind="opportunity",
            last_updated=date(2011, 7, 7),
        )
        self.assertEqual(status, "verification_required")
        self.assertIn("stale_open_ended", flags)
        self.assertIn("not labeled open", basis)

    def test_recent_open_ended_synopsis_stays_open(self):
        status, _basis, flags = derive_status(
            doc_type="synopsis",
            post=date(2026, 4, 24),
            close=None,
            archive=None,
            as_of=AS_OF,
            description="Standing solicitation.",
            record_kind="opportunity",
            last_updated=date(2026, 4, 27),
        )
        self.assertEqual(status, "open")
        self.assertIn("deadline_not_published", flags)

    def test_program_has_no_invented_deadline(self):
        status, basis, flags = derive_status(
            doc_type="program",
            post=date(2026, 9, 21),
            close=None,
            archive=None,
            as_of=AS_OF,
            description="Standing program.",
            record_kind="program",
        )
        self.assertEqual(status, "open_program")
        self.assertIn("deadline_not_published", flags)
        self.assertIn("not", basis.lower())


class ScopeTests(unittest.TestCase):
    def test_st_category_included(self):
        bases = inclusion_basis("HUD", "Housing", ["ST"], ["G"], "community")
        self.assertTrue(any(b["id"] == "funding_category_ST" for b in bases))

    def test_housing_grant_excluded(self):
        bases = inclusion_basis("HUD", "Department of Housing and Urban Development", ["HO"], ["G"], "repair housing")
        self.assertEqual(bases, [])

    def test_nih_prefix_included(self):
        bases = inclusion_basis("HHS-NIH11", "National Institutes of Health", ["HL"], ["CA"], "methods")
        self.assertTrue(bases)

    def test_nofo_alone_is_not_research(self):
        bases = inclusion_basis(
            "USDOJ-OJP-OVC",
            "Office for Victims of Crime",
            ["ISS"],
            ["G"],
            "This NOFO funds services for victims of crime. See the funding opportunity announcement.",
        )
        self.assertEqual(bases, [])

    def test_sbir_included(self):
        bases = inclusion_basis("EPA", "Environmental Protection Agency", ["ENV"], ["G"], "SBIR sensors")
        self.assertTrue(any(b["id"] == "sbir_sttr" for b in bases))

    def test_topics_require_terms(self):
        topics = classify_topics(["Quantum computing for climate models"])
        ids = {t["id"] for t in topics}
        self.assertIn("quantum", ids)
        self.assertIn("climate", ids)
        for topic in topics:
            self.assertTrue(topic["matched_terms"])
        self.assertEqual(classify_topics(["Housing repair grants"]), [])


class ApiMapTests(unittest.TestCase):
    def test_fetch_payload_maps_without_inventing_amounts(self):
        from pipeline.sources_grantsgov import api_record_to_raw

        raw = api_record_to_raw(
            {
                "data": {
                    "id": 42,
                    "opportunityNumber": "NSF-1",
                    "opportunityTitle": "Quantum methods",
                    "owningAgencyCode": "NSF",
                    "docType": "synopsis",
                    "synopsis": {
                        "agencyName": "National Science Foundation",
                        "agencyCode": "NSF",
                        "postingDate": "09/01/2026",
                        "awardCeiling": "1000",
                        "synopsisDesc": "Supports quantum computing research.",
                        "applicantTypes": [{"id": "06", "description": "Public universities"}],
                        "fundingActivityCategories": [{"id": "ST"}],
                        "fundingInstruments": [{"id": "G"}],
                    },
                    "alns": [{"alnNumber": "47.070", "programTitle": "Computer and Information Science"}],
                }
            }
        )
        self.assertEqual(raw["opportunity_id"], "42")
        self.assertEqual(raw["award_ceiling"], "1000")
        self.assertIsNone(raw["award_floor"])
        self.assertEqual(raw["funding_categories"], ["ST"])
        self.assertEqual(raw["alns"][0]["number"], "47.070")


class ExtractTests(unittest.TestCase):
    def test_fixture_parse_and_catalog_rules(self):
        raw_records, stats = parse_extract(FIXTURE)
        self.assertGreaterEqual(stats["records_parsed"], 8)
        normalized = []
        for raw in raw_records:
            record = normalize_grant_record(raw, AS_OF, "2026-09-27T12:00:00-04:00", SOURCE)
            self.assertIsNotNone(record)
            normalized.append(record)
        by_id = {}
        for record in normalized:
            # The fixture repeats 100001 as a forecast. Keep the synopsis for field checks.
            if record["source_record_id"] not in by_id or record["record_kind"] == "opportunity":
                by_id[record["source_record_id"]] = record
        quantum = by_id["100001"]
        self.assertEqual(quantum["status"], "open")
        self.assertEqual(quantum["dates"]["close"], "2026-12-01")
        self.assertEqual(quantum["funding"]["ceiling"], 500000)
        self.assertEqual(quantum["funding"]["floor"], 100000)
        self.assertFalse(quantum["funding"]["cost_sharing"])
        self.assertEqual(quantum["urls"]["official"], "https://www.grants.gov/search-results-detail/100001")
        self.assertTrue(any(t["id"] == "quantum" for t in quantum["topics"]))
        self.assertTrue(quantum["objective_quotes"])
        self.assertEqual(quantum["objective_quotes"][0]["kind"], "extracted_quote")
        self.assertIn("47.070", [a["number"] for a in quantum["aln"]])
        self.assertIn("06", [a["code"] for a in quantum["applicant_types"]])

        housing = by_id["100003"]
        self.assertFalse(housing["inclusion"]["research_relevant"])
        self.assertEqual(by_id["100004"]["status"], "upcoming")
        self.assertEqual(by_id["100005"]["status"], "closed")
        self.assertEqual(by_id["100006"]["status"], "closed")
        self.assertNotEqual(by_id["100006"]["status"], "open")
        self.assertTrue(by_id["100007"]["is_sbir_sttr"])
        self.assertEqual(by_id["100008"]["status"], "verification_required")
        self.assertIsNone(by_id["100004"]["funding"]["ceiling"])

        research = [r for r in normalized if r["inclusion"]["research_relevant"]]
        self.assertIn("Duplicate opportunity ids.", validate_opportunities(research, AS_OF))
        deduped = []
        seen = set()
        for record in research:
            if record["id"] in seen:
                continue
            seen.add(record["id"])
            deduped.append(record)
        self.assertEqual(validate_opportunities(deduped, AS_OF), [])

    def test_refresh_fixture_omits_housing_and_ancient(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data"
            meta = refresh(out, Path(tmp) / "cache", skip_awards=True, fixture=FIXTURE)
            catalog = json.loads((out / "opportunities.json").read_text())["opportunities"]
            ids = {r["source_record_id"] for r in catalog}
            self.assertIn("100001", ids)
            self.assertIn("100002", ids)
            self.assertIn("100004", ids)
            self.assertIn("100005", ids)
            self.assertIn("100007", ids)
            self.assertIn("100008", ids)
            self.assertNotIn("100003", ids)
            self.assertNotIn("100006", ids)
            self.assertFalse(any(r["status"] == "open" and (r["dates"]["close"] or "") < "2026-09-27" for r in catalog))
            self.assertGreater(meta["counts"]["opportunities"], 0)
            # No win-probability field anywhere.
            blob = (out / "opportunities.json").read_text()
            self.assertNotIn("win_probability", blob)


if __name__ == "__main__":
    unittest.main()
