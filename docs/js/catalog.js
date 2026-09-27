/**
 * Pure catalog logic: filtering, sorting, and deadline math.
 *
 * This module touches no DOM state so it can be tested directly with
 * `node --test`. Every rule here operates on fields the pipeline published.
 * Nothing is inferred for a blank field: a missing amount or deadline is
 * treated as "not published" and excluded from value comparisons rather
 * than read as zero.
 */

import { daysUntil } from "./match.js";

/** Sort keys the explorer exposes. `-desc` reverses the field ordering. */
export const SORT_FIELDS = ["close", "posted", "updated", "ceiling", "agency", "title"];

export function splitSort(sort) {
  const raw = String(sort || "close");
  if (raw.endsWith("-desc")) return { field: raw.slice(0, -5), direction: -1 };
  if (raw.endsWith("-asc")) return { field: raw.slice(0, -4), direction: 1 };
  return { field: raw, direction: 1 };
}

/** YYYY-MM-DD in the viewer's own timezone. Deadlines are dates, not times. */
export function viewerDate(now = new Date()) {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * Whole days from `referenceDate` to the published close date.
 * Negative means the published date is already behind the reference date.
 */
export function daysToClose(record, referenceDate) {
  return daysUntil((record?.dates || {}).close, referenceDate);
}

function valueOf(record, field) {
  if (field === "title") return record.title || "";
  if (field === "agency") return record.agency_name || record.agency_code || "";
  if (field === "ceiling") {
    const ceiling = (record.funding || {}).ceiling;
    return ceiling == null ? null : Number(ceiling);
  }
  if (field === "posted") return (record.dates || {}).post || null;
  if (field === "updated") return (record.dates || {}).last_updated || null;
  return (record.dates || {}).close || null;
}

/**
 * Order two opportunities. Records missing the sorted field always sort last,
 * in both directions, so a blank amount never floats to the top of a
 * "highest ceiling" list. Ties break on title for a stable order.
 */
export function compareRecords(a, b, sort) {
  const { field, direction } = splitSort(sort);
  const left = valueOf(a, field);
  const right = valueOf(b, field);
  const leftMissing = left == null || left === "";
  const rightMissing = right == null || right === "";
  if (leftMissing || rightMissing) {
    if (leftMissing && rightMissing) return (a.title || "").localeCompare(b.title || "");
    return leftMissing ? 1 : -1;
  }
  const compared = typeof left === "number" ? left - right : String(left).localeCompare(String(right));
  if (compared !== 0) return compared * direction;
  return (a.title || "").localeCompare(b.title || "");
}

export function sortRecords(rows, sort) {
  return rows.slice().sort((a, b) => compareRecords(a, b, sort));
}

const searchCache = new WeakMap();

function cached(key, row, build) {
  const hit = searchCache.get(row);
  if (hit && hit[key] != null) return hit[key];
  const value = build(row);
  searchCache.set(row, { ...(hit || {}), [key]: value });
  return value;
}

function searchBlob(record) {
  return cached("opportunity", record, (row) =>
    [
      row.title,
      row.number,
      row.agency_name,
      row.agency_code,
      row.description,
      row.eligibility_text,
      ...(row.topics || []).map((topic) => `${topic.label} ${(topic.matched_terms || []).join(" ")}`),
      ...(row.aln || []).map((aln) => `${aln.number} ${aln.title || ""}`),
    ]
      .filter(Boolean)
      .join("\n")
      .toLowerCase()
  );
}

/**
 * Apply explorer filters.
 *
 * Amount filters compare against the published award ceiling. A record with no
 * published ceiling cannot satisfy an amount filter, so it is excluded and
 * counted in `amount_excluded_missing_ceiling` — the UI reports that count
 * instead of silently dropping rows.
 */
export function filterOpportunities(records, params, referenceDate) {
  const q = String(params.get("q") || "").trim().toLowerCase();
  const status = params.get("status") || "";
  const agency = params.get("agency") || "";
  const topic = params.get("topic") || "";
  const applicant = params.get("applicant") || "";
  const instrument = params.get("instrument") || "";
  const kind = params.get("kind") || "";
  const location = String(params.get("location") || "").trim().toLowerCase();
  const closing = Number(params.get("closing") || "");
  const min = params.get("min") !== null && params.get("min") !== "" ? Number(params.get("min")) : null;
  const max = params.get("max") !== null && params.get("max") !== "" ? Number(params.get("max")) : null;
  const amountFilterActive = min != null || max != null;

  let amountExcludedMissingCeiling = 0;
  let deadlineExcludedNoDate = 0;

  const rows = records.filter((record) => {
    if (q && !searchBlob(record).includes(q)) return false;
    if (status && record.status !== status) return false;
    if (agency && record.top_agency_code !== agency && record.agency_code !== agency) return false;
    if (topic && !(record.topics || []).some((item) => item.id === topic)) return false;
    if (applicant && !(record.applicant_types || []).some((item) => item.code === applicant)) return false;
    if (instrument && !(record.instruments || []).some((item) => item.code === instrument)) return false;
    if (kind && record.record_kind !== kind) return false;
    if (location && !`${record.eligibility_text || ""}\n${record.description || ""}`.toLowerCase().includes(location)) return false;
    if (Number.isFinite(closing) && closing > 0) {
      const days = daysToClose(record, referenceDate);
      if (days == null) {
        deadlineExcludedNoDate += 1;
        return false;
      }
      if (days < 0 || days > closing) return false;
    }
    if (amountFilterActive) {
      const ceiling = (record.funding || {}).ceiling;
      if (ceiling == null) {
        amountExcludedMissingCeiling += 1;
        return false;
      }
      if (min != null && ceiling < min) return false;
      if (max != null && ceiling > max) return false;
    }
    return true;
  });

  return {
    rows: sortRecords(rows, params.get("sort") || "close"),
    amount_excluded_missing_ceiling: amountExcludedMissingCeiling,
    deadline_excluded_missing_date: deadlineExcludedNoDate,
  };
}

/** Dollar amount on either an award row or a USAspending obligation row. */
export function awardAmount(row) {
  const value = row.amount_obligated != null ? row.amount_obligated : row.amount;
  return value == null ? null : Number(value);
}

export function awardAgency(row) {
  return row.agency || row.awarding_agency || "";
}

export function awardAgencyName(row) {
  return row.agency_name || row.awarding_agency || row.awarding_sub_agency || "";
}

function awardBlob(row) {
  return cached("award", row, (item) =>
    [
      item.title,
      item.description,
      awardAgencyName(item),
      awardAgency(item),
      item.awardee_name,
      item.awardee_state,
      item.awardee_city,
      item.pi_name,
      item.program,
      item.directorate,
      item.division,
      item.project_number,
      item.opportunity_number,
      item.cfda,
      item.abstract,
      ...(item.topics || []).map((topic) => `${topic.label} ${(topic.matched_terms || []).join(" ")}`),
    ]
      .filter(Boolean)
      .join("\n")
      .toLowerCase()
  );
}

function awardDate(row) {
  return row.start_date || row.award_date || row.award_notice_date || null;
}

/**
 * Filter the historical award and obligation rows already in the catalog.
 *
 * These rows are samples. The filter narrows the sample; it does not turn the
 * sample into a census, and the caller must keep the coverage note visible.
 */
export function filterAwards(rows, params) {
  const q = String(params.get("q") || "").trim().toLowerCase();
  const agency = params.get("agency") || "";
  const topic = params.get("topic") || "";
  const state = String(params.get("state") || "").trim().toLowerCase();
  const source = params.get("source") || "";
  const min = params.get("min") !== null && params.get("min") !== "" ? Number(params.get("min")) : null;
  const kind = params.get("kind") || "";

  let amountExcluded = 0;
  const filtered = rows.filter((row) => {
    if (kind === "award" && row.record_type !== "historical_award") return false;
    if (kind === "obligation" && row.record_type !== "obligation") return false;
    if (q && !awardBlob(row).includes(q)) return false;
    if (agency && awardAgency(row).toUpperCase() !== agency.toUpperCase()) return false;
    if (topic && !(row.topics || []).some((item) => item.id === topic)) return false;
    if (state && String(row.awardee_state || "").toLowerCase() !== state) return false;
    if (source && (row.source || {}).id !== source) return false;
    if (min != null) {
      const amount = awardAmount(row);
      if (amount == null) {
        amountExcluded += 1;
        return false;
      }
      if (amount < min) return false;
    }
    return true;
  });
  return { rows: filtered, amount_excluded_missing_amount: amountExcluded };
}

/**
 * Order award rows. Missing amounts and dates sort last in both directions.
 */
export function compareAwards(a, b, sort) {
  const { field, direction } = splitSort(sort);
  const pick = (row) => {
    if (field === "amount") return awardAmount(row);
    if (field === "date") return awardDate(row);
    if (field === "agency") return awardAgencyName(row);
    return row.title || "";
  };
  const left = pick(a);
  const right = pick(b);
  const leftMissing = left == null || left === "";
  const rightMissing = right == null || right === "";
  if (leftMissing || rightMissing) {
    if (leftMissing && rightMissing) return (a.title || "").localeCompare(b.title || "");
    return leftMissing ? 1 : -1;
  }
  const compared = typeof left === "number" ? left - right : String(left).localeCompare(String(right));
  if (compared !== 0) return compared * direction;
  return (a.title || "").localeCompare(b.title || "");
}

export function sortAwards(rows, sort) {
  return rows.slice().sort((a, b) => compareAwards(a, b, sort));
}

/** Agency choices present in a set of rows, labeled from the row itself. */
export function awardAgencyOptions(rows) {
  const map = new Map();
  for (const row of rows) {
    const code = awardAgency(row);
    if (!code || map.has(code)) continue;
    map.set(code, awardAgencyName(row) || code);
  }
  return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
}

/** Awardee state codes present in a set of rows. */
export function awardStateOptions(rows) {
  const set = new Set();
  for (const row of rows) {
    const value = String(row.awardee_state || "").trim();
    if (value) set.add(value.toUpperCase());
  }
  return [...set].sort();
}

/**
 * Slice one page out of a result set.
 *
 * A page number beyond the end is clamped to the last page rather than
 * returning an empty list, so a stale or hand-edited `page=` link still shows
 * records instead of a dead end.
 */
export function paginate(rows, page, pageSize) {
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const requested = Math.max(1, Number(page) || 1);
  const safePage = Math.min(requested, pages);
  const start = (safePage - 1) * pageSize;
  return { rows: rows.slice(start, start + pageSize), page: safePage, pages, clamped: safePage !== requested };
}

/**
 * Only http and https URLs are safe to render as links.
 *
 * Every URL in this catalog is copied from a government source field. They are
 * official, but they are still external data, so a value that is not an http(s)
 * URL is refused instead of being handed to an anchor's href.
 */
export function safeHttpUrl(url) {
  if (!url) return null;
  try {
    const parsed = new URL(String(url), "https://invalid.invalid");
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return parsed.href;
  } catch {
    return null;
  }
}
