/**
 * Drives the real docs/js/app.js in a DOM against the published catalog.
 *
 * These are the checks that unit tests on pure functions cannot make: that the
 * routes render, that a feed count agrees with the explorer it links to, that
 * a sort actually reorders the rendered cards, and that the pages a user needs
 * to answer "can I apply?" exist and show their sources.
 *
 * The catalog under docs/data is generated. If the pipeline changes the schema
 * these tests fail, which is the point.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const here = dirname(fileURLToPath(import.meta.url));
const docs = join(here, "..", "docs");

const meta = JSON.parse(readFileSync(join(docs, "data", "meta.json"), "utf8"));
const opportunities = JSON.parse(readFileSync(join(docs, "data", "opportunities.json"), "utf8")).opportunities;

const errors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (error) => errors.push(error.message));

const dom = new JSDOM(readFileSync(join(docs, "index.html"), "utf8"), {
  url: "https://example.test/#/feed",
  pretendToBeVisual: true,
  virtualConsole,
});
const { window } = dom;

for (const key of [
  "document",
  "location",
  "localStorage",
  "navigator",
  "Node",
  "Element",
  "HTMLElement",
  "Blob",
  "URL",
  "URLSearchParams",
  "FormData",
  "Event",
  "HashChangeEvent",
  "CustomEvent",
  "getComputedStyle",
]) {
  if (window[key] === undefined) continue;
  Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true });
}
Object.defineProperty(globalThis, "window", { value: window, configurable: true, writable: true });
globalThis.addEventListener = window.addEventListener.bind(window);
globalThis.fetch = async (url) => {
  const name = String(url).replace(/^data\//, "").split("?")[0];
  const body = readFileSync(join(docs, "data", name), "utf8");
  return { ok: true, status: 200, json: async () => JSON.parse(body), text: async () => body };
};

await import(pathToFileURL(join(docs, "js", "app.js")).href);
await new Promise((resolve) => setTimeout(resolve, 250));

/**
 * jsdom does not implement file downloads, so exercising the CSV button makes
 * it report "Not implemented: navigation to another Document" — asynchronously,
 * after the click handler returns. That is a jsdom gap, not an app defect.
 */
const unexpectedErrors = () => errors.filter((message) => !message.includes("Not implemented: navigation"));

const view = () => window.document.querySelector("#view");
const text = () => view().textContent.replace(/\s+/g, " ").trim();
const cards = () => [...view().querySelectorAll("article.card")];

async function go(hash) {
  window.location.hash = hash;
  window.dispatchEvent(new window.HashChangeEvent("hashchange", { newURL: window.location.href, oldURL: window.location.href }));
  await new Promise((resolve) => setTimeout(resolve, 120));
  return view();
}

function resultCount() {
  const node = view().querySelector(".result-count");
  assert.ok(node, "explorer did not render a result count");
  return Number(node.textContent.match(/\d+/)[0]);
}

function sectionCount(title) {
  const head = [...view().querySelectorAll(".section-head")].find((node) => node.textContent.includes(title));
  assert.ok(head, `feed has no section titled ${title}`);
  const match = head.textContent.match(/View (\d+)/);
  assert.ok(match, `section ${title} has no record count link`);
  return Number(match[1]);
}

test("the catalog loads from docs/data without a page error", () => {
  assert.deepEqual(unexpectedErrors(), [], "jsdom reported a page error");
  assert.ok(opportunities.length > 0, "the published catalog is empty");
  assert.equal(view().querySelectorAll(".stat").length, 4, "feed summary stats are missing");
  assert.match(window.document.querySelector("#verified-stamp").textContent, /Last verified/);
  assert.match(window.document.querySelector("#verified-stamp").textContent, /your time/, "the stamp must say whose timezone it shows");
});

test("the feed deadline count matches the explorer it links to", async () => {
  await go("#/feed");
  const feedCount = sectionCount("Closing within 21 days");
  await go("#/explore?status=open&closing=21&sort=close");
  assert.equal(resultCount(), feedCount, "the feed and the explorer disagree about how many opportunities close within 21 days");
});

test("a descending sort actually reorders the rendered cards", async () => {
  await go("#/explore?status=open&sort=title");
  const ascending = cards().map((card) => card.querySelector("h3").textContent.trim());
  await go("#/explore?status=open&sort=title-desc");
  const descending = cards().map((card) => card.querySelector("h3").textContent.trim());
  assert.ok(ascending.length > 1, "not enough open records to test sorting");
  assert.notEqual(ascending[0], descending[0], "title-desc rendered the same first card as title");
  assert.ok(ascending[0].localeCompare(descending[0]) < 0, "the first ascending title should sort before the first descending title");

  const closesFor = (sort) => {
    const hrefs = cards().map((card) => card.querySelector("h3 a").getAttribute("href"));
    return hrefs.map((href) => {
      const record = opportunities.find((item) => `#/opportunity/${encodeURIComponent(item.id)}` === href);
      assert.ok(record, `card links to an unknown record: ${href}`);
      return (record.dates || {}).close || "9999-99-99";
    });
  };
  await go("#/explore?status=open&sort=close");
  const soonest = closesFor("close");
  await go("#/explore?status=open&sort=close-desc");
  const latest = closesFor("close-desc");
  assert.notEqual(soonest[0], latest[0], "close-desc rendered the same first card as close");
  for (let index = 1; index < soonest.length; index += 1) {
    assert.ok(soonest[index - 1] <= soonest[index], "the deadline sort is not ascending");
    assert.ok(latest[index - 1] >= latest[index], "the reverse deadline sort is not descending");
  }
});

