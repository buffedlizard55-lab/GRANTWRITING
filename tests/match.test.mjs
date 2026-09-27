import test from "node:test";
import assert from "node:assert/strict";
import { rankMatches, scoreOpportunity } from "../docs/js/match.js";

const asOf = "2026-09-27";

const open = {
  id: "gg-1",
  title: "Quantum computing for climate models",
  status: "open",
  status_basis: "Posted synopsis with a close date on or after the as-of date.",
  description: "The purpose of this program is quantum computing research applied to climate models.",
  applicant_types: [{ code: "06", label: "Public universities" }],
  funding: { ceiling: 500000, floor: 100000, estimated_total: null, cost_sharing: false },
  dates: { close: "2026-12-01" },
  topics: [{ id: "quantum", label: "Quantum information science", matched_terms: ["quantum computing"], method: "keyword" }],
  aln: [{ number: "47.070" }],
  contact: { email: "a@nsf.gov" },
  eligibility_text: "Universities.",
};

test("fit is explainable and is not a win probability", () => {
  const result = scoreOpportunity(
    {
      title: "Quantum climate models",
      summary: "We will build quantum computing methods for climate models.",
      applicantTypes: ["06"],
      budget: 250000,
    },
    open,
    asOf
  );
  assert.equal(result.not_a_win_probability, true);
  assert.equal(result.fit_label, "Opportunity fit");
  assert.equal("probability" in result, false);
  assert.ok(result.fit >= 70);
  assert.equal(result.blockers.length, 0);
  const alignment = result.components.find((item) => item.id === "alignment");
  assert.ok(alignment.evidence.some((line) => line.includes("quantum")));
  assert.ok(alignment.quotes.length > 0);
});

test("ineligible applicant is a blocker, not a hidden zero", () => {
  const result = scoreOpportunity(
    { summary: "quantum computing climate", applicantTypes: ["23"], budget: 250000 },
    open,
    asOf
  );
  assert.ok(result.blockers.length > 0);
  assert.equal(result.components.find((item) => item.id === "eligibility").score, 0);
});

test("missing budget is not scored as incompatible", () => {
  const result = scoreOpportunity({ summary: "quantum computing", applicantTypes: ["06"] }, open, asOf);
  const funding = result.components.find((item) => item.id === "funding");
  assert.equal(funding.assessed, false);
  assert.equal(funding.score, null);
});

test("closed opportunity sorts below an open one", () => {
  const closed = { ...open, id: "gg-2", status: "closed", dates: { close: "2026-01-01" } };
  const ranked = rankMatches({ summary: "quantum computing climate models", applicantTypes: ["06"] }, [closed, open], asOf);
  assert.equal(ranked[0].opportunity.id, "gg-1");
  assert.ok(ranked[1].match.blockers.length > 0);
});

test("unpublished amounts are not treated as zero", () => {
  const bare = {
    ...open,
    funding: { ceiling: null, floor: null },
    applicant_types: [],
  };
  const result = scoreOpportunity({ summary: "quantum", applicantTypes: ["06"], budget: 10 }, bare, asOf);
  assert.equal(result.components.find((item) => item.id === "funding").assessed, false);
  assert.equal(result.components.find((item) => item.id === "eligibility").assessed, false);
});
