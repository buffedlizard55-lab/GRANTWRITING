# Federal Research Grant Intelligence Platform

Read this file before changing the project. The specification below is the source of truth for what we are building, why, the requirements, the limitations, and what is still unfinished. Do not treat the current code as correct only because it exists. Check what is live, what is derived, what failed, and what has not been verified.

## Current implementation status

Reviewed 2026-09-27 against the saved catalog snapshot with an as-of date of `2026-09-26` (America/New_York). The generated `docs/data/meta.json` is authoritative for the latest generation time, source file, exact counts, field coverage, source errors, and cross-check results; these values can change at every daily refresh.

### What the live catalog contains

- 1,286 research-relevant records: 718 open, 282 upcoming, 20 standing NSF programs (`open_program`), 251 closed, 15 `verification_required`. 1,300 historical award rows (1,000 NSF, 300 NIH) and 101 USAspending obligations.
- A posted synopsis with no close date is not labeled open if its last-updated or post date is more than 18 months before the as-of date. That caught a FY 2012 program still sitting in the active extract. Recently updated open-ended solicitations stay open, with the missing deadline flagged.
- **Changed 2026-09-27:** cancellation language no longer overrides a deadline that already passed. Re-running the new status rule over the published file moves exactly 5 records — Grants.gov ids `45902`, `52203`, `52285`, `55317`, `274975`, posted 2009–2015 — from `verification_required` to `archived`, and `_keep` then drops archived records, so they leave the feed at the next refresh. No other record changes status. Before this fix those five appeared under "Needs verification" on the feed, which presented 2009 solicitations as current intelligence.
- The extract contained 83,488 records (82,518 synopses, 970 forecasts). The platform's research-scope rules matched 34,585 of them; recency/status rules retained 1,266 Grants.gov records, then 20 NSF standing-program feed items were added. A NOFO/FOA label alone is not a research signal. The `meta.json` scope summary records aggregate exclusions; exclusion does not mean the opportunity is unofficial or definitively non-research.
- Field coverage on the published file: title, agency, post date, and official URL 100%; opportunity number, eligibility codes, cost sharing, and ALN about 98%; close date 93%; eligibility text 82%; estimated total 52%; award ceiling 40%; award floor 30%. Blank money fields stay blank. A stored `$0` means the source published zero.
- Known source-field conflict: Grants.gov opportunity `361931` publishes `$0` for both award floor and ceiling, while its additional eligibility text says requests over `$300,000` will not be considered. The detail view preserves the source fields, warns users to confirm a zero ceiling, and shows the full official description; do not infer a corrected structured ceiling.
- Saved cross-check against `https://api.grants.gov/v1/api/search2`: 1,536 posted or forecasted opportunities in all categories and 310 in category ST. The catalog has 295 open or upcoming ST rows, an absolute difference of 15 (4.8% of the API count); pipeline status is `ok` within its 15% discrepancy threshold. The recorded ID comparison lists 17 search2 ids absent from the catalog and 2 catalog ids absent from the returned search2 id set. Search2 can retain older forecast records; a difference is not automatically a parser error or a currently open opportunity. The saved `fetchOpportunity` spot check covers 5 records with 0 title, number, agency, or close-date mismatches. See `meta.json` for the compared ids and results.
- Historical files are samples, not censuses. The latest NSF Award Search API pull returned 1,000 unique rows (40 pages, capped and not exhausted). NIH RePORTER returned 300 and USAspending 101 in the saved snapshot; all three are partial. Do not sum these files and call the result total federal research funding. [NSF API guide](https://resources.research.gov/common/webapi/awardapisearch-v1.htm). NSF award pages use `https://www.nsf.gov/awardsearch/show-award/?AWD_ID={id}`.

### Fixed in this pass

Each of these was found by running the shipped code, not by reading it, and each now has a test.

- **The feed and the explorer disagreed about deadlines.** The feed counted "closing within 21 days" from the viewer's date while the explorer it linked to counted from the catalog as-of date. Measured before the fix: the feed said "View 114" and the linked explorer said "115 records". Both now use one reference date and `tests/ui.test.mjs` asserts the two numbers are equal.
- **Descending sorts silently did nothing.** `filtered()` computed a direction and passed it to `compareRecords(a, b, sort, direction)`, but that function only accepted three parameters, and any `-desc` key fell through to the deadline branch. Sorting by "title-desc" returned deadline order. Direction is now handled in `docs/js/catalog.js`, missing values sort last in both directions, and the explorer exposes ascending and descending options.
- **Records with no close date vanished from a deadline filter without a word.** They are now counted and reported: "N records published no close date and were left out of the deadline filter."
- **Amount filters silently dropped records with no published ceiling.** The count is now shown next to the results. The exclusion itself is unchanged and intentional — a blank ceiling is not zero.
- **"Last verified" did not say whose timezone it was showing.** The pipeline stores Eastern time with its offset; the browser re-renders it locally. The stamp and the detail page now label it "your time".
- **The bulk JSON files were published with indentation.** That was 22.5% of `opportunities.json` (9,363,962 → 7,255,125 bytes) and 16.4% of `awards.json`, downloaded on every page load and committed on every daily refresh. The three record files are now compact; the small files a person reads stay indented. `python -m pipeline.validate_published` still passes on the compact files.
- **Source URLs were handed straight to `href`.** They are official, but they are still external data. `safeHttpUrl` now refuses anything that is not http or https, and the detail page falls back to inert text.

### Added in this pass

- **Historical funding explorer** (`#/awards`). It was a hardcoded `slice(0, 20)`. The 1,401 award and obligation rows in the catalog can now be searched, filtered by record type, agency, derived topic, awardee state, source, and minimum amount, sorted by amount or date, paginated, and exported to CSV. The sample-coverage warnings stay on the page above the results.
- **Changes view** (`#/changes`), answering the specification's "what information changed since the last time I checked?". It lists newly closed records, records new to the catalog, which tracked fields changed on which records, and ids absent from the new extract — with the caveat that an absence is not a documented cancellation, and with the truncation shown when the pipeline capped the list.
- **`docs/js/catalog.js`**, a DOM-free module holding the filtering, sorting, deadline, and URL logic. It exists so that logic can be tested without a browser; `docs/js/app.js` imports it.
- **Browser-level tests.** `tests/ui.test.mjs` loads `docs/index.html` in jsdom, stubs `fetch` against the real `docs/data/`, imports the real `docs/js/app.js`, and drives all nine routes against the real catalog. It asserts feed/explorer count agreement, that a descending sort reorders rendered cards, that search results actually contain the search term, that every card links to a record that exists, that the CSV export quotes cells and neutralizes formula prefixes, that the builder states fit is not a win probability, and that no external host outside `.gov`/`.mil`/GitHub/the official Grants.gov extract bucket is linked.

### Verified in this pass

- `python -m unittest discover -s tests` — 25 tests pass. Includes new tests for cancellation-plus-passed-deadline, cancelled forecasts, and the terminal-record keep rule.
- `node --test tests/*.test.mjs` — 32 tests pass: 12 in `catalog.test.mjs`, 12 in `ui.test.mjs`, 5 in `match.test.mjs`, 3 in `csv.test.mjs`.
- `python -m pipeline.validate_published` — "Published catalog ok: 1286 opportunities, as of 2026-09-26", run against the compacted files.
- A static server on `docs/` returned HTTP 200 for the page, all four JS modules, the stylesheet, the favicon, the 404 page, and all seven data files.
- The rendered DOM was inspected for every primary route. No route fell through to the missing-record view and jsdom reported no page errors.

### Not verified in this pass

- **This sandbox has no direct network route to Grants.gov, NSF, NIH, or USAspending** (TLS to those hosts fails; `api.github.com` is reachable). No live refresh was run here. The catalog under `docs/data` is the one the last CI refresh produced. CI re-runs the refresh on push, which is how the data changes get validated against the live extract.
- **The deployed GitHub Pages site was not fetched in this pass**, because `*.github.io` is unreachable from here. Earlier sessions recorded successful deployments (runs `36289849530` and `36290163686`); that claim is not re-verified here.
- **jsdom is not a browser.** It verifies DOM structure, routing, counts, sort order, and link targets. It does not verify visual layout, responsive breakpoints, real viewport behavior, color contrast, keyboard focus order, or form autofill. Those remain untested.

### What is not claimed

- SAM.gov contract BAAs are not collected. Simpler.Grants.gov is not used; it requires an API key this project does not have.
- Historical award files are samples. NSF and NIH pulls were capped.
- The site does not generate a specific research project and present it as an agency request. It quotes official sentences and compares a project the user types.
- Grants.gov agency code `PAMS` is the Office of Science submission code. Records keep that official code. Do not rename it to DOE in the source fields.
- A phrase match such as "scientific research" can still include a non-research program if that phrase appears in official text. The matched basis is stored so the reason is visible.
- Project Builder notes are stored in browser `localStorage`, not sent to a server. They are not encrypted; do not enter sensitive or controlled research information.
- `opportunities.json` is still about 7.3 MB uncompressed (about 0.96 MB gzipped). A lean index plus on-demand detail records would cut the first load substantially and has not been built.

### Gaps to close before relying on the platform for application planning

- **Coverage:** Grants.gov is the primary opportunity source, supplemented by NSF funding RSS. Many federal research contract BAAs and some agency-specific announcements are outside coverage. Investigate official SAM.gov and agency sources rather than implying comprehensive federal coverage.
- **Complete application requirements:** The pipeline uses Grants.gov synopsis/extract fields and extracts selected sentences. It does not parse every linked NOFO, PDF, attachment, or amendment. Required registrations, documents, partnerships, PI qualifications, geography, and letter-of-intent rules may be missing; quote absence is not evidence that a requirement does not exist.
- **Historical awards:** Current NSF and NIH pulls are capped samples; USAspending covers only a subset of assistance listings and one page per batch. They do not support complete award totals, agency-wide trend claims, or recipient success rates.
- **Research-gap analysis:** Keyword counts and multi-agency topic overlap are descriptive leads, not measured funding trends or evidence of a research gap. The site must not claim a gap until it has a documented method and sufficient longitudinal data.
- **Matching quality:** The browser fit score is a transparent lexical heuristic. It has not been benchmarked against expert-labeled matches or outcome data and must not be presented as eligibility approval or award probability.
- **Real-browser testing:** DOM-level tests now exist, but there are still no real-browser, responsive-viewport, or accessibility tests.

### How to run

```bash
python -m unittest discover -s tests -v   # 25 pipeline tests
npm ci                                    # installs jsdom for the DOM tests
node --test tests/*.test.mjs              # 32 browser-logic and rendered-view tests
python -m pipeline.refresh                # needs network access to the official sources
python -m pipeline.validate_published     # checks the files the site will serve
```

The site reads `docs/data/` with relative URLs so it works on a GitHub Pages project site. Serve `docs/` locally with any static server. Do not hand-edit opportunity JSON. Pages publishes the repository root, so `.nojekyll` must stay; without it Jekyll drops `docs/index.html`.

---

## Specification

This specification is the starting point for every work session.

# Federal Research Grant Intelligence Platform

## Review the Repo First

Review the entire repo before doing any work.

This prompt should be placed in the repo README and read **every time we work on this project** as the starting point for the project. The README should remain the central source of truth for what we are building, why we are building it, our requirements, limitations, and what still needs to be completed.

Do not assume the current implementation is correct simply because it already exists. Inspect what is actually working, what is incomplete, what is simulated, what is hardcoded, what is outdated, and what is missing.

The goal is to build something genuinely useful for everyday use—not a demonstration, mockup, or collection of manually maintained information.

---

# Project Goal

Build a continuously updated **Federal Research Grant Intelligence Platform** that helps a person discover:

1. What federal research funding opportunities currently exist.
2. What scientific and technical research areas the U.S. government is currently interested in funding.
3. Which agencies and programs are funding those areas.
4. Who is eligible to apply.
5. How much funding is available.
6. What the deadlines and important dates are.
7. What research questions and project types the agencies are looking for.
8. What previous projects have received funding.
9. What research gaps or opportunities appear to exist.
10. What potential projects could be developed into strong grant proposals.
11. Which opportunities appear to have the strongest documented fit with a proposed project.
12. What would prevent a person, company, nonprofit, university, or other applicant from applying.

The ultimate goal is to answer:

> **“Given the research funding that is actually available right now, what research projects could we realistically propose, who could fund them, why would they fit the funding opportunity, how much funding could potentially be available, and what would we need to do to submit a legitimate application?”**

The system should reduce or eliminate the need to manually search dozens of government websites, read hundreds of funding announcements, track deadlines, compare eligibility requirements, and repeatedly check whether information has changed.

It should provide a **current, verified research-funding feed**.

---

# Core Values

The following principles should remain focal points when building, developing, researching, suggesting upgrades, and implementing the project.

## Maximize P(Win)

“Maximize the Probability of Winning.”

For this project, this means maximizing the probability that the platform produces **accurate, useful, actionable research-funding intelligence**.

Every major technical decision should consider:

* Accuracy
* Source reliability
* Data freshness
* Completeness
* Eligibility accuracy
* Research-topic matching
* Funding-opportunity matching
* Reliability of recommendations
* Ease of verification
* Maintainability
* Scalability
* User usefulness

Do not optimize for having the most information if that information is unreliable.

Do not optimize for a beautiful UI if the underlying data is wrong.

Do not optimize for the number of grants collected if important fields cannot be verified.

The objective is to build something people can actually rely on.

## Own the Outcome

Own the entire outcome end to end.

If something is broken and the information or tools necessary to fix it are available, investigate and fix it rather than waiting for another instruction.

If an approach does not work, determine why and find a better approach.

If a data source is unreliable, identify it and replace it where possible.

If an API does not provide the required information, investigate the underlying website, public feeds, downloadable datasets, documents, or other legitimate public sources.

Treat failures as information that should improve the project.

Do not simply report that something cannot be done when there is another reasonable avenue to investigate.

---

# No Hallucinations

This is one of the most important requirements of the entire project.

**Never invent grant opportunities, agencies, funding amounts, deadlines, eligibility requirements, research topics, award amounts, URLs, statistics, applicants, recipients, or other information.**

Every factual data point must have a source.

Whenever possible, use the **official government source as the primary source**.

Examples include:

* Grants.gov
* NSF
* NIH
* DOE
* NASA
* DARPA
* DoD
* USDA
* NOAA
* EPA
* NIST
* DHS
* DOT
* CDC
* FDA
* Other official federal agencies
* Official federal datasets
* Official agency funding databases
* Official agency announcements
* Official government documents

Third-party sources may be useful for discovery, but they should not replace the official source when an official source is available.

If information cannot be verified, clearly mark it as:

**Unverified**

or

**Verification Required**

Do not silently convert uncertainty into fact.

---

# Line-by-Line Verification

Work line by line and field by field.

For every grant opportunity, verify as many of the following as applicable:

* Agency
* Sub-agency
* Program
* Funding opportunity title
* Funding opportunity number
* Description
* Research topic
* Research objectives
* Eligibility
* Applicant types
* Geographic restrictions
* Funding amount
* Expected number of awards
* Award duration
* Application deadline
* Letter-of-intent deadline
* Estimated award date
* Cost-sharing requirements
* Matching requirements
* Required registrations
* Required documents
* Principal investigator requirements
* Program contact
* Official application URL
* Official source URL
* Publication date
* Last updated date
* Current status
* Whether the opportunity is open or closed

Do not assume a field is correct because another website says it is correct.

Verify it against the authoritative source.

Provide official links so the user can manually review the source.

---

# Current Data Is Critical

This project must prioritize **current information**.

A grant that closed six months ago should not appear as an active opportunity.

A deadline that changed must be updated.

A funding opportunity that was canceled must be identified.

A new opportunity should automatically enter the system when technically possible.

The platform should distinguish clearly between:

* Open
* Upcoming
* Closed
* Canceled
* Archived
* Unknown
* Verification Required

The system should display when information was last verified.

Ideally each record should contain:

**Last verified: [date/time]**

The user should be able to determine how fresh the information is.

---

# Eliminate Manual Research

The purpose of this project is specifically to reduce the need for manual research.

Do not build a system that requires the user to manually enter every grant.

Do not build a system that requires the user to manually check every agency website.

Do not build a system where the user has to manually determine whether a grant is still open.

Automate discovery, collection, normalization, comparison, verification, and updating wherever technically possible.

If something genuinely cannot be automated, identify the limitation clearly.

---

# Research Topic Intelligence

The platform should not only collect individual grants.

It should understand the **research areas behind the grants**.

For example, the system should be able to identify recurring federal research interests such as:

* Artificial intelligence
* Machine learning
* Cybersecurity
* Robotics
* Quantum computing
* Energy
* Nuclear technology
* Climate science
* Materials science
* Biotechnology
* Biomedical research
* Space technology
* Transportation
* Advanced manufacturing
* Scientific computing
* Information systems
* Agriculture
* Defense technologies
* Environmental science
* Public health
* Infrastructure
* Other emerging research areas

Do not limit the system to this list.

Discover research categories from the actual funding data.

The system should be able to identify:

* Frequently funded research areas
* Emerging research areas
* Agencies increasing activity in a research area
* Agencies decreasing activity
* New funding programs
* Recurring funding programs
* Large funding opportunities
* Small funding opportunities
* Areas with multiple agencies funding related research
* Research areas with identifiable funding gaps or opportunities

These conclusions must be based on actual verified data.

---

# Project Idea Generation

The platform should eventually help transform funding opportunities into **potential research projects**.

For example:

**Funding opportunity**

→ Research objective

→ Problem being addressed

→ Existing research

→ Research gap

→ Potential research question

→ Possible methodology

→ Required resources

→ Potential applicant type

→ Potential budget

→ Relevant funding programs

→ Grant proposal opportunity

The system should distinguish between:

### Verified Facts

Information directly supported by authoritative sources.

### Analysis

Reasonable conclusions derived from verified information.

### Proposed Research Ideas

New project concepts generated from the available information.

Never present a generated research idea as if the government explicitly requested that exact project unless the source actually says so.

---

# Grant Opportunity Matching

Build a system that can compare a proposed research project against available funding opportunities.

For each potential match, show the evidence behind the match.

Possible factors include:

* Research-topic alignment
* Explicit objectives alignment
* Applicant eligibility
* Funding range
* Project duration
* Technology requirements
* Geographic requirements
* Required partnerships
* Research methodology alignment
* Timing
* Program priorities

Do **not** simply output:

> “This is a great grant.”

Instead show:

> **Why this opportunity matches**

with the underlying evidence.

For example:

* 4/5 stated research objectives align
* Applicant type appears eligible
* Proposed project falls within stated research area
* Funding range is compatible
* Deadline is still open
* Required partnership is currently missing

Every conclusion should be explainable.

---

# Funding Opportunity Scoring

If the platform eventually uses a score or ranking, the score must be transparent.

Do not create a mysterious AI score.

Show exactly what contributes to it.

For example:

**Opportunity Fit**

* Research alignment
* Eligibility
* Funding compatibility
* Timeline compatibility
* Required capabilities
* Evidence strength
* Data freshness

The system should distinguish between:

**Opportunity fit**

and

**Probability of receiving an award.**

Do not claim that a score predicts winning unless there is verified empirical evidence supporting that prediction.

Where historical award data exists, use it to provide additional context rather than inventing probabilities.

---

# Historical Awards

Where public federal award data is available, collect and analyze it.

Determine:

* Who received funding
* What projects were funded
* Award amounts
* Award dates
* Agency
* Program
* Research area
* Geographic information where appropriate
* Organization type
* Number of awards
* Historical funding trends

Use historical awards to understand what agencies have actually funded.

This is extremely important.

The platform should help answer:

> **“What does this agency say it wants to fund?”**

and separately:

> **“What has this agency actually funded?”**

Do not confuse the two.

---

# Source Transparency

Every important piece of information displayed to the user should have a source.

The interface should make it easy to click through to the original source.

Where possible display:

**Source:** Official agency
**Published:** Date
**Last verified:** Date/time
**Official URL:** Link

The user must be able to independently verify important information.

---

# Website

Create a GitHub Pages website for the project.

The website should have a:

* Clean UI
* Modern design
* Simple navigation
* Fast experience
* Responsive layout
* Desktop support
* Mobile support
* Search
* Filtering
* Sorting
* Clear status indicators
* Source links
* Verification dates
* Grant details
* Research-topic exploration
* Agency exploration
* Funding analysis
* Project-idea exploration

The interface should prioritize usefulness over visual complexity.

---

# Main Views

At minimum, investigate and implement views such as:

## Current Funding Feed

A continuously updated feed of currently open and upcoming opportunities.

## Grant Explorer

Search and filter opportunities by:

* Agency
* Research area
* Funding amount
* Deadline
* Applicant type
* Location
* Program
* Status

## Research Explorer

Explore what the federal government is currently funding and researching.

## Agency Explorer

See funding activity by agency.

## Research Opportunity Finder

Help users identify research areas where multiple funding opportunities exist.

## Project Builder

Allow a user to describe a potential research idea and identify relevant funding opportunities.

## Historical Funding

Explore previously funded research.

## Verification

Show exactly where the platform obtained information and when it was last verified.

---

# Data Architecture

Do not build the project around manually maintained static data if an automated source is available.

Investigate:

* APIs
* Public APIs
* Government APIs
* RSS feeds
* Open datasets
* Public databases
* Downloadable government files
* Government webpages
* Government PDFs
* Structured data
* Public award databases

Prefer structured official data where available.

Build the system so additional agencies and sources can be added without rebuilding the entire application.

---

# Data Pipeline

Build toward an automated pipeline:

**Source discovery**

↓

**Data collection**

↓

**Normalization**

↓

**Deduplication**

↓

**Validation**

↓

**Verification**

↓

**Classification**

↓

**Research-topic extraction**

↓

**Historical analysis**

↓

**Opportunity matching**

↓

**Database**

↓

**Website**

↓

**Current feed**

The system should be designed so that this process can eventually run automatically.

---

# No Fake Data

Do not use fake grants to make the website look populated.

Do not use fabricated funding amounts.

Do not use placeholder government agencies presented as real data.

If real data is unavailable, make the limitation obvious.

A smaller database containing verified information is better than a large database containing questionable information.

---

# Research Quality

The platform should distinguish:

**Official fact**

**Derived statistic**

**Model-generated analysis**

**Research hypothesis**

**Proposed project**

**Unverified information**

These categories must never be silently mixed together.

---

# Suggestions and Improvements

Do not merely follow instructions literally.

While working on the project, identify:

* Missing functionality
* Data-quality problems
* Better official sources
* Better APIs
* Better architecture
* Security problems
* Scalability problems
* Performance problems
* UI problems
* Research methodology problems
* Verification problems
* False-positive opportunities
* Missing grant categories
* Important limitations

Make concrete suggestions and, when appropriate, implement improvements rather than simply describing them.

---

# Verification Before Completion

Before declaring a task complete:

1. Test the actual implementation.
2. Verify that data is coming from the claimed source.
3. Verify URLs.
4. Verify API responses.
5. Verify parsing.
6. Verify filtering.
7. Verify search.
8. Verify sorting.
9. Verify grant status.
10. Verify dates.
11. Verify eligibility information.
12. Verify the UI.
13. Verify mobile behavior.
14. Check for broken links.
15. Check for duplicate records.
16. Check for stale information.
17. Check for hallucinated information.
18. Check for hardcoded information that should be dynamic.
19. Check for error handling.
20. Check that the site actually works from a clean environment.

Do not claim something works without testing it.

---

# Multiple-Pass Development

Run every major task through multiple passes.

## Pass 1 — Build

Implement the requested functionality completely.

Then test it.

## Pass 2 — Attack the Implementation

Review the work as if trying to break it.

Look for:

* Bugs
* Missing requirements
* Incorrect assumptions
* Broken data sources
* Incorrect parsing
* Stale data
* False positives
* Duplicate data
* Edge cases
* Security issues
* Performance issues
* UI problems
* Incorrect eligibility conclusions
* Hallucinations

Fix everything discovered.

## Pass 3 — Independent Recheck

Go back to the original request.

Check the entire implementation against it line by line.

Determine:

* What was requested?
* What was actually implemented?
* What is partially implemented?
* What is missing?
* What is simulated?
* What is verified?
* What remains uncertain?

Fix remaining problems.

## Pass 4 — Real-World Use Test

Use the application as an actual user would.

Ask:

> “Could someone realistically use this today to discover a legitimate research funding opportunity and determine whether they could develop a project around it?”

Find anything that prevents that.

Fix it where possible.

---

# Pull Request and Main Branch

When the task is complete:

1. Review all changes.
2. Run tests.
3. Verify the website.
4. Verify the data.
5. Review the diff.
6. Create a pull request.
7. Review the pull request.
8. Fix issues found during review.
9. Merge the pull request into `main` when appropriate.
10. Verify that `main` contains the final working implementation.
11. Verify the deployed GitHub Pages site.

Do not merge broken or unverified work simply because the requested feature was implemented.

---

# Final Report

At the end of each major development session, report:

### Completed

What was actually implemented.

### Verified

What was independently checked and confirmed.

### Sources

The important official sources used.

### Current Limitations

What still prevents the project from being fully successful.

### Potential Problems

Anything that could produce inaccurate or misleading results.

### Recommended Next Work

The most important remaining tasks.

### Data Coverage

Which agencies, programs, and sources are currently covered.

### Automation Status

What is automatically updated versus what remains manual.

### Verification Status

Which information is verified and which requires additional verification.

---

# Ultimate Objective

The final product should become more than a grant-search website.

It should become a **research-funding intelligence system**.

A user should be able to open the site and answer:

> **What is the federal government currently interested in researching?**

> **What funding is currently available?**

> **Who can apply?**

> **How much money is available?**

> **What research has already been funded?**

> **What problems are agencies asking researchers to solve?**

> **What potential research projects fit those problems?**

> **Which funding opportunities match those projects?**

> **What evidence supports that match?**

> **What would I need to do to become eligible and apply?**

> **What are the deadlines?**

> **What information changed since the last time I checked?**

The system should eliminate as much repetitive manual research as technically possible while maintaining a very high standard of factual accuracy and source verification.

The ultimate standard is:

**Current. Verified. Comprehensive. Explainable. Automated. Useful.**

**No hallucinations.**

**Verify everything possible.**

**Show the source.**

**Own the outcome.**

**Maximize P(Win).**