test("explorer search and filters narrow the published catalog", async () => {
  await go("#/explore");
  const all = resultCount();
  assert.equal(all, opportunities.length, "an unfiltered explorer should show every published record");

  await go("#/explore?q=quantum");
  const quantum = resultCount();
  assert.ok(quantum > 0 && quantum < all, "the quantum search returned an implausible count");
  for (const card of cards()) {
    const link = card.querySelector("h3 a").getAttribute("href");
    const record = opportunities.find((item) => `#/opportunity/${encodeURIComponent(item.id)}` === link);
    assert.ok(record, `card links to a record that is not in the catalog: ${link}`);
    const haystack = `${record.title} ${record.description} ${record.agency_name} ${(record.topics || []).map((t) => t.label).join(" ")}`.toLowerCase();
    assert.match(haystack, /quantum/, "a search result does not contain the search term");
  }

  await go("#/explore?status=open");
  const open = resultCount();
  const expectedOpen = opportunities.filter((record) => record.status === "open").length;
  assert.equal(open, expectedOpen, "the status filter count does not match the catalog");
});

test("an amount filter says how many records it could not evaluate", async () => {
  await go("#/explore?min=1000000");
  const published = opportunities.filter((record) => (record.funding || {}).ceiling != null).length;
  assert.ok(published < opportunities.length, "this check needs some records without a published ceiling");
  assert.match(text(), /published no award ceiling/, "the explorer did not explain the records the amount filter skipped");
});

test("the detail page shows published fields, the status basis, and the official source", async () => {
  const record = opportunities.find((item) => item.id.startsWith("gg-") && item.urls?.official);
  assert.ok(record, "no Grants.gov record to open");
  await go(`#/opportunity/${encodeURIComponent(record.id)}`);
  const body = text();
  assert.ok(body.includes(record.title), "the detail page does not show the record title");
  assert.match(body, /Published fields/);
  assert.match(body, /Last verified/);
  assert.match(body, /Why this record is in the research catalog/, "the inclusion basis is not shown");
  const official = [...view().querySelectorAll("a")].find((link) => link.href === record.urls.official);
  assert.ok(official, "the official source link is missing from the detail page");
  assert.equal(official.getAttribute("rel"), "noopener noreferrer");
});

test("the historical funding view can be searched and sorted", async () => {
  await go("#/awards");
  const all = resultCount();
  assert.ok(all > 0, "no historical rows are shown");
  assert.match(text(), /samples? unless a source says its pull was exhausted/i, "the sample warning disappeared");

  await go("#/awards?q=climate");
  const climate = resultCount();
  assert.ok(climate >= 0 && climate <= all, "award search returned an implausible count");
  assert.ok(view().querySelector(".filters"), "the award filter panel is missing");

  await go("#/awards?sort=amount-desc");
  const firstAmount = cards()[0]?.querySelector(".money")?.textContent || "";
  await go("#/awards?sort=amount");
  const lastAmount = cards()[0]?.querySelector(".money")?.textContent || "";
  assert.notEqual(firstAmount, lastAmount, "the award sort did not change the first row");

  await go("#/awards?kind=obligation");
  for (const card of cards()) {
    assert.match(card.textContent, /Obligation/, "a non-obligation row appeared under the obligation filter");
  }
});

test("the changes view reports what moved between catalogs", async () => {
  await go("#/changes");
  assert.match(text(), /What is different since the previous catalog/);
  assert.match(text(), /New to this catalog/);
  assert.match(text(), /Newly closed/);
  assert.match(text(), /Absent from the new extract/);
  assert.match(text(), /not a documented cancellation/i, "the removed-id caveat is missing");
});

