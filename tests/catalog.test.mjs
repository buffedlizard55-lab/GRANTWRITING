import test from "node:test";
import assert from "node:assert/strict";
import {
  awardAmount,
  compareAwards,
  compareRecords,
  daysToClose,
  filterAwards,
  filterOpportunities,
  paginate,
  sortAwards,
  safeHttpUrl,
  sortRecords,
  splitSort,
  viewerDate,
} from "../docs/js/catalog.js";

const REFERENCE = "2026-09-27";

function opportunity(overrides = {}) {
  return {
    id: "gg-1",
    title: "Quantum computing for climate models",
    number: "PAR-26-001",
    agency_name: "National Science Foundation",
    agency_code: "NSF",
    top_agency_code: "NSF",
    status: "open",
    record_kind: "opportunity",
    description: "The purpose of this program is quantum computing research.",
    eligibility_text: "Universities may apply.",
    applicant_types: [{ code: "06", label: "Public universities" }],
    instruments: [{ code: "G", label: "Grant" }],
    funding: { ceiling: 500000, floor: 100000, estimated_total: null },
    dates: { close: "2026-12-01", post: "2026-09-01", last_updated: "2026-09-20" },
    topics: [{ id: "quantum", label: "Quantum information science", matched_terms: ["quantum computing"], method: "keyword" }],
    aln: [{ number: "47.070", title: null }],
    ...overrides,
  };
}

function params(object = {}) {
  return new URLSearchParams(object);
}

test("sort direction is honored, including the -desc suffix", () => {
  assert.deepEqual(splitSort("close"), { field: "close", direction: 1 });
  assert.deepEqual(splitSort("title-desc"), { field: "title", direction: -1 });
  assert.deepEqual(splitSort("ceiling-desc"), { field: "ceiling", direction: -1 });

  const a = opportunity({ id: "a", title: "Alpha" });
  const b = opportunity({ id: "b", title: "Zulu" });
  assert.ok(compareRecords(a, b, "title") < 0, "ascending puts Alpha first");
  assert.ok(compareRecords(a, b, "title-desc") > 0, "descending puts Zulu first");
});

test("descending sort does not silently fall back to the deadline order", () => {
  const early = opportunity({ id: "early", title: "Middle title", dates: { close: "2026-10-01", post: "2026-09-01", last_updated: "2026-09-20" } });
  const late = opportunity({ id: "late", title: "Another title", dates: { close: "2027-06-01", post: "2026-09-01", last_updated: "2026-09-20" } });
  const sorted = sortRecords([early, late], "close-desc");
  assert.equal(sorted[0].id, "late", "latest deadline comes first when descending");
  assert.equal(sortRecords([early, late], "close")[0].id, "early", "soonest deadline comes first when ascending");
});

test("records missing the sorted field stay last in both directions", () => {
  const withCeiling = opportunity({ id: "with", funding: { ceiling: 10, floor: null, estimated_total: null } });
  const without = opportunity({ id: "without", funding: { ceiling: null, floor: null, estimated_total: null } });
  assert.equal(sortRecords([without, withCeiling], "ceiling-desc")[0].id, "with");
  assert.equal(sortRecords([without, withCeiling], "ceiling")[0].id, "with");
  const noClose = opportunity({ id: "noclose", dates: { close: null, post: "2026-09-01", last_updated: "2026-09-20" } });
  assert.equal(sortRecords([noClose, withCeiling], "close")[1].id, "noclose");
  assert.equal(sortRecords([noClose, withCeiling], "close-desc")[1].id, "noclose");
});

test("deadline math uses one reference date for the feed and the explorer", () => {
  const record = opportunity({ dates: { close: "2026-10-18", post: "2026-09-01", last_updated: "2026-09-20" } });
  assert.equal(daysToClose(record, REFERENCE), 21);
  const result = filterOpportunities([record], params({ status: "open", closing: "21" }), REFERENCE);
  assert.equal(result.rows.length, 1, "21 days out is inside a 21-day window");
  const outside = filterOpportunities([record], params({ status: "open", closing: "20" }), REFERENCE);
  assert.equal(outside.rows.length, 0);
  const stale = filterOpportunities([record], params({ closing: "21" }), "2026-10-19");
  assert.equal(stale.rows.length, 0, "a close date behind the reference date is not in the window");
});

test("a record with no published close date is counted, not silently dropped, by a deadline filter", () => {
  const openEnded = opportunity({ id: "open-ended", dates: { close: null, post: "2026-09-01", last_updated: "2026-09-20" } });
  const result = filterOpportunities([openEnded], params({ closing: "30" }), REFERENCE);
  assert.equal(result.rows.length, 0);
  assert.equal(result.deadline_excluded_missing_date, 1);
});

