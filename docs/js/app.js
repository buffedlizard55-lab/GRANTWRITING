import { rankMatches, scoreOpportunity, daysUntil } from "./match.js";
import {
  awardAgencyName,
  awardAgencyOptions,
  awardAmount,
  awardStateOptions,
  daysToClose,
  filterAwards,
  filterOpportunities,
  paginate,
  safeHttpUrl,
  sortAwards,
  viewerDate,
} from "./catalog.js";
import { csvCell } from "./csv.js";

const STORE_KEY = "frgi.project.v1";
const PAGE_SIZE = 20;
const STATUS_LABEL = {
  open: "Open",
  upcoming: "Upcoming",
  open_program: "Standing program",
  closed: "Closed",
  archived: "Archived",
  canceled: "Canceled",
  unknown: "Unknown",
  verification_required: "Verification required",
};

/** Explorer sort choices. `-desc` is handled by compareRecords in catalog.js. */
const SORT_OPTIONS = [
  ["close", "Deadline — soonest first"],
  ["close-desc", "Deadline — latest first"],
  ["posted-desc", "Posted — newest first"],
  ["posted", "Posted — oldest first"],
  ["ceiling-desc", "Ceiling — highest first"],
  ["ceiling", "Ceiling — lowest first"],
  ["updated-desc", "Source update — newest first"],
  ["updated", "Source update — oldest first"],
  ["agency", "Agency — A to Z"],
  ["agency-desc", "Agency — Z to A"],
  ["title", "Title — A to Z"],
  ["title-desc", "Title — Z to A"],
];

const state = {
  ready: false,
  error: null,
  meta: null,
  aggregates: null,
  opportunities: [],
  awards: [],
  obligations: [],
  changes: null,
  codes: null,
  byId: new Map(),
};

const view = document.querySelector("#view");
const nav = document.querySelector("#sitenav");
const stamp = document.querySelector("#verified-stamp");
const toggle = document.querySelector(".nav-toggle");

