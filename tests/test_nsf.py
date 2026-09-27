"""Tests for NSF Award Search API pagination semantics."""

from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from pipeline.sources_nsf import fetch_awards


def _award_row(number: int) -> dict:
    return {
        "id": str(number),
        "title": f"Award {number}",
        "fundsObligatedAmt": "25000",
        "date": "09/01/2026",
    }


class NsfPaginationTests(unittest.TestCase):
    def test_uses_zero_based_offsets_and_stable_award_number_sort(self):
        pages = [
            {"response": {"award": [_award_row(i) for i in range(1, 26)]}},
            {"response": {"award": [_award_row(26)]}},
            {"response": {"award": []}},
        ]
        requests = []

        def fake_fetch(url: str, **_kwargs):
            requests.append(url)
            payload = pages[len(requests) - 1]
            return json.dumps(payload).encode("utf-8"), {}

        with patch("pipeline.http_util.fetch_bytes", side_effect=fake_fetch), patch("pipeline.sources_nsf.time.sleep"):
            result = fetch_awards("2026-09-27T12:00:00-04:00", max_pages=5, rpp=25)

        self.assertEqual(len(result["awards"]), 26)
        self.assertTrue(result["exhausted"])
        self.assertEqual(result["pages"], 3)
        params = [parse_qs(urlparse(url).query) for url in requests]
        self.assertEqual([item["offset"][0] for item in params], ["0", "25", "50"])
        self.assertTrue(all(item["sortKey"] == ["awardNumber"] for item in params))
        self.assertEqual(result["query"]["offset_start"], 0)
        self.assertEqual(result["query"]["sortKey"], "awardNumber")


if __name__ == "__main__":
    unittest.main()
