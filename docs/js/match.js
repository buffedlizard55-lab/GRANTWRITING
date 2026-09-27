/**
 * Explainable opportunity fit. This is not a probability of award.
 * Weights are fixed and shown to the user. A component that cannot be
 * assessed is omitted from the weighted fit rather than scored as zero.
 */

export const WEIGHTS = {
  alignment: 0.45,
  eligibility: 0.25,
  funding: 0.15,
  timeline: 0.15,
};

const STOP = new Set(
  "a an the and or of to for in on with by from that this is are be as at it its into over under than then not your our their will can may using use used about across within without per via using".split(
    " "
  )
);

export function tokenize(text) {
  if (!text) return [];
  const tokens = String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .split(/\s+/)
    .filter((token) => token.length >= 3 && !STOP.has(token));
  return [...new Set(tokens)];
}

export function daysUntil(iso, asOf) {
  if (!iso || !asOf) return null;
  const close = Date.parse(`${iso}T00:00:00Z`);
  const today = Date.parse(`${asOf}T00:00:00Z`);
  if (Number.isNaN(close) || Number.isNaN(today)) return null;
  return Math.round((close - today) / 86400000);
}

function snippets(description, terms, limit = 2) {
  if (!description || !terms.length) return [];
  const lower = description.toLowerCase();
  const found = [];
  for (const term of terms) {
    const at = lower.indexOf(term);
    if (at < 0) continue;
    const start = Math.max(0, at - 80);
    const end = Math.min(description.length, at + term.length + 110);
    let text = description.slice(start, end).replace(/\s+/g, " ").trim();
    if (start > 0) text = `…${text}`;
    if (end < description.length) text = `${text}…`;
    found.push({ term, text });
    if (found.length >= limit) break;
  }
  return found;
}