toggle.addEventListener("click", () => {
  const open = document.body.classList.toggle("nav-open");
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
});
nav.addEventListener("click", (event) => {
  if (event.target.closest("a")) {
    document.body.classList.remove("nav-open");
    toggle.setAttribute("aria-expanded", "false");
  }
});
window.addEventListener("hashchange", render);
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !event.target.matches("input, textarea, select")) {
    event.preventDefault();
    const box = document.querySelector("#q");
    if (box) box.focus();
  }
});

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "checked" || key === "selected") node[key] = Boolean(value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clear(node) {
  node.replaceChildren();
}

function money(value) {
  if (value == null) return "Not published";
  return value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function prettyDate(iso) {
  if (!iso) return "Not published";
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function prettyStamp(iso) {
  if (!iso) return "unknown";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * The pipeline records retrieval time in America/New_York with its offset.
 * The browser renders it in the viewer's own timezone, so the label has to
 * say which one the reader is looking at.
 */
function verifiedLine(iso) {
  if (!iso) return "unknown";
  return `${prettyStamp(iso)} · your time`;
}

function hoursSince(iso) {
  const parsed = Date.parse(iso || "");
  if (Number.isNaN(parsed)) return null;
  return (Date.now() - parsed) / 36e5;
}

function statusBadge(status) {
  return h("span", { class: `badge ${status || "unknown"}` }, STATUS_LABEL[status] || status || "Unknown");
}

function factBadge() {
  return h("span", { class: "badge fact" }, "Official fact");
}

function derivedBadge() {
  return h("span", { class: "badge derived" }, "Derived");
}

function externalLink(url, label) {
  const safe = safeHttpUrl(url);
  if (!safe) {
    return url
      ? h("span", { class: "muted" }, `Unusable URL in the source field: ${url}`)
      : h("span", { class: "muted" }, "No official URL");
  }
  return h("a", { href: safe, target: "_blank", rel: "noopener noreferrer" }, label || safe);
}

function route() {
  const raw = (location.hash || "#/feed").replace(/^#/, "");
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  return { parts, params: new URLSearchParams(query), path: `/${parts.join("/")}` || "/feed" };
}

function setNav(name) {
  for (const link of nav.querySelectorAll("a")) {
    if (link.dataset.nav === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

function go(hash) {
  location.hash = hash;
}

function asOf() {
  return state.meta?.as_of_date || null;
}

function loadProject() {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) || "null");
  } catch {
    return null;
  }
}

function saveProject(project) {
  localStorage.setItem(STORE_KEY, JSON.stringify(project));
}

async function loadJson(name) {
  const response = await fetch(`data/${name}`, { cache: "no-cache" });
  if (!response.ok) return null;
  return response.json();
}

async function loadCatalog() {
  try {
    const [meta, aggregates, opportunityFile, awardFile, obligationFile, changes, codes] = await Promise.all([
      loadJson("meta.json"),
      loadJson("aggregates.json"),
      loadJson("opportunities.json"),
      loadJson("awards.json"),
      loadJson("obligations.json"),
      loadJson("changes.json"),
      loadJson("codes.json"),
    ]);
    state.meta = meta;
    state.aggregates = aggregates;
    state.opportunities = opportunityFile?.opportunities || [];
    state.awards = awardFile?.awards || [];
    state.obligations = obligationFile?.obligations || [];
    state.changes = changes;
    state.codes = codes;
    state.byId = new Map(state.opportunities.map((record) => [record.id, record]));
    state.ready = true;
    paintStamp();
  } catch (error) {
    state.error = error.message || String(error);
    state.ready = true;
  }
  render();
}

function paintStamp() {
  clear(stamp);
  if (!state.meta?.generated_at) {
    stamp.textContent = "No verified catalog published yet";
    stamp.classList.add("warn");
    return;
  }
  const age = hoursSince(state.meta.generated_at);
  const stale = age != null && age > 36;
  stamp.classList.toggle("warn", stale);
  stamp.append(
    "Last verified ",
    h("strong", {}, verifiedLine(state.meta.generated_at)),
    stale ? ` · ${Math.round(age)} hours old` : ""
  );
}

function pageHead(kicker, title, lede) {
  return h("header", { class: "page-head" }, [
    h("p", { class: "eyebrow" }, kicker),
    h("h1", {}, title),
    lede ? h("p", { class: "lede" }, lede) : null,
  ]);
}

function stat(value, label) {
  return h("div", { class: "stat" }, [h("b", {}, value), h("span", {}, label)]);
}

function counts() {
  const by = state.meta?.counts?.by_status || {};
  return h("div", { class: "stats" }, [
    stat(String(by.open || 0), "Open opportunities"),
    stat(String(by.upcoming || 0), "Upcoming forecasts"),
    stat(String(by.open_program || 0), "Standing programs"),
    stat(String(by.closed || 0), "Recently closed"),
  ]);
}

function legend() {
  return h("div", { class: "callout fact" }, [
    h("div", { class: "badge-row" }, [factBadge(), derivedBadge(), h("span", { class: "badge" }, "Extracted quote"), h("span", { class: "badge" }, "Not published")]),
    h("p", { class: "small" }, "Official fact is copied from a government source. Derived means this site counted or classified those facts and shows the rule. An extracted quote is a sentence copied from the official text, not a rewrite. Not published means the source left the field blank — it is not zero, and it was not guessed."),
  ]);
}

function deadlineText(record) {
  const close = record.dates?.close;
  if (!close) return record.status === "open_program" ? "No single deadline published" : "Deadline not published";
  const days = daysUntil(close, viewerDate());
  const when = prettyDate(close);
  if (days == null) return when;
  if (days < 0 && record.status === "open") {
    return `${when} · before today. Catalog still says open as of ${asOf() || "the extract date"}. Confirm the official page.`;
  }
  if (days < 0) return `${when} · passed`;
  if (days === 0) return `${when} · closes today, confirm the time`;
  return `${when} · ${days} day${days === 1 ? "" : "s"}`;
}

function moneyLine(record) {
  const funding = record.funding || {};
  if (funding.ceiling == null && funding.floor == null && funding.estimated_total == null) return "Amounts not published";
  const ceilingText = funding.ceiling === 0 ? "ceiling published as $0" : money(funding.ceiling);
  const floorText = funding.floor === 0 ? "floor published as $0" : money(funding.floor);
  const range =
    funding.floor == null && funding.ceiling == null
      ? "Award range not published"
      : `${floorText} – ${ceilingText}`;
  const total = funding.estimated_total == null ? "" : ` · est. program ${money(funding.estimated_total)}`;
  return `${range}${total}`;
}

function topicChips(record) {
  const chips = (record.topics || []).slice(0, 4).map((topic) =>
    h("a", { class: "chip", href: `#/topic/${encodeURIComponent(topic.id)}` }, topic.label)
  );
  if (!chips.length) chips.push(h("span", { class: "chip" }, "Unclassified"));
  return h("div", { class: "chip-row" }, chips);
}

function card(record) {
  return h("article", { class: `card ${record.status}` }, [
    h("div", { class: "badge-row" }, [
      statusBadge(record.status),
      record.record_kind === "program" ? h("span", { class: "badge" }, "Program page") : null,
      record.is_sbir_sttr ? h("span", { class: "badge" }, "SBIR/STTR") : null,
    ]),
    h("h3", {}, h("a", { href: `#/opportunity/${encodeURIComponent(record.id)}` }, record.title)),
    h("p", { class: "meta-row" }, [
      h("b", {}, record.agency_name || "Agency not published"),
      record.number ? ` · ${record.number}` : "",
    ]),
    h("p", { class: "meta-row" }, [deadlineText(record), " · ", h("span", { class: "money" }, moneyLine(record))]),
    topicChips(record),
    h("p", { class: "small" }, externalLink(record.urls?.official, "Official source")),
  ]);
}

function emptyCatalog() {
  clear(view);
  setNav("feed");
  view.append(
    pageHead(
      "Catalog",
      "No verified opportunities are published yet.",
      "This site does not display sample or invented grants. The refresh pipeline has to download the Grants.gov extract and write the catalog before any opportunity appears here."
    ),
    h("div", { class: "callout warn" }, [
      h("h2", {}, "What is missing"),
      h("p", {}, state.error ? `The catalog could not be read: ${state.error}` : "docs/data/opportunities.json is not available yet."),
      h("p", {}, "After a successful refresh, this page shows open and upcoming research funding with the retrieval time, the official URL, and the fields the source actually published."),
    ])
  );
}

/**
 * Explorer filtering. Every record and every filter is compared against the
 * same reference date — the viewer's own date — so the count on the feed and
 * the count in the explorer cannot disagree.
 */
function filtered(params) {
  return filterOpportunities(state.opportunities, params, viewerDate());
}

function renderFeed() {
  setNav("feed");
  clear(view);
  if (!state.opportunities.length) {
    emptyCatalog();
    return;
  }
  const open = state.opportunities.filter((record) => record.status === "open" && record.dates?.close);
  const soon = open
    .filter((record) => {
      const days = daysUntil(record.dates.close, viewerDate());
      return days != null && days >= 0 && days <= 21;
    })
    .sort((a, b) => a.dates.close.localeCompare(b.dates.close));
  view.append(
    ...[
      pageHead(
        "Current funding feed",
        "What research funding is open right now?",
        "Open and upcoming federal research opportunities from the latest official extract, plus NSF program pages. Closed records stay labeled closed."
      ),
      counts(),
      legend(),
      changeStrip(),
      staleStrip(),
    ].filter(Boolean)
  );
  view.append(feedSection("Closing within 21 days", soon, "#/explore?status=open&closing=21&sort=close"));
  view.append(
    feedSection(
      "Open, deadline published",
      open.sort((a, b) => a.dates.close.localeCompare(b.dates.close)),
      "#/explore?status=open&sort=close"
    )
  );
  view.append(
    feedSection(
      "Open, deadline not published",
      state.opportunities.filter((record) => record.status === "open" && !record.dates?.close),
      "#/explore?status=open"
    )
  );
  view.append(
    feedSection(
      "Upcoming forecasts",
      state.opportunities.filter((record) => record.status === "upcoming"),
      "#/explore?status=upcoming"
    )
  );
  view.append(
    feedSection(
      "Standing programs",
      state.opportunities.filter((record) => record.status === "open_program"),
      "#/explore?status=open_program",
      "These are program pages, usually from the NSF funding feed. A missing deadline was not filled in."
    )
  );
  view.append(
    feedSection(
      "Needs verification",
      state.opportunities.filter((record) => record.status === "verification_required"),
      "#/explore?status=verification_required",
      "Cancellation language, or a synopsis with no deadline that the source has not updated in more than 18 months. Not labeled open."
    )
  );
}

function changeStrip() {
  const summary = state.meta?.changes_summary;
  if (!summary?.compared_to_previous_catalog) {
    return h("div", { class: "callout" }, "First catalog retained by this pipeline. A record can be old to the agency and new to this site. Use the post date, not the first-seen time.");
  }
  return h("div", { class: "callout analysis" }, [
    derivedBadge(),
    h("p", {}, `Since the previous catalog: ${summary.new} new ids, ${summary.removed} removed, ${summary.changed} changed, ${summary.newly_closed} newly closed.`),
    h("p", { class: "small" }, "Removed means the id is absent from the new extract. That is not a documented cancellation."),
    h("span", {}, [h("a", { href: "#/changes" }, "See what changed"), " · ", h("a", { href: "#/sources" }, "verification details")]),
  ]);
}

function staleStrip() {
  const age = hoursSince(state.meta?.generated_at);
  if (age == null || age <= 36) return null;
  return h("div", { class: "callout warn" }, `This catalog was built ${Math.round(age)} hours ago. A deadline may have moved since then. Check the official page before applying.`);
}

function feedSection(title, rows, href, note) {
  const section = h("section", { class: "section" }, [
    h("div", { class: "section-head" }, [h("h2", {}, title), h("a", { href }, `View ${rows.length}`)]),
    note ? h("p", { class: "small muted" }, note) : null,
  ]);
  if (!rows.length) {
    section.append(h("p", { class: "muted" }, "None in the current catalog."));
    return section;
  }
  section.append(h("div", { class: "cards" }, rows.slice(0, 6).map(card)));
  return section;
}

function renderExplore() {
  setNav("explore");
  const { params } = route();
  const { rows, amount_excluded_missing_ceiling, deadline_excluded_missing_date } = filtered(params);
  const { rows: slice, page, clamped } = paginate(rows, params.get("page"), PAGE_SIZE);
  clear(view);
  const agencies = agencyOptions();
  const topics = (state.aggregates?.topics || []).slice().sort((a, b) => a.label.localeCompare(b.label));
  view.append(
    pageHead("Grant explorer", "Search the verified catalog", "Filters use published fields. A blank amount is excluded from amount filters rather than treated as zero."),
    h("div", { class: "layout" }, [
      filterForm(params, agencies, topics),
      h("div", {}, [
        h("div", { class: "section-head" }, [
          h("p", { class: "result-count" }, `${rows.length} records`),
          h("button", { class: "button secondary", type: "button", onclick: () => exportCsv(rows) }, "Download CSV"),
        ]),
        filterNotes(amount_excluded_missing_ceiling, deadline_excluded_missing_date, params),
        clamped ? h("p", { class: "small muted filter-note" }, `That page is past the end of these results. Showing page ${page} instead.`) : h("span"),
        h("div", { class: "cards" }, slice.map(card)),
        pager(params, page, rows.length),
      ]),
    ])
  );
}

/** Say out loud what a filter dropped, instead of hiding it. */
function filterNotes(missingCeiling, missingDeadline, params) {
  const notes = [];
  if (missingCeiling) {
    notes.push(
      `${missingCeiling} more record${missingCeiling === 1 ? "" : "s"} matched the other filters but published no award ceiling, so the amount filter could not evaluate ${missingCeiling === 1 ? "it" : "them"}.`
    );
  }
  if (missingDeadline && (params.get("closing") || "")) {
    notes.push(
      `${missingDeadline} record${missingDeadline === 1 ? "" : "s"} published no close date and ${missingDeadline === 1 ? "was" : "were"} left out of the deadline filter. A missing deadline is not the same as an open one.`
    );
  }
  if (!notes.length) return h("span");
  return h("p", { class: "small muted filter-note" }, notes.join(" "));
}

function agencyOptions() {
  const map = new Map();
  for (const record of state.opportunities) {
    const code = record.top_agency_code;
    if (!code || map.has(code)) continue;
    map.set(code, record.top_agency_grouping_label || record.agency_name || code);
  }
  return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
}

function filterForm(params, agencies, topics) {
  const form = h("form", {
    class: "panel filters",
    onsubmit: (event) => {
      event.preventDefault();
      const data = new FormData(event.target);
      const next = new URLSearchParams();
      for (const [key, value] of data.entries()) {
        if (String(value).trim()) next.set(key, String(value).trim());
      }
      go(`/explore?${next.toString()}`);
    },
  });
  form.append(h("h2", {}, "Filters"));
  form.append(labeled("Search", h("input", { id: "q", name: "q", type: "search", value: params.get("q") || "", placeholder: "Title, number, agency, term" })));
  form.append(labeled("Status", select("status", params.get("status"), [["", "Any"], ...Object.entries(STATUS_LABEL)])));
  form.append(labeled("Agency", select("agency", params.get("agency"), [["", "Any"], ...agencies])));
  form.append(labeled("Derived topic", select("topic", params.get("topic"), [["", "Any"], ...topics.map((topic) => [topic.id, topic.label])])));
  form.append(
    labeled(
      "Applicant type",
      select("applicant", params.get("applicant"), [["", "Any"], ...(state.codes?.applicant_types || []).map((item) => [item.code, `${item.code} · ${item.label}`])])
    )
  );
  form.append(
    labeled(
      "Instrument",
      select("instrument", params.get("instrument"), [["", "Any"], ...(state.codes?.instruments || []).map((item) => [item.code, item.label || item.code])])
    )
  );
  form.append(labeled("Record kind", select("kind", params.get("kind"), [["", "Any"], ["opportunity", "Opportunity"], ["forecast", "Forecast"], ["program", "Standing program"]])));
  form.append(labeled("Place mentioned in text", h("input", { name: "location", value: params.get("location") || "", placeholder: "State or region word" })));
  form.append(labeled(`Closes within days of today (${prettyDate(viewerDate())})`, h("input", { name: "closing", type: "number", min: "1", value: params.get("closing") || "" })));
  form.append(labeled("Ceiling at least", h("input", { name: "min", type: "number", min: "0", value: params.get("min") || "" })));
  form.append(labeled("Ceiling at most", h("input", { name: "max", type: "number", min: "0", value: params.get("max") || "" })));
  form.append(labeled("Sort", select("sort", params.get("sort") || "close", SORT_OPTIONS)));
  form.append(h("div", { class: "button-row" }, [h("button", { class: "primary", type: "submit" }, "Apply"), h("a", { class: "button secondary", href: "#/explore" }, "Reset")]));
  return form;
}

function labeled(text, control) {
  const wrap = h("label", {}, text);
  wrap.append(control);
  return wrap;
}

function select(name, current, options) {
  const node = h("select", { name });
  for (const [value, label] of options) {
    const option = h("option", { value }, label);
    if (value === (current || "")) option.selected = true;
    node.append(option);
  }
  return node;
}

function pager(params, page, total) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (pages === 1) return h("span");
  const previous = new URLSearchParams(params);
  const next = new URLSearchParams(params);
  previous.set("page", String(page - 1));
  next.set("page", String(page + 1));
  return h("div", { class: "pager" }, [
    page > 1 ? h("a", { class: "button secondary", href: `#/explore?${previous}` }, "Previous") : null,
    h("span", {}, `Page ${page} of ${pages}`),
    page < pages ? h("a", { class: "button secondary", href: `#/explore?${next}` }, "Next") : null,
  ]);
}

function exportCsv(rows) {
  const header = ["id", "title", "number", "agency", "status", "post_date", "close_date", "ceiling", "floor", "estimated_total", "official_url", "derived_topics"];
  const lines = [header.join(",")];
  for (const record of rows) {
    lines.push(
      [
        record.id,
        record.title,
        record.number,
        record.agency_name,
        record.status,
        record.dates?.post,
        record.dates?.close,
        record.funding?.ceiling,
        record.funding?.floor,
        record.funding?.estimated_total,
        record.urls?.official,
        (record.topics || []).map((topic) => topic.label).join("|"),
      ]
        .map(csvCell)
        .join(",")
    );
  }
  downloadCsv(lines, "research-funding-catalog.csv");
}

function downloadCsv(lines, filename) {
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = h("a", { href: url, download: filename });
  link.click();
  URL.revokeObjectURL(url);
}

function renderOpportunity(id) {
  setNav("explore");
  const record = state.byId.get(id);
  clear(view);
  if (!record) {
    view.append(pageHead("Record", "That opportunity is not in the catalog."), h("a", { href: "#/explore" }, "Back to explorer"));
    return;
  }
  const project = loadProject();
  view.append(
    h("p", { class: "small" }, h("a", { href: "#/explore" }, "Explorer")),
    h("div", { class: "badge-row" }, [statusBadge(record.status), factBadge()]),
    h("h1", {}, record.title),
    h("p", { class: "lede" }, record.status_basis || ""),
    h("p", { class: "meta-row" }, [
      h("b", {}, record.agency_name || "Agency not published"),
      record.agency_code ? ` · ${record.agency_code}` : "",
      record.number ? ` · ${record.number}` : "",
    ]),
    h("div", { class: "button-row" }, [
      safeHttpUrl(record.urls?.official)
        ? h("a", { class: "button", href: safeHttpUrl(record.urls?.official), target: "_blank", rel: "noopener noreferrer" }, "Official page")
        : h("span", { class: "button secondary" }, "No usable official URL"),
      record.id.startsWith("gg-")
        ? h(
            "a",
            {
              class: "button secondary",
              href: `https://apply07.grants.gov/apply/jsf/workspace/createWorkspace.faces?activityID=CreateWorkspace&cleanSession=1&oppId=${encodeURIComponent(record.source_record_id)}`,
              target: "_blank",
              rel: "noopener noreferrer",
            },
            "Grants.gov apply link"
          )
        : null,
      h("a", { class: "button secondary", href: "#/build" }, "Compare with a project"),
    ]),
    record.id.startsWith("gg-")
      ? h("p", { class: "small muted" }, "The apply link uses the opportunity id in the same workspace URL the official Grants.gov page uses. If it does not open a package, use the official page.")
      : null,
    factGrid(record),
    quoteBlock("What the announcement says", record.objective_quotes, "Extracted sentences from the official description. Not a summary and not a generated project."),
    quoteBlock("Requirements mentioned", record.requirement_quotes, "Extracted sentences. This is not a complete application checklist unless the source text is complete."),
    quoteBlock("Registrations mentioned", record.registration_quotes, "Only phrases found in this description. Most federal grants also require SAM.gov. Confirm in the official announcement."),
    quoteBlock("Duration language", record.duration_quotes, "Extracted mentions of a project or award period. Not a structured duration field."),
    quoteBlock("Letter of intent or pre-application language", record.loi_quotes, "Extracted only. Absence of a quote does not mean no letter of intent is required."),
    beforeYouApply(record),
    scaffold(record),
    h("section", { class: "section" }, [
      h("h2", {}, "Eligibility"),
      record.applicant_types?.length
        ? h("ul", {}, record.applicant_types.map((item) => h("li", {}, item.label ? `${item.label} (${item.code})` : `Code ${item.code} — label not in the Grants.gov guide`)))
        : h("p", {}, "Applicant-type codes were not published."),
      h("p", { class: "prose" }, record.eligibility_text || "Additional eligibility text was not published."),
    ]),
    h("section", { class: "section" }, [
      h("h2", {}, "Official description"),
      h("p", { class: "prose" }, record.description || "Description was not published in the extract."),
    ]),
    topicPanel(record),
    inclusionPanel(record),
    flagsPanel(record),
    project ? matchPanel(record, project) : h("div", { class: "callout" }, "Save a project in the Builder to see an explainable fit on this page. The comparison stays in this browser."),
    related(record)
  );
  document.title = `${record.title} — Federal Research Grant Intelligence`;
}

function factGrid(record) {
  const funding = record.funding || {};
  const dates = record.dates || {};
  const rows = [
    ["Post date", prettyDate(dates.post)],
    ["Close date", dates.close ? `${prettyDate(dates.close)} (date only)` : "Not published"],
    ["Archive date", prettyDate(dates.archive)],
    ["Last updated in source", prettyDate(dates.last_updated)],
    ["Estimated award date", prettyDate(dates.estimated_award)],
    ["Award floor", money(funding.floor)],
    ["Award ceiling", funding.ceiling === 0 ? "Source published $0 — confirm the announcement; some agencies publish zero in this field" : money(funding.ceiling)],
    ["Estimated program total", money(funding.estimated_total)],
    ["Expected awards", funding.expected_awards == null ? "Not published" : String(funding.expected_awards)],
    ["Cost sharing", funding.cost_sharing == null ? "Not published" : funding.cost_sharing ? "Yes" : "No"],
    ["Instruments", (record.instruments || []).map((item) => item.label || item.code).join(", ") || "Not published"],
    ["Funding categories", (record.funding_categories || []).map((item) => item.label || item.code).join(", ") || "Not published"],
    ["Assistance listings", (record.aln || []).map((item) => item.number).join(", ") || "Not published"],
    ["Contact", contactLine(record.contact)],
    ["Last verified", verifiedLine(record.verified_at)],
    ["Source", record.source?.name || "Unknown"],
  ];
  return h("section", { class: "panel" }, [
    h("div", { class: "badge-row" }, [factBadge()]),
    h("h2", {}, "Published fields"),
    h("dl", { class: "facts" }, rows.flatMap(([label, value]) => [h("div", {}, [h("dt", {}, label), h("dd", {}, value)])])),
  ]);
}

function contactLine(contact = {}) {
  const parts = [contact.name, contact.email, contact.phone].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Not published";
}

function quoteBlock(title, quotes, note) {
  const section = h("section", { class: "section" }, [h("h2", {}, title), h("p", { class: "small muted" }, note)]);
  if (!quotes?.length) {
    section.append(h("p", {}, "No matching sentence was extracted. Read the official description rather than assuming the requirement is absent."));
    return section;
  }
  for (const quote of quotes) {
    section.append(h("blockquote", { class: "quote" }, [quote.text, h("footer", {}, "Extracted quote · not rewritten")]));
  }
  return section;
}

function topicPanel(record) {
  const section = h("section", { class: "panel" }, [h("div", { class: "badge-row" }, [derivedBadge()]), h("h2", {}, "Research topics")]);
  if (!record.topics?.length) {
    section.append(h("p", {}, "No topic term in the lexicon matched the official text. Left unclassified rather than guessed."));
    return section;
  }
  for (const topic of record.topics) {
    section.append(
      h("p", {}, [
        h("a", { href: `#/topic/${encodeURIComponent(topic.id)}` }, topic.label),
        topic.method === "keyword"
          ? ` — matched: ${(topic.matched_terms || []).join(", ") || "none recorded"}`
          : ` — ${topic.note || "Agency default, not a text match."}`,
      ])
    );
  }
  return section;
}

function inclusionPanel(record) {
  return h("section", { class: "panel" }, [
    derivedBadge(),
    h("h2", {}, "Why this record is in the research catalog"),
    ...(record.inclusion?.basis || []).map((basis) => h("p", {}, basis.label)),
    h("p", { class: "small muted" }, record.fact_boundary || ""),
  ]);
}

function flagsPanel(record) {
  const flags = record.flags || [];
  if (!flags.length) return h("span");
  return h("section", { class: "section" }, [
    h("h2", {}, "Field notes"),
    h("ul", {}, flags.map((flag) => h("li", {}, flag.replaceAll("_", " ")))),
  ]);
}

function matchPanel(record, project) {
  const match = scoreOpportunity(project, record, asOf());
  return h("section", { class: "panel" }, [
    derivedBadge(),
    h("h2", {}, `Fit with your saved project: ${match.fit == null ? "not scored" : match.fit}`),
    h("p", { class: "small" }, match.note),
    ...match.blockers.map((blocker) => h("p", { class: "callout warn" }, blocker)),
    ...match.components.map(componentView),
  ]);
}

function componentView(component) {
  return h("div", { class: "component" }, [
    h("strong", {}, `${component.label}${component.assessed ? ` · ${component.score}` : " · not assessed"}`),
    h("div", { class: "score", title: component.assessed ? `${component.score} of 100` : "Not assessed" }, [
      h("span", { style: `width:${component.assessed ? component.score : 0}%` }),
    ]),
    ...(component.evidence || []).map((line) => h("p", { class: "small" }, line)),
    ...(component.quotes || []).map((quote) => h("blockquote", { class: "quote" }, [quote.text, h("footer", {}, `Excerpt around “${quote.term}”`)])),
  ]);
}

function beforeYouApply(record) {
  const items = [
    `Official application page: ${record.urls?.official || "not published"}`,
    `Deadline: ${deadlineText(record)}`,
    `Cost sharing: ${record.funding?.cost_sharing == null ? "not published" : record.funding.cost_sharing ? "required in the source field" : "source field says no"}`,
  ];
  if (record.applicant_types?.length) {
    items.push(`Published applicant types: ${record.applicant_types.map((item) => item.label || item.code).join("; ")}.`);
  } else {
    items.push("Applicant types were not published. Do not assume you are eligible.");
  }
  return h("section", { class: "panel" }, [
    h("h2", {}, "What would block an application, from published fields"),
    h("ul", {}, items.map((item) => h("li", {}, item))),
    h("p", { class: "small muted" }, "A general federal requirement such as an active SAM.gov registration is an opportunity-specific fact only when the announcement text says so. Those sentences, if found, are in the registration quotes above."),
  ]);
}

function scaffold(record) {
  const quotes = [...(record.objective_quotes || []), ...(record.requirement_quotes || [])].slice(0, 6);
  const section = h("section", { class: "section" }, [
    h("div", { class: "badge-row" }, [derivedBadge()]),
    h("h2", {}, "Proposal scaffold"),
    h("p", { class: "small" }, "These prompts restate extracted sentences as questions. They are not a research idea, and they are not a project the agency requested unless the quote says so."),
  ]);
  if (!quotes.length) {
    section.append(h("p", {}, "No objective or requirement sentence was extracted. Use the official description rather than a generated project."));
    return section;
  }
  section.append(
    h(
      "ol",
      {},
      quotes.map((quote) =>
        h("li", {}, [
          h("p", {}, `Does the project directly address this published sentence?`),
          h("blockquote", { class: "quote" }, quote.text),
        ])
      )
    )
  );
  return section;
}

function related(record) {
  const topicIds = new Set((record.topics || []).map((topic) => topic.id));
  const actionable = { open: 0, upcoming: 1, open_program: 2, verification_required: 3, closed: 4 };
  const rows = state.opportunities
    .filter((other) => other.id !== record.id && (other.topics || []).some((topic) => topicIds.has(topic.id)))
    .map((other) => ({
      record: other,
      shared: (other.topics || []).filter((topic) => topicIds.has(topic.id)).length,
    }))
    .sort((a, b) => b.shared - a.shared || (actionable[a.record.status] ?? 9) - (actionable[b.record.status] ?? 9) || a.record.title.localeCompare(b.record.title))
    .slice(0, 4)
    .map((item) => item.record);
  if (!rows.length) return h("span");
  return h("section", { class: "section" }, [
    h("h2", {}, "Other catalog records with a shared derived topic"),
    h("div", { class: "cards" }, rows.map(card)),
  ]);
}

function renderResearch() {
  setNav("research");
  clear(view);
  const topics = state.aggregates?.topics || [];
  view.append(
    pageHead(
      "Research explorer",
      "What areas show up in current funding text?",
      "Topics are keyword classifications of official titles and descriptions. They are not an official federal taxonomy and they are not a finding that a scientific gap exists."
    ),
    h("div", { class: "callout analysis" }, [
      derivedBadge(),
      h("p", {}, `${state.aggregates?.unclassified_current ?? "—"} current-feed records matched no topic term and stay unclassified.`),
      h("p", { class: "small" }, state.aggregates?.funding_published?.warning || ""),
    ]),
    h("div", { class: "grid-2" }, topics.slice(0, 24).map(topicCard))
  );
}

function topicCard(topic) {
  return h("a", { class: "card", href: `#/topic/${encodeURIComponent(topic.id)}` }, [
    h("h3", {}, topic.label),
    h("p", { class: "meta-row" }, `${topic.open} open · ${topic.upcoming} upcoming · ${topic.open_program} programs · ${topic.agency_count} agencies`),
    h("p", { class: "small muted" }, "Derived classification"),
  ]);
}

function renderTopic(id) {
  setNav("research");
  const topic = (state.aggregates?.topics || []).find((item) => item.id === id);
  const rows = state.opportunities.filter((record) => (record.topics || []).some((item) => item.id === id));
  clear(view);
  if (!topic && !rows.length) {
    view.append(
      pageHead("Derived topic", "That topic is not in this catalog", "Topics are generated from the current catalog. This one is not in it, so there is nothing to show."),
      h("p", { class: "muted" }, `No record in the published catalog carries the topic id "${id}".`),
      h("p", {}, h("a", { href: "#/research" }, "Back to the research explorer"))
    );
    return;
  }
  view.append(
    pageHead("Derived topic", topic?.label || id, "Shown because the official text matched a listed term, or because a labeled agency default applied."),
    h("div", { class: "callout analysis" }, topic ? `${topic.open} open, ${topic.upcoming} upcoming, ${topic.agency_count} agencies in this catalog. This is not an official funding total.` : "This topic is not in the current aggregate file."),
    h("div", { class: "cards" }, rows.slice(0, 30).map(card))
  );
  const awardHits = state.awards.filter((award) => (award.topics || []).some((item) => item.id === id)).slice(0, 8);
  if (awardHits.length) {
    view.append(h("h2", {}, "Historical awards in this catalog with the same derived topic"), h("p", { class: "small muted" }, "These are funded projects from the covered award samples, not evidence of a gap and not a template."), h("div", { class: "cards" }, awardHits.map(awardCard)));
  }
}

function renderAgencies() {
  setNav("agencies");
  clear(view);
  const rows = state.aggregates?.agencies || [];
  view.append(
    pageHead("Agency explorer", "Where is the current research funding posted?", "Counts are catalog counts. A sum of estimated totals includes only records that published one."),
    h("div", { class: "panel" }, [
      h("table", {}, [
        h("thead", {}, h("tr", {}, ["Agency", "Open", "Upcoming", "Programs", "Median published ceiling", "Sum of published estimated totals"].map((label) => h("th", {}, label)))),
        h("tbody", {}, rows.map((row) =>
          h("tr", {}, [
            h("td", {}, h("a", { href: `#/agency/${encodeURIComponent(row.code)}` }, row.grouping_label || row.source_name_most_common || row.code)),
            h("td", {}, String(row.open)),
            h("td", {}, String(row.upcoming)),
            h("td", {}, String(row.open_program)),
            h("td", {}, row.median_published_ceiling == null ? "Not published" : money(row.median_published_ceiling)),
            h("td", {}, row.sum_published_estimated_totals == null ? "None published" : money(row.sum_published_estimated_totals)),
          ])
        )),
      ]),
      h("p", { class: "small muted" }, "Median and sum are derived and omit records with a blank amount. Do not read the sum as money available to one applicant."),
    ])
  );
}

function renderAgency(code) {
  setNav("agencies");
  const agency = (state.aggregates?.agencies || []).find((row) => row.code === code);
  const rows = state.opportunities.filter((record) => record.top_agency_code === code || record.agency_code === code);
  const awards = state.awards.filter((award) => award.agency === code || (award.agency_name || "").toLowerCase().includes((agency?.grouping_label || code).toLowerCase())).slice(0, 8);
  clear(view);
  if (!agency && !rows.length) {
    view.append(
      pageHead("Agency", "That agency is not in this catalog", "Agency codes come from the published records. This one is not among them."),
      h("p", { class: "muted" }, `No record in the published catalog uses the agency code "${code}".`),
      h("p", {}, h("a", { href: "#/agencies" }, "Back to the agency explorer"))
    );
    return;
  }
  view.append(
    pageHead(code, agency?.grouping_label || agency?.source_name_most_common || code, "Left side is what the catalog shows they are soliciting. Right side is only the historical awards this catalog actually holds."),
    h("div", { class: "grid-2" }, [
      h("section", { class: "panel" }, [h("h2", {}, "What is posted"), h("p", { class: "small" }, `${rows.filter((r) => r.status === "open").length} open in this catalog.`), h("div", { class: "cards" }, rows.filter((r) => r.status === "open" || r.status === "upcoming").slice(0, 6).map(card))]),
      h("section", { class: "panel" }, [
        h("h2", {}, "What this catalog shows was funded"),
        h("p", { class: "small muted" }, "If this list is empty, the historical sources did not return a matching sample. That is not evidence the agency has never funded the area."),
        awards.length ? h("div", { class: "cards" }, awards.map(awardCard)) : h("p", {}, "No matching historical award in the current sample."),
      ]),
    ])
  );
}

function renderFinder() {
  setNav("finder");
  const rows = state.aggregates?.multi_agency_topics || [];
  clear(view);
  view.append(
    pageHead("Opportunity finder", "Where more than one agency is posting related work", "A shared derived topic is a lead, not a conclusion that the programs can be combined or that a gap exists."),
    h("div", { class: "callout analysis" }, [derivedBadge(), " Multi-agency means at least two top-level agency codes and at least two open or upcoming records in this catalog."]),
    h("div", { class: "grid-2" }, rows.map(topicCard))
  );
}

function renderBuilder() {
  setNav("build");
  const saved = loadProject() || { title: "", summary: "", keywords: "", applicantTypes: [], budget: "", topics: [] };
  clear(view);
  view.append(
    pageHead(
      "Project builder",
      "Which open opportunities fit a project you can describe?",
      "The comparison runs in this browser. Notes are stored locally and are not sent to a server. The score is fit, not the chance of an award."
    )
  );
  const form = h("form", {
    class: "panel",
    onsubmit: (event) => {
      event.preventDefault();
      const data = new FormData(event.target);
      const project = {
        title: String(data.get("title") || ""),
        summary: String(data.get("summary") || ""),
        keywords: String(data.get("keywords") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        applicantTypes: data.getAll("applicant"),
        budget: data.get("budget") ? Number(data.get("budget")) : "",
        topics: data.getAll("topic"),
      };
      saveProject(project);
      renderBuilderResults(project);
    },
  });
  form.append(labeled("Project title", h("input", { name: "title", value: saved.title || "" })));
  form.append(labeled("What you want to investigate", h("textarea", { name: "summary" }, saved.summary || "")));
  form.append(labeled("Extra keywords, comma separated", h("input", { name: "keywords", value: (saved.keywords || []).join(", ") })));
  form.append(labeled("Budget you would request, dollars", h("input", { name: "budget", type: "number", min: "0", value: saved.budget || "" })));
  form.append(h("p", { class: "kicker" }, "Applicant type"));
  for (const item of state.codes?.applicant_types || []) {
    const checked = (saved.applicantTypes || []).includes(item.code);
    form.append(
      h("label", { class: "check" }, [
        h("input", { type: "checkbox", name: "applicant", value: item.code, checked: checked || null }),
        `${item.label}`,
      ])
    );
  }
  form.append(h("div", { class: "button-row" }, [h("button", { class: "primary", type: "submit" }, "Find documented fits"), h("button", { class: "secondary", type: "button", onclick: () => { localStorage.removeItem(STORE_KEY); render(); } }, "Clear saved project")]));
  view.append(form, h("div", { id: "matches" }));
  if (saved.summary || saved.title) renderBuilderResults(saved);
}

function renderBuilderResults(project) {
  const host = document.querySelector("#matches");
  if (!host) return;
  clear(host);
  const pool = state.opportunities.filter((record) => ["open", "upcoming", "open_program", "verification_required"].includes(record.status));
  const ranked = rankMatches(
    { ...project, keywords: project.keywords || [], topics: project.topics || [] },
    pool,
    asOf()
  ).slice(0, 12);
  host.append(h("h2", {}, "Strongest documented fits"), h("p", { class: "small muted" }, "Sorted with blockers after compatible records. Each score shows its evidence. This is not a ranking of likelihood of award."));
  if (!project.summary && !project.title && !(project.keywords || []).length) {
    host.append(h("p", {}, "Add a description to assess research alignment."));
  }
  host.append(
    h(
      "div",
      { class: "cards" },
      ranked.map(({ opportunity, match }) =>
        h("article", { class: `card ${opportunity.status}` }, [
          h("div", { class: "badge-row" }, [statusBadge(opportunity.status), h("span", { class: "badge derived" }, match.fit == null ? "Fit not scored" : `Fit ${match.fit}`)]),
          h("h3", {}, h("a", { href: `#/opportunity/${encodeURIComponent(opportunity.id)}` }, opportunity.title)),
          h("p", { class: "meta-row" }, opportunity.agency_name || ""),
          ...match.blockers.map((blocker) => h("p", { class: "small" }, blocker)),
          ...match.components.filter((item) => item.assessed).map((item) => h("p", { class: "small" }, `${item.label}: ${item.score}. ${item.evidence[0] || ""}`)),
          h("p", { class: "small muted" }, `Evidence strength ${match.evidence_strength.score} — ${match.evidence_strength.note}`),
        ])
      )
    )
  );
}

const AWARD_SORT_OPTIONS = [
  ["amount-desc", "Amount — largest first"],
  ["amount", "Amount — smallest first"],
  ["date-desc", "Start date — newest first"],
  ["date", "Start date — oldest first"],
  ["agency", "Agency — A to Z"],
  ["title", "Title — A to Z"],
];

/**
 * Historical funding explorer.
 *
 * Rows come from the capped NSF, NIH, and USAspending pulls the pipeline
 * recorded. Searching them narrows a sample; it does not make the sample a
 * census, so the coverage notes stay on the page above the results.
 */
function renderAwards() {
  setNav("awards");
  clear(view);
  const { params } = route();
  const sources = (state.meta?.sources || []).filter((source) => ["nsf_awards_api", "nih_reporter", "usaspending"].includes(source.id));
  const pool = [...state.awards, ...state.obligations];
  const { rows, amount_excluded_missing_amount } = filterAwards(pool, params);
  const sorted = sortAwards(rows, params.get("sort") || "amount-desc");
  const slice = paginate(sorted, params.get("page"), PAGE_SIZE);

  view.append(
    pageHead(
      "Historical funding",
      "What was funded is not the same as what is being solicited.",
      "Award rows below are samples unless a source says its pull was exhausted. Do not add the amounts and call the result an agency budget."
    ),
    ...sources.map((source) =>
      h("div", { class: "callout" }, [
        h("strong", {}, source.name || source.id),
        h("p", {}, source.coverage || source.error || "No coverage note."),
        h("p", { class: "small" }, `Status: ${source.status || "unknown"} · records in catalog: ${source.count ?? "—"}${source.pages ? ` · pages pulled: ${source.pages}${source.exhausted ? " (exhausted)" : " (capped)"}` : ""}`),
        source.url ? externalLink(source.url, "Source") : null,
      ])
    )
  );

  if (!pool.length) {
    view.append(h("p", { class: "muted" }, "No historical award rows in this catalog. The award sources failed or were skipped in the last refresh; see the verification page."));
    return;
  }

  const topicIds = new Set();
  for (const row of pool) for (const topic of row.topics || []) topicIds.add(topic);
  const topicLabels = new Map((state.aggregates?.topics || []).map((topic) => [topic.id, topic.label]));

  const form = h("form", {
    class: "panel filters award-filters",
    onsubmit: (event) => {
      event.preventDefault();
      const data = new FormData(event.target);
      const next = new URLSearchParams();
      for (const [key, value] of data.entries()) {
        if (String(value).trim()) next.set(key, String(value).trim());
      }
      go(`/awards?${next.toString()}`);
    },
  });
  form.append(h("h2", {}, "Search the award sample"));
  form.append(labeled("Search", h("input", { id: "aq", name: "q", type: "search", value: params.get("q") || "", placeholder: "Title, awardee, PI, program, abstract" })));
  form.append(labeled("Record type", select("kind", params.get("kind"), [["", "All rows"], ["award", "Historical awards"], ["obligation", "USAspending obligations"]])));
  form.append(
    labeled(
      "Agency as recorded",
      select("agency", params.get("agency"), [["", "Any"], ...awardAgencyOptions(pool)])
    )
  );
  form.append(
    labeled(
      "Derived topic",
      select(
        "topic",
        params.get("topic"),
        [["", "Any"], ...[...topicIds].sort().map((id) => [id, topicLabels.get(id) || id])]
      )
    )
  );
  form.append(labeled("Awardee state", select("state", params.get("state"), [["", "Any"], ...awardStateOptions(pool)])));
  form.append(
    labeled("Source", select("source", params.get("source"), [["", "Any"], ...[...new Set(pool.map((row) => (row.source || {}).id).filter(Boolean))].sort().map((id) => [id, id])]))
  );
  form.append(labeled("Amount at least", h("input", { name: "min", type: "number", min: "0", value: params.get("min") || "" })));
  form.append(labeled("Sort", select("sort", params.get("sort") || "amount-desc", AWARD_SORT_OPTIONS)));
  form.append(h("div", { class: "button-row" }, [h("button", { class: "primary", type: "submit" }, "Apply"), h("a", { class: "button secondary", href: "#/awards" }, "Reset")]));

  const notes = [];
  if (amount_excluded_missing_amount) {
    notes.push(`${amount_excluded_missing_amount} row(s) matched the other filters but published no amount.`);
  }
  if (params.get("topic") || params.get("state")) {
    notes.push("USAspending obligation rows carry no derived topic and no awardee state in this catalog, so a topic or state filter leaves them out.");
  }

  view.append(
    h("div", { class: "layout" }, [
      form,
      h("div", {}, [
        h("div", { class: "section-head" }, [
          h("p", { class: "result-count" }, `${sorted.length} of ${pool.length} rows`),
          h("button", { class: "button secondary", type: "button", onclick: () => exportAwardCsv(sorted) }, "Download CSV"),
        ]),
        notes.length ? h("p", { class: "small muted filter-note" }, notes.join(" ")) : h("span"),
        slice.clamped ? h("p", { class: "small muted filter-note" }, `That page is past the end of these results. Showing page ${slice.page} instead.`) : h("span"),
        h("p", { class: "small muted" }, "These are funded projects and reported obligations, not open solicitations. A row appearing here is not evidence that the same project would be funded again."),
        h("div", { class: "cards" }, slice.rows.map((row) => (row.record_type === "obligation" ? obligationCard(row) : awardCard(row)))),
        awardPager(params, slice),
      ]),
    ])
  );
}

function awardPager(params, slice) {
  if (slice.pages === 1) return h("span");
  const previous = new URLSearchParams(params);
  const next = new URLSearchParams(params);
  previous.set("page", String(slice.page - 1));
  next.set("page", String(slice.page + 1));
  return h("div", { class: "pager" }, [
    slice.page > 1 ? h("a", { class: "button secondary", href: `#/awards?${previous}` }, "Previous") : null,
    h("span", {}, `Page ${slice.page} of ${slice.pages}`),
    slice.page < slice.pages ? h("a", { class: "button secondary", href: `#/awards?${next}` }, "Next") : null,
  ]);
}

function exportAwardCsv(rows) {
  const header = ["record_type", "id", "title", "agency", "agency_name", "awardee", "state", "pi", "amount", "start_date", "end_date", "program", "derived_topics", "official_url"];
  const lines = [header.join(",")];
  for (const row of rows) {
    lines.push(
      [
        row.record_type,
        row.id || row.award_id,
        row.title,
        row.agency || row.awarding_agency,
        row.agency_name || row.awarding_sub_agency,
        row.awardee_name || row.recipient_name,
        row.awardee_state,
        row.pi_name,
        awardAmount(row),
        row.start_date,
        row.end_date,
        row.program,
        (row.topics || []).map((topic) => topic.label).join("|"),
        (row.urls || {}).official,
      ]
        .map(csvCell)
        .join(",")
    );
  }
  downloadCsv(lines, "research-award-sample.csv");
}

function awardCard(award) {
  return h("article", { class: "card" }, [
    h("div", { class: "badge-row" }, [h("span", { class: "badge fact" }, "Historical award"), award.sample_label ? h("span", { class: "badge derived" }, award.sample_label.replaceAll("_", " ")) : null]),
    h("h3", {}, award.title),
    h("p", { class: "meta-row" }, [award.agency_name || award.agency || "", award.awardee_name ? ` · ${award.awardee_name}` : "", award.awardee_state ? `, ${award.awardee_state}` : ""]),
    h("p", { class: "money" }, money(award.amount_obligated)),
    h("p", { class: "small" }, [prettyDate(award.start_date), " – ", prettyDate(award.end_date)]),
    externalLink(award.urls?.official, "Official award page"),
  ]);
}

function obligationCard(row) {
  return h("article", { class: "card" }, [
    h("span", { class: "badge fact" }, "Obligation"),
    h("h3", {}, row.recipient_name || row.award_id || "Recipient not named"),
    h("p", { class: "meta-row" }, [row.awarding_agency || "", row.cfda ? ` · ALN ${row.cfda}` : ""]),
    h("p", { class: "money" }, money(row.amount)),
    h("p", { class: "small prose" }, row.description || "Description not published."),
    externalLink(row.urls?.official, "USAspending record"),
  ]);
}

/**
 * What changed between the previous published catalog and this one.
 *
 * "Removed" is an absence from the new extract, not a documented cancellation.
 * The pipeline caps the changed list, so the full count is shown separately.
 */
function renderChanges() {
  setNav("changes");
  clear(view);
  const changes = state.changes;
  view.append(
    pageHead(
      "What changed",
      "What is different since the previous catalog",
      `Compared against the catalog this refresh replaced. Built ${verifiedLine(state.meta?.generated_at)}.`
    )
  );

  if (!changes) {
    view.append(h("p", { class: "muted" }, "No changes file is published yet."));
    return;
  }
  if (!changes.compared_to_previous_catalog) {
    view.append(
      h("div", { class: "callout" }, [
        h("p", {}, "This is the first catalog retained by this pipeline, so there is no previous catalog to compare against."),
        h("p", { class: "small" }, changes.note || ""),
      ])
    );
    return;
  }

  const changedRows = changes.changed || [];
  const changedTotal = changes.changed_count ?? changedRows.length;
  const truncated = changedTotal > changedRows.length;

  view.append(
    h("div", { class: "stats" }, [
      stat(String((changes.new_ids || []).length), "New to this catalog"),
      stat(String((changes.newly_closed || []).length), "Newly closed"),
      stat(String(changedTotal), "Records with a changed field"),
      stat(String((changes.removed_ids || []).length), "Absent from the new extract"),
    ]),
    h("div", { class: "callout analysis" }, [
      derivedBadge(),
      h("p", { class: "small" }, changes.note || ""),
      h("p", { class: "small muted" }, "A record can be new to this catalog and old to the agency. Use the published post date, not first-seen time, to judge how new an announcement is."),
    ])
  );

  view.append(changeSection("Newly closed", changes.newly_closed || [], "These records were open, upcoming, or a standing program in the previous catalog and now carry a published close date before the as-of date."));
  view.append(changeSection("New to this catalog", changes.new_ids || [], "Not present in the previous catalog file. That is when this pipeline first carried the record, which is not always when the agency posted it."));

  const changedSection = h("section", { class: "section" }, [
    h("h2", {}, "Fields that changed"),
    h("p", { class: "small muted" }, "Only status, close date, post date, ceiling, estimated total, title, and applicant-type codes are tracked. A record can change in another field without appearing here."),
  ]);
  if (!changedRows.length) {
    changedSection.append(h("p", { class: "muted" }, "No tracked field changed between the two catalogs."));
  } else {
    if (truncated) {
      changedSection.append(h("p", { class: "small" }, `Showing the first ${changedRows.length} of ${changedTotal} changed records. The pipeline caps this list to keep the published file small.`));
    }
    changedSection.append(
      h("table", { class: "changes-table" }, [
        h("thead", {}, h("tr", {}, ["Record", "Changed fields", "Status now", "Status before"].map((label) => h("th", {}, label)))),
        h("tbody", {}, changedRows.slice(0, 200).map((row) =>
          h("tr", {}, [
            h("td", {}, h("a", { href: `#/opportunity/${encodeURIComponent(row.id)}` }, (state.byId.get(row.id) || {}).title || row.id)),
            h("td", {}, (row.fields || []).join(", ")),
            h("td", {}, STATUS_LABEL[row.status] || row.status || ""),
            h("td", {}, STATUS_LABEL[row.previous_status] || row.previous_status || ""),
          ])
        )),
      ])
    );
  }
  view.append(changedSection);

  const removed = changes.removed_ids || [];
  const removedSection = h("section", { class: "section" }, [
    h("h2", {}, "Absent from the new extract"),
    h("p", { class: "small muted" }, "The id is no longer in the published catalog. That happens when an opportunity leaves the extract, and it is not a documented cancellation. Check the official page before treating it as canceled."),
  ]);
  if (!removed.length) {
    removedSection.append(h("p", { class: "muted" }, "No ids dropped out of the catalog in this refresh."));
  } else {
    removedSection.append(h("ul", {}, removed.slice(0, 200).map((id) => h("li", { class: "mono small" }, id))));
  }
  view.append(removedSection);
  view.append(h("p", { class: "small" }, h("a", { href: "#/sources" }, "How this catalog is verified")));
}

function changeSection(title, ids, note) {
  const section = h("section", { class: "section" }, [h("h2", {}, `${title} (${ids.length})`), h("p", { class: "small muted" }, note)]);
  if (!ids.length) {
    section.append(h("p", { class: "muted" }, "None in this refresh."));
    return section;
  }
  const rows = ids.map((id) => state.byId.get(id)).filter(Boolean);
  if (!rows.length) {
    section.append(h("ul", {}, ids.slice(0, 200).map((id) => h("li", { class: "mono small" }, id))));
    return section;
  }
  section.append(h("div", { class: "cards" }, rows.slice(0, 12).map(card)));
  if (rows.length > 12) {
    section.append(h("p", { class: "small muted" }, `Showing 12 of ${rows.length}.`));
  }
  return section;
}

function renderSources() {
  setNav("sources");
  clear(view);
  const meta = state.meta;
  if (!meta) {
    emptyCatalog();
    return;
  }
  const coverage = meta.field_coverage || {};
  view.append(
    pageHead("Verification", "Where this catalog came from, and what it does not know.", `As-of date ${meta.as_of_date || "unknown"} (${meta.timezone || ""}). Built ${verifiedLine(meta.generated_at)}.`),
    h("div", { class: "callout fact" }, meta.no_hallucination || "Missing values stay blank."),
    h("h2", {}, "Sources"),
    h("div", { class: "cards" }, (meta.sources || []).map((source) =>
      h("article", { class: "card" }, [
        h("h3", {}, source.name || source.id),
        h("p", { class: "meta-row" }, source.status || "recorded"),
        source.url || source.file_url ? externalLink(source.url || source.file_url, "Open source") : null,
        source.file_name ? h("p", { class: "mono small" }, source.file_name) : null,
        source.coverage ? h("p", { class: "small" }, source.coverage) : null,
        source.error ? h("p", { class: "small" }, `Error: ${source.error}`) : null,
      ])
    )),
    h("h2", {}, "Field coverage"),
    h("div", { class: "panel" }, Object.entries(coverage).map(([key, value]) =>
      h("div", { class: "component" }, [
        h("strong", {}, `${key.replaceAll("_", " ")} · ${value.percent}%`),
        h("div", { class: "score evidence" }, h("span", { style: `width:${value.percent}%` })),
        h("p", { class: "small muted" }, `${value.count} of ${value.of}`),
      ])
    )),
    h("h2", {}, "Cross-check"),
    crossCheckPanel(meta.cross_check),
    h("h2", {}, "Scope"),
    h("pre", { class: "panel small prose" }, JSON.stringify(meta.scope_stats || {}, null, 2)),
    h("h2", {}, "Limitations"),
    h("ul", {}, (meta.limitations || []).map((item) => h("li", {}, item))),
    h("h2", {}, "Reproduce"),
    h("p", { class: "mono small" }, "python -m pipeline.refresh"),
    h("p", { class: "small" }, "The daily GitHub Actions workflow downloads the Grants.gov extract, normalizes it, and commits docs/data. Hand-edited grants are not part of the design.")
  );
}

function crossCheckPanel(check) {
  if (!check) return h("p", {}, "No cross-check recorded.");
  const spot = check.spot_check;
  return h("div", { class: "panel" }, [
    h("p", {}, `Status: ${check.status || "unknown"}`),
    h("p", { class: "small" }, check.interpretation || check.error || check.reason || ""),
    check.posted_or_forecasted_ST ? h("p", {}, `search2 ST posted|forecasted hitCount: ${check.posted_or_forecasted_ST.hit_count ?? "unavailable"}`) : null,
    check.catalog_open_or_upcoming_ST != null ? h("p", {}, `Catalog open or upcoming ST: ${check.catalog_open_or_upcoming_ST}`) : null,
    spot ? h("p", {}, `Detail spot check: ${spot.status || "unknown"}, mismatches ${spot.mismatch_count ?? "—"}.`) : null,
    spot?.results
      ? h("ul", {}, spot.results.map((row) => h("li", { class: "small" }, `${row.id}: ${row.status}${row.mismatches?.length ? ` mismatch ${row.mismatches.join(", ")}` : ""}`)))
      : null,
  ]);
}

function render() {
  document.title = "Federal Research Grant Intelligence";
  if (!state.ready) return;
  const { parts } = route();
  const name = parts[0] || "feed";
  if (!state.opportunities.length && !["sources", "build", "awards", "changes"].includes(name)) {
    emptyCatalog();
    return;
  }
  if (name === "explore") renderExplore();
  else if (name === "opportunity") renderOpportunity(decodeURIComponent(parts[1] || ""));
  else if (name === "research") renderResearch();
  else if (name === "topic") renderTopic(decodeURIComponent(parts[1] || ""));
  else if (name === "agencies") renderAgencies();
  else if (name === "agency") renderAgency(decodeURIComponent(parts[1] || ""));
  else if (name === "finder") renderFinder();
  else if (name === "build") renderBuilder();
  else if (name === "awards") renderAwards();
  else if (name === "changes") renderChanges();
  else if (name === "sources") renderSources();
  else renderFeed();
  view.focus({ preventScroll: true });
}

loadCatalog();