test("the verification page shows sources, coverage, and the cross-check", async () => {
  await go("#/sources");
  assert.match(text(), /Where this catalog came from/);
  assert.match(text(), /Field coverage/);
  assert.match(text(), /Cross-check/);
  assert.match(text(), /Limitations/);
  assert.ok(text().includes(meta.as_of_date), "the as-of date is not displayed");
  const sourceLinks = [...view().querySelectorAll("a")].filter((link) => /^https?:/.test(link.href)).map((link) => link.hostname);
  assert.ok(sourceLinks.length > 0, "no external source links are rendered");
  // Grants.gov publishes the daily extract from its own S3 bucket, which is
  // linked from https://www.grants.gov/xml-extract. It is official but it is
  // not a .gov hostname, so the allowlist names it explicitly.
  const allowlisted = (host) =>
    host.endsWith(".gov") ||
    host.endsWith(".mil") ||
    host.endsWith("github.com") ||
    host === "prod-grants-gov-chatbot.s3.amazonaws.com";
  assert.ok(
    sourceLinks.every(allowlisted),
    `unexpected external host in the sources view: ${sourceLinks.filter((host) => !allowlisted(host)).join(", ")}`
  );
});

test("the project builder returns explainable fits and never a win probability", async () => {
  await go("#/build");
  const form = view().querySelector("form");
  assert.ok(form, "the builder form is missing");
  form.querySelector('[name="title"]').value = "Quantum sensing for groundwater monitoring";
  form.querySelector('[name="summary"]').value = "We will develop quantum sensing instruments to monitor groundwater levels and quality.";
  form.querySelector('[name="budget"]').value = "400000";
  const firstApplicant = form.querySelector('[name="applicant"]');
  if (firstApplicant) firstApplicant.checked = true;
  form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 200));

  const results = window.document.querySelector("#matches");
  assert.ok(results, "the builder produced no results container");
  assert.match(results.textContent, /Strongest documented fits/);
  assert.match(results.textContent, /not a ranking of likelihood of award/, "the builder must state that fit is not a win probability");
  assert.doesNotMatch(results.textContent, /probability of (winning|award)/i);
  const scored = [...results.querySelectorAll(".badge.derived")].map((badge) => badge.textContent);
  assert.ok(scored.some((label) => label.startsWith("Fit ")), "no fit score was rendered");
});

test("the CSV export quotes cells and neutralizes formula prefixes", async () => {
  const captured = [];
  const errorsBefore = errors.length;
  const original = window.URL.createObjectURL;
  window.URL.createObjectURL = (blob) => {
    captured.push(blob);
    return "blob:stub";
  };
  window.URL.revokeObjectURL = () => {};
  try {
    await go("#/explore?status=open&sort=close");
    const button = [...view().querySelectorAll("button")].find((node) => node.textContent.includes("Download CSV"));
    assert.ok(button, "the explorer has no CSV export button");
    button.dispatchEvent(new window.Event("click", { bubbles: true }));
    assert.equal(captured.length, 1, "the export produced no file");
    const text = await captured[0].text();
    const lines = text.split("\n");
    assert.equal(
      lines[0],
      "id,title,number,agency,status,post_date,close_date,ceiling,floor,estimated_total,official_url,derived_topics"
    );
    assert.ok(lines.length > 1, "the export has no data rows");
    assert.equal(lines.length, resultCount() + 1, "the export should contain every filtered record plus a header row");
    assert.ok(lines.length < opportunities.length + 1, "the status filter was ignored by the export");
    assert.match(lines[1], /^"gg-|^"nsf-program-/, "data rows should be quoted");
    for (const line of lines.slice(1)) {
      for (const cell of line.split('","')) {
        assert.doesNotMatch(cell.replace(/^"/, ""), /^[=+\-@]/, "a cell could execute as a spreadsheet formula");
      }
    }
    assert.deepEqual(
      errors.slice(errorsBefore).filter((message) => !message.includes("Not implemented: navigation")),
      [],
      "the CSV export produced a page error"
    );
  } finally {
    window.URL.createObjectURL = original;
  }
});

test("a page past the end shows records instead of a dead end", async () => {
  await go("#/explore?page=9999");
  assert.ok(cards().length > 0, "an out-of-range page rendered no records");
  assert.match(text(), /past the end of these results/, "the clamp is not explained to the user");
  const label = view().querySelector(".pager")?.textContent || "";
  assert.doesNotMatch(label, /Page 9999/, "the pager still claims the impossible page number");
});

test("unknown topic and agency routes say so instead of rendering an empty page", async () => {
  await go("#/topic/this-topic-does-not-exist");
  assert.match(text(), /That topic is not in this catalog/);
  assert.equal(cards().length, 0);
  await go("#/agency/ZZZZ");
  assert.match(text(), /That agency is not in this catalog/);
  await go("#/opportunity/not-a-real-id");
  assert.match(text(), /That opportunity is not in the catalog/);
});

test("every navigation link resolves to a rendered view", async () => {
  const links = [...window.document.querySelectorAll("#sitenav a")].map((link) => link.getAttribute("href"));
  assert.ok(links.length >= 8, "primary navigation is missing entries");
  for (const href of links) {
    await go(href);
    assert.ok(view().querySelector("h1"), `${href} rendered no heading`);
    assert.doesNotMatch(view().textContent, /is not in the catalog/, `${href} fell through to the missing-record view`);
  }
  assert.deepEqual(unexpectedErrors(), [], "navigation produced a page error");
});