export function scoreOpportunity(project, opportunity, asOf) {
  const components = [];
  const blockers = [];
  const projectText = [project.title, project.summary, ...(project.keywords || [])].filter(Boolean).join(" ");
  const projectTokens = tokenize(projectText);
  const selectedTopics = new Set(project.topics || []);

  if (projectTokens.length || selectedTopics.size) {
    const titleTokens = tokenize(opportunity.title);
    const topicTokens = (opportunity.topics || []).flatMap((topic) => tokenize(`${topic.label} ${(topic.matched_terms || []).join(" ")}`));
    const descriptionTokens = tokenize(opportunity.description);
    const oppTokens = new Set([...titleTokens, ...topicTokens, ...descriptionTokens]);
    const overlap = projectTokens.filter((token) => oppTokens.has(token));
    const titleHits = projectTokens.filter((token) => titleTokens.includes(token));
    const topicHits = (opportunity.topics || [])
      .filter((topic) => selectedTopics.has(topic.id) || projectTokens.some((token) => topic.label.toLowerCase().includes(token) || (topic.matched_terms || []).some((term) => term.toLowerCase().includes(token))))
      .map((topic) => topic.label);
    let score = 0;
    if (projectTokens.length) {
      score = Math.round((overlap.length / projectTokens.length) * 100);
      if (titleHits.length) score = Math.min(100, score + 10);
    }
    if (selectedTopics.size) {
      const topicScore = Math.round((topicHits.length / selectedTopics.size) * 100);
      score = projectTokens.length ? Math.round(score * 0.7 + topicScore * 0.3) : topicScore;
    }
    const evidence = [];
    if (overlap.length) evidence.push(`Shared terms: ${overlap.slice(0, 12).join(", ")}.`);
    else evidence.push("No shared terms between the project text and this record.");
    if (titleHits.length) evidence.push(`Terms also in the official title: ${titleHits.join(", ")}.`);
    if (topicHits.length) evidence.push(`Derived topic overlap: ${topicHits.join(", ")}. Topic tags are classifications, not official categories.`);
    if (!projectTokens.length && !topicHits.length) evidence.push("No project text and no selected topic matched.");
    const quotes = snippets(opportunity.description || "", overlap.slice(0, 4));
    components.push({
      id: "alignment",
      label: "Research alignment",
      score,
      weight: WEIGHTS.alignment,
      assessed: true,
      evidence,
      quotes,
    });
  } else {
    components.push({
      id: "alignment",
      label: "Research alignment",
      score: null,
      weight: WEIGHTS.alignment,
      assessed: false,
      evidence: ["Add a project description or keywords to assess alignment."],
      quotes: [],
    });
  }

  const applicantCodes = new Set(project.applicantTypes || []);
  const published = opportunity.applicant_types || [];
  if (!applicantCodes.size) {
    components.push({
      id: "eligibility",
      label: "Eligibility",
      score: null,
      weight: WEIGHTS.eligibility,
      assessed: false,
      evidence: ["Applicant type was not selected, so eligibility was not scored."],
    });
  } else if (!published.length) {
    components.push({
      id: "eligibility",
      label: "Eligibility",
      score: null,
      weight: WEIGHTS.eligibility,
      assessed: false,
      evidence: ["The source did not publish applicant-type codes. This is not treated as eligible or ineligible."],
    });
  } else if (published.some((item) => item.code === "99")) {
    components.push({
      id: "eligibility",
      label: "Eligibility",
      score: 100,
      weight: WEIGHTS.eligibility,
      assessed: true,
      evidence: ["Applicant types are published as unrestricted (code 99), subject to the additional eligibility text."],
    });
  } else {
    const hit = published.filter((item) => applicantCodes.has(item.code));
    if (hit.length) {
      components.push({
        id: "eligibility",
        label: "Eligibility",
        score: 100,
        weight: WEIGHTS.eligibility,
        assessed: true,
        evidence: [`Published applicant types include: ${hit.map((item) => item.label || item.code).join("; ")}.`],
      });
    } else {
      blockers.push("Published applicant-type codes do not include the selected applicant type.");
      components.push({
        id: "eligibility",
        label: "Eligibility",
        score: 0,
        weight: WEIGHTS.eligibility,
        assessed: true,
        evidence: [
          `Published types: ${published.map((item) => item.label || item.code).join("; ")}.`,
          "This is a comparison to published codes, not a legal eligibility determination.",
        ],
      });
    }
  }

  const budget = Number(project.budget);
  const hasBudget = Number.isFinite(budget) && budget > 0;
  const ceiling = opportunity.funding?.ceiling;
  const floor = opportunity.funding?.floor;
  if (!hasBudget) {
    components.push({
      id: "funding",
      label: "Funding compatibility",
      score: null,
      weight: WEIGHTS.funding,
      assessed: false,
      evidence: ["No project budget was entered, so funding compatibility was not scored."],
    });
  } else if (ceiling == null && floor == null) {
    components.push({
      id: "funding",
      label: "Funding compatibility",
      score: null,
      weight: WEIGHTS.funding,
      assessed: false,
      evidence: ["Award floor and ceiling were not published. No funding comparison was invented."],
    });
  } else if (ceiling != null && floor != null && budget >= floor && budget <= ceiling) {
    components.push({
      id: "funding",
      label: "Funding compatibility",
      score: 100,
      weight: WEIGHTS.funding,
      assessed: true,
      evidence: [`Entered budget is within the published floor and ceiling.`],
    });
  } else if (ceiling != null && floor == null && budget <= ceiling) {
    components.push({
      id: "funding",
      label: "Funding compatibility",
      score: 85,
      weight: WEIGHTS.funding,
      assessed: true,
      evidence: ["Entered budget is at or below the published ceiling. No floor was published."],
    });
  } else if (floor != null && ceiling == null && budget >= floor) {
    components.push({
      id: "funding",
      label: "Funding compatibility",
      score: 70,
      weight: WEIGHTS.funding,
      assessed: true,
      evidence: ["Entered budget is at or above the published floor. No ceiling was published."],
    });
  } else if (ceiling != null && budget > ceiling) {
    components.push({
      id: "funding",
      label: "Funding compatibility",
      score: 15,
      weight: WEIGHTS.funding,
      assessed: true,
      evidence: ["Entered budget is above the published award ceiling."],
    });
  } else {
    components.push({
      id: "funding",
      label: "Funding compatibility",
      score: 40,
      weight: WEIGHTS.funding,
      assessed: true,
      evidence: ["Entered budget is below the published floor. Some programs still allow smaller requests; confirm in the announcement."],
    });
  }

  const status = opportunity.status;
  if (status === "closed" || status === "archived" || status === "canceled") {
    blockers.push(`Status is ${status}. This is not an open application window in the catalog.`);
    components.push({
      id: "timeline",
      label: "Timeline",
      score: 0,
      weight: WEIGHTS.timeline,
      assessed: true,
      evidence: [opportunity.status_basis || `Status is ${status}.`],
    });
  } else if (status === "verification_required") {
    components.push({
      id: "timeline",
      label: "Timeline",
      score: 20,
      weight: WEIGHTS.timeline,
      assessed: true,
      evidence: [opportunity.status_basis || "Status requires verification before treating the opportunity as open."],
    });
  } else if (status === "upcoming") {
    components.push({
      id: "timeline",
      label: "Timeline",
      score: 75,
      weight: WEIGHTS.timeline,
      assessed: true,
      evidence: [opportunity.status_basis || "Forecast. Not yet a posted synopsis."],
    });
  } else if (status === "open_program") {
    components.push({
      id: "timeline",
      label: "Timeline",
      score: 60,
      weight: WEIGHTS.timeline,
      assessed: true,
      evidence: ["Standing program. No single deadline was published in the source used here."],
    });
  } else if (status === "open") {
    const days = daysUntil(opportunity.dates?.close, asOf);
    if (days == null) {
      components.push({
        id: "timeline",
        label: "Timeline",
        score: 50,
        weight: WEIGHTS.timeline,
        assessed: true,
        evidence: ["Posted as open, but no close date was published. Deadline was not inferred."],
      });
    } else if (days > 45) {
      components.push({
        id: "timeline",
        label: "Timeline",
        score: 100,
        weight: WEIGHTS.timeline,
        assessed: true,
        evidence: [`Published close date is ${days} days after the catalog as-of date. The source published a date, not a cutoff time.`],
      });
    } else if (days > 21) {
      components.push({
        id: "timeline",
        label: "Timeline",
        score: 80,
        weight: WEIGHTS.timeline,
        assessed: true,
        evidence: [`Published close date is ${days} days after the catalog as-of date.`],
      });
    } else if (days > 7) {
      components.push({
        id: "timeline",
        label: "Timeline",
        score: 55,
        weight: WEIGHTS.timeline,
        assessed: true,
        evidence: [`Published close date is ${days} days after the catalog as-of date.`],
      });
    } else {
      components.push({
        id: "timeline",
        label: "Timeline",
        score: 35,
        weight: WEIGHTS.timeline,
        assessed: true,
        evidence: [`Published close date is ${days} day(s) after the catalog as-of date. Confirm the cutoff time on the official page.`],
      });
    }
  } else {
    components.push({
      id: "timeline",
      label: "Timeline",
      score: null,
      weight: WEIGHTS.timeline,
      assessed: false,
      evidence: ["Status is unknown, so timeline was not scored."],
    });
  }

  const assessed = components.filter((item) => item.assessed && item.score != null);
  const weight = assessed.reduce((sum, item) => sum + item.weight, 0);
  const fit = weight ? Math.round(assessed.reduce((sum, item) => sum + item.score * item.weight, 0) / weight) : null;
  const evidenceStrength = evidenceStrengthScore(opportunity);
  return {
    fit,
    fit_label: "Opportunity fit",
    not_a_win_probability: true,
    weights: WEIGHTS,
    components,
    blockers,
    evidence_strength: evidenceStrength,
    note: "Fit compares the project you entered with published fields and extracted text. It does not estimate the chance of receiving an award.",
  };
}