test("an amount filter reports the records it could not evaluate", () => {
  const withCeiling = opportunity({ id: "with", funding: { ceiling: 900000, floor: null, estimated_total: null } });
  const small = opportunity({ id: "small", funding: { ceiling: 5000, floor: null, estimated_total: null } });
  const unpublished = opportunity({ id: "unpublished", funding: { ceiling: null, floor: null, estimated_total: null } });
  const result = filterOpportunities([withCeiling, small, unpublished], params({ min: "100000" }), REFERENCE);
  assert.deepEqual(result.rows.map((row) => row.id), ["with"]);
  assert.equal(result.amount_excluded_missing_ceiling, 1);
  assert.equal(result.deadline_excluded_missing_date, 0);
  const noAmountFilter = filterOpportunities([withCeiling, small, unpublished], params({}), REFERENCE);
  assert.equal(noAmountFilter.rows.length, 3, "no amount filter keeps the unpublished rows");
  assert.equal(noAmountFilter.amount_excluded_missing_ceiling, 0);
});

test("explorer filters combine and search covers number, agency, topic, and assistance listing", () => {
  const other = opportunity({
    id: "other",
    title: "Marine ecosystem monitoring",
    number: "NOAA-2026-200",
    description: "This program supports marine ecosystem observation.",
    eligibility_text: "State agencies may apply.",
    agency_name: "National Oceanic and Atmospheric Administration",
    agency_code: "DOC-NOAA",
    top_agency_code: "DOC",
    applicant_types: [{ code: "01", label: "State governments" }],
    instruments: [{ code: "CA", label: "Cooperative Agreement" }],
    topics: [{ id: "ocean", label: "Ocean and marine science", matched_terms: ["marine ecosystem"], method: "keyword" }],
    aln: [{ number: "11.431", title: null }],
  });
  const pool = [opportunity(), other];
  assert.equal(filterOpportunities(pool, params({ q: "par-26-001" }), REFERENCE).rows.length, 1, "matches the opportunity number");
  assert.equal(filterOpportunities(pool, params({ q: "47.070" }), REFERENCE).rows.length, 1, "matches the assistance listing");
  assert.equal(filterOpportunities(pool, params({ q: "quantum" }), REFERENCE).rows.length, 1, "matches a topic label");
  assert.equal(filterOpportunities(pool, params({ agency: "DOC" }), REFERENCE).rows.length, 1, "matches the top-level agency code");
  assert.equal(filterOpportunities(pool, params({ topic: "ocean" }), REFERENCE).rows.length, 1);
  assert.equal(filterOpportunities(pool, params({ applicant: "06" }), REFERENCE).rows.length, 1);
  assert.equal(filterOpportunities(pool, params({ instrument: "G" }), REFERENCE).rows.length, 1, "matches the instrument code");
  assert.equal(filterOpportunities(pool, params({ kind: "opportunity" }), REFERENCE).rows.length, 2);
  assert.equal(filterOpportunities(pool, params({ status: "open", agency: "NSF", topic: "quantum" }), REFERENCE).rows.length, 1);
  assert.equal(filterOpportunities(pool, params({ q: "nonexistent-term" }), REFERENCE).rows.length, 0);
});

function award(overrides = {}) {
  return {
    id: "nsf-award-1",
    title: "Quantum sensors for gravity mapping",
    agency: "NSF",
    agency_name: "National Science Foundation",
    awardee_name: "University of Example",
    awardee_state: "CA",
    pi_name: "A. Researcher",
    amount_obligated: 425000,
    start_date: "2025-01-15",
    end_date: "2027-12-31",
    program: "Quantum Information Science",
    abstract: "Quantum sensing research.",
    record_type: "historical_award",
    source: { id: "nsf_awards_api" },
    topics: [{ id: "quantum", label: "Quantum information science", matched_terms: ["quantum"], method: "keyword" }],
    urls: { official: "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=1" },
    ...overrides,
  };
}

function obligation(overrides = {}) {
  return {
    award_id: "W81XWH1120174",
    title: "Medical research obligation",
    recipient_name: "Example Foundation",
    amount: 2265729366,
    awarding_agency: "Department of Defense",
    cfda: "12.420",
    start_date: "2011-09-23",
    record_type: "obligation",
    source: { id: "usaspending" },
    urls: { official: "https://www.usaspending.gov/award/x" },
    ...overrides,
  };
}