export function evidenceStrengthScore(opportunity) {
  const checks = [
    { id: "description", ok: (opportunity.description || "").length > 200, label: "Description longer than 200 characters" },
    { id: "eligibility", ok: (opportunity.applicant_types || []).length > 0, label: "Applicant-type codes published" },
    { id: "eligibility_text", ok: Boolean(opportunity.eligibility_text), label: "Eligibility text published" },
    { id: "deadline", ok: Boolean(opportunity.dates?.close) || opportunity.status === "open_program", label: "Close date published, or standing program with no date" },
    { id: "amount", ok: opportunity.funding?.ceiling != null || opportunity.funding?.estimated_total != null, label: "Ceiling or estimated total published" },
    { id: "aln", ok: (opportunity.aln || []).length > 0, label: "Assistance listing published" },
    { id: "contact", ok: Boolean(opportunity.contact?.email || opportunity.contact?.name), label: "Contact published" },
  ];
  const present = checks.filter((item) => item.ok).length;
  return {
    score: Math.round((present / checks.length) * 100),
    present,
    of: checks.length,
    checks,
    note: "Evidence strength measures how many decision fields the source published. It is not part of the fit score and it is not a quality rating of the research.",
  };
}

export function rankMatches(project, opportunities, asOf) {
  return opportunities
    .map((opportunity) => ({ opportunity, match: scoreOpportunity(project, opportunity, asOf) }))
    .sort((a, b) => {
      const aBlock = a.match.blockers.length > 0;
      const bBlock = b.match.blockers.length > 0;
      if (aBlock !== bBlock) return aBlock ? 1 : -1;
      return (b.match.fit ?? -1) - (a.match.fit ?? -1);
    });
}