test("award rows can be searched, filtered, and sorted", () => {
  const pool = [
    award(),
    award({ id: "nsf-award-2", title: "Coastal flood modeling", abstract: "Coastal flood model development.", program: "Ocean Observing", start_date: "2026-03-01", amount_obligated: 90000, topics: [{ id: "ocean", label: "Ocean and marine science", matched_terms: ["coastal"], method: "keyword" }], awardee_state: "WA" }),
    award({ id: "nih-1", title: "Neonatal nutrition cohort study", abstract: "A longitudinal study of infant nutrition.", program: "Child Health and Human Development", start_date: "2024-11-05", agency: "NICHD", agency_name: "Eunice Kennedy Shriver National Institute", amount_obligated: null, source: { id: "nih_reporter" }, topics: [] }),
    obligation(),
  ];
  assert.deepEqual(filterAwards(pool, params({ q: "quantum" })).rows.map((row) => row.id), ["nsf-award-1"], "searches title, abstract, and program");
  assert.equal(filterAwards(pool, params({ q: "coastal" })).rows.length, 1, "searches the abstract");
  assert.equal(filterAwards(pool, params({ agency: "nsf" })).rows.length, 2, "agency match is case-insensitive");
  assert.equal(filterAwards(pool, params({ topic: "quantum" })).rows.length, 1);
  assert.equal(filterAwards(pool, params({ state: "wa" })).rows.length, 1);
  assert.equal(filterAwards(pool, params({ source: "usaspending" })).rows.length, 1);
  assert.equal(filterAwards(pool, params({ kind: "obligation" })).rows.length, 1);
  assert.equal(filterAwards(pool, params({ kind: "award" })).rows.length, 3);

  const minFilter = filterAwards(pool, params({ min: "100000" }));
  assert.equal(minFilter.rows.length, 2, "the award with no published amount cannot satisfy a minimum");
  assert.equal(minFilter.amount_excluded_missing_amount, 1);

  const largest = sortAwards(pool, "amount-desc");
  assert.equal(largest[0].award_id || largest[0].id, "W81XWH1120174", "largest amount first");
  assert.equal(largest[largest.length - 1].id, "nih-1", "a row with no amount sorts last");
  const newest = sortAwards(pool, "date-desc");
  assert.equal(newest[0].id, "nsf-award-2", "newest start date first");
  assert.equal(newest[newest.length - 1].award_id, "W81XWH1120174", "oldest start date last");
});

test("award amounts read from either award or obligation field names", () => {
  assert.equal(awardAmount(award()), 425000);
  assert.equal(awardAmount(obligation()), 2265729366);
  assert.equal(awardAmount(award({ amount_obligated: null })), null);
});

test("pagination clamps a page beyond the end instead of returning nothing", () => {
  const rows = Array.from({ length: 45 }, (_unused, index) => ({ index }));
  assert.equal(paginate(rows, 1, 20).rows.length, 20);
  assert.equal(paginate(rows, 3, 20).rows.length, 5);
  assert.equal(paginate(rows, 3, 20).pages, 3);
  const beyond = paginate(rows, 99, 20);
  assert.equal(beyond.page, 3, "a page past the end is clamped to the last page");
  assert.equal(beyond.rows.length, 5);
  assert.equal(beyond.clamped, true);
  assert.equal(paginate(rows, 2, 20).clamped, false);
  assert.equal(paginate(rows, 0, 20).page, 1, "page 0 is treated as page 1");
  assert.equal(paginate(rows, "abc", 20).page, 1, "a non-numeric page is treated as page 1");
  assert.equal(paginate([], 1, 20).pages, 1);
  assert.equal(compareAwards(award(), award({ title: "Zebra" }), "title") < 0, true);
});

test("viewerDate returns the viewer's own local calendar date", () => {
  assert.equal(viewerDate(new Date(2026, 8, 27, 23, 30)), "2026-09-27");
  assert.equal(viewerDate(new Date(2026, 0, 5, 0, 5)), "2026-01-05");
});

test("source URLs that are not http or https are refused", () => {
  assert.equal(safeHttpUrl("https://www.grants.gov/search-results-detail/350944"), "https://www.grants.gov/search-results-detail/350944");
  assert.equal(safeHttpUrl("http://www.nsf.gov/awardsearch/show-award/?AWD_ID=1"), "http://www.nsf.gov/awardsearch/show-award/?AWD_ID=1");
  assert.equal(safeHttpUrl("javascript:alert(1)"), null);
  assert.equal(safeHttpUrl("data:text/html,<script>alert(1)</script>"), null);
  assert.equal(safeHttpUrl(" JaVaScRiPt:alert(1)"), null);
  assert.equal(safeHttpUrl(""), null);
  assert.equal(safeHttpUrl(null), null);
  assert.equal(safeHttpUrl(undefined), null);
  assert.equal(safeHttpUrl("not a url at all"), "https://invalid.invalid/not%20a%20url%20at%20all", "a relative value resolves against a placeholder and stays https");
});
