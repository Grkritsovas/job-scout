# Contributing Guide

This repository is small in framework terms but policy-heavy in behavior. A lot of the real product logic lives in plain Python heuristics, scraper assumptions, and ranking rules. Read this guide before changing matching, scraper, URL, location, or storage code.

`README.md` is the setup and usage entrypoint. This file is the internal map for contributors and LLM agents.

## System Purpose

The app scrapes public job boards, filters for junior and UK-relevant roles, ranks jobs against one or more recipient profiles, optionally reranks the top semantic matches with Gemini, sends grouped email digests, and stores reviewed job URLs so recipients do not keep seeing the same roles.

The intended steady-state runtime is a scheduled GitHub Actions workflow backed by persistent storage:

1. Load recipient profiles from the database, and load target lists from environment variables, local override files, or bundled examples.
2. Scrape supported providers into a shared in-memory job shape.
3. Enrich jobs with sponsorship metadata.
4. Rank and filter jobs separately for each recipient.
5. Optionally send the unseen shortlist through Gemini.
6. Build digest payloads and send email.
7. Store reviewed job URLs for that recipient.

## End-to-End Job Flow

### 1. Startup and config loading

- `run_all.py` is the orchestration entrypoint.
- `config/recipient_profiles.py` normalizes recipient settings and defaults.
- `config/target_config.py` resolves scraper targets with precedence:
  environment -> local file -> bundled example.
- `storage.py` selects SQLite by default and Postgres when `DATABASE_URL` points there.
- Runtime recipient profiles are database-only. Ignored files such as `recipient_profiles.local.json` are not read by `run_all.py`.

### 2. Scraper collection

- `run_all.collect_all_jobs()` runs the four source families concurrently:
  `ashby_scraper`, `greenhouse_scraper`, `lever_scraper`, `nextjs_scraper`.
- Each source family still scrapes serially internally.
- Each scraper returns a shared job dict with fields such as:
  `company`, `title`, `url`, `description`, `locations`, `location`, `source`, `target_value`, `description_status`, `description_looks_like_html`.
- A single merge step dedupes jobs by URL after the source-family workers return.

### 3. Description and URL normalization

- `shared/job_urls.py` sanitizes URLs and enforces host allowlists.
- `shared/descriptions.py` extracts visible text, strips repeated boilerplate, and fetches details for platforms that do not expose enough description text directly.
- `shared/locations.py` applies UK-location heuristics and formatting helpers.

### 4. Sponsorship enrichment

- `sponsorship.py` adds metadata to each job before recipient-specific ranking.
- Added fields:
  `normalized_company`, `sponsorship_status`, `is_sponsor_licensed_employer`, `sponsor_company_metadata`.
- This layer is informational for matching, but it affects digest content and sponsor markers.

### 5. Recipient-specific ranking

- `run_all.select_jobs_for_recipient()` loads previously seen URLs for that recipient, then calls `matching/ranking.py`.
- `matching/hard_filters.py` rejects obvious non-target roles first:
  seniority, commercial titles, non-UK locations, authorization/eligibility mismatches, and experience requirements above the junior threshold.
- Internship titles are not automatically rejected. Current-student-only internships are rejected from eligibility language in the description.
- Commercial title filtering can be recipient-aware for explicitly targeted role families such as marketing.
- `matching/profile_library.py` builds the semantic profile texts used for scoring.
- `matching/ranking.py` then:
  - builds matching text from title + cleaned description
  - scores against profile embeddings
  - applies junior-title boosts
  - applies optional salary penalties
  - sorts by final `ranking_score`
- Added ranking fields include:
  `profile_scores`, `top_profile`, `top_score`, `second_profile`, `second_score`, `score_margin`, `fit_summary`, `ranking_score`, `salary_upper_bound_gbp`, `salary_penalty_applied`.

### 6. Unseen filtering and optional Gemini review

- Before ranking, `run_all.select_jobs_for_recipient()` removes jobs already seen by that recipient.
- `matching/gemini_rerank.py` has two modes:
  - semantic-only when `GEMINI_API_KEY` is absent
  - semantic + Gemini rerank when the key is present
- Gemini mode uses semantic ranking as retrieval, sends the top unseen jobs through a two-pass prompt flow, and returns:
  `jobs_to_send`, `reviewed_jobs`, `review_mode`, `llm_shortlisted_jobs`, `gemini_reviewed_jobs`, `review_error`, `review_error_stage`.
- Gemini prompts include structured candidate context such as `education_status` and `work_authorization_summary` when configured.
- Important current invariant:
  in Gemini mode, reviewed jobs are marked as seen even when Gemini rejects them.
- Important current failure behavior:
  if Gemini is enabled but unavailable, the app does not fall back to the semantic shortlist for that run.

### 7. Digest generation and delivery

- `shared/digest.py` groups jobs by company, sorts the strongest ones first, and builds plain-text + HTML email payloads.
- `emailer.py` sends the digest unless `JOB_SCRAPER_DRY_RUN=1`, in which case it prints the output instead.

### 8. Seen-job persistence

- `storage.store_seen_jobs()` persists reviewed jobs after each recipient is processed.
- Storage is recipient-aware, so the same job can be new for one recipient and already seen for another.

## Module Map

### Entry points

- `run_all.py`
  Main runtime orchestration.
- `manage_targets.py`
  Inspect effective scraper targets.
- `examples/preview_digest.py`
  Generate a local HTML/text digest preview from sample data.
- `admin_ui.py`
  Run a local admin UI for database-backed recipient profiles, review audit rows,
  and explicit per-recipient/job seen-marker resets.
- `tools/validate_recipient_profiles.py`
  Validate stored recipient profile JSON through the runtime normalization path.
- `tools/replay_run.py`
  Replay ranking and review from a saved run snapshot without scraping, sending email, or marking jobs seen.

### Config

- `config/config_loader.py`
  Shared JSON/list loading with environment/local/example precedence.
- `config/recipient_profiles.py`
  Recipient normalization and defaults.
- `config/target_config.py`
  Target specs and effective-target resolution.

### Scrapers

- `scrapers/ashby_scraper.py`
  Ashby target parsing, GraphQL fetch, per-job description fetch.
- `scrapers/greenhouse_scraper.py`
  Greenhouse board fetch and content extraction.
- `scrapers/lever_scraper.py`
  Lever target normalization, API host fallback, per-job description fetch.
- `scrapers/nextjs_scraper.py`
  Next.js `__NEXT_DATA__` parsing plus per-job description fetch.
- `scrapers/scrape_diagnostics.py`
  Run-time scrape and ranking summaries printed to stdout.

### Matching and policy

- `matching/profile_library.py`
  Built-in semantic profile definitions and fallback profile text.
- `matching/filters.py`
  Keyword and regex constants for hard-filter logic.
- `matching/hard_filters.py`
  Rule-based rejection before semantic scoring.
- `matching/ranking.py`
  Embedding-based scoring, junior boosts, penalties, and sort order.
- `matching/gemini_rerank.py`
  Two-pass Gemini shortlist logic and fallback behavior.
- `matching/models/__init__.py`
  Embedding model catalog.

### Shared helpers

- `shared/descriptions.py`
  HTML/text extraction and description fallback fetching.
- `shared/job_urls.py`
  URL sanitization and source-specific host allowlists.
- `shared/locations.py`
  UK location heuristics.
- `shared/company_names.py`
  Company-name normalization helpers.
- `shared/digest.py`
  Text and HTML digest rendering.

### Storage and output

- `sponsorship.py`
  Sponsor lookup loading and sponsorship-status classification.
- `storage.py`
  SQLite/Postgres storage abstraction and schema management.
- `emailer.py`
  SMTP sending and dry-run behavior.

### Compatibility shims

- `semantic_matching.py`
  Thin re-export layer over `matching/*`.
- `utils.py`
  Thin re-export layer over selected shared helpers.

## Safe vs Risky Edit Areas

### Usually safer

- Docs, examples, and contributor tooling.
- `manage_targets.py` and `examples/preview_digest.py`.
- Pure presentation changes inside `shared/digest.py` that do not change grouping, ordering, or filtering semantics.
- Adding tests around existing behavior.

### High risk

- `matching/hard_filters.py`
  Small regex or keyword changes can quietly shift what categories of jobs are even eligible.
- `matching/ranking.py`
  Thresholds, boosts, penalties, and sort rules directly change who receives what.
- `matching/gemini_rerank.py`
  Prompt text, candidate shape, and reviewed-job behavior can materially change shortlist quality and dedupe semantics.
- `shared/locations.py`
  UK filtering is heuristic and business-critical for this project.
- `shared/job_urls.py`
  Host allowlists and sanitization protect both correctness and trust boundaries.
- `storage.py`
  Schema and "seen" behavior affect dedupe across runs and recipients.
- `scrapers/*.py`
  Provider-specific assumptions can fail silently when job-board structures drift.
- `shared/descriptions.py`
  Description extraction quality strongly affects matching quality downstream.
- `run_all.py`
  The order of ranking, unseen filtering, review, send, and persistence is intentional.

## Agent Guardrails

Treat these as manual-review areas, not "quick cleanup" opportunities:

1. Do not casually change the junior-first, UK-first, or hard-eligibility assumptions.
2. Do not casually change Gemini failure behavior or the rule that Gemini-reviewed jobs are stored as seen.
3. Do not loosen URL allowlists or location heuristics without tests and a clear reason.
4. Do not refactor scraper code without checking whether the same field assumptions really hold across all providers.
5. Do not remove compatibility shims (`semantic_matching.py`, `utils.py`) unless all imports and tests are updated together.
6. Do not rely on "the tests still pass" as proof that live job boards still match the parsing logic.

When touching risky areas:

1. Read the adjacent tests first.
2. Preserve current invariants unless the change is explicitly intended.
3. Add or update tests in the same area.
4. Run the full suite before handoff.
5. If behavior changes affect ranking or seen-job semantics, call that out explicitly in the final summary.

## Local Workflows

### Inspect effective targets

```powershell
python manage_targets.py list
python manage_targets.py list ashby
python manage_targets.py lever
```

Use this before debugging a scraper. Many "missing jobs" issues are really target-resolution issues.

### Run the tests

```powershell
python -m unittest discover -s tests -v
```

If you are using the checked-in virtualenv on Windows, this also works:

```powershell
venv\Scripts\python.exe -m unittest discover -s tests -v
```

### Preview the digest locally

```powershell
python examples/preview_digest.py
```

This writes preview files into `examples/` so you can inspect formatting changes without sending mail.

### Run the scraper locally without sending email

```powershell
$env:JOB_SCRAPER_DRY_RUN = "1"
python run_all.py
```

Local runs default to SQLite in `job_scraper.db` unless `DATABASE_URL` is set, but recipient profiles still have to exist in the active database. `recipient_profiles.local.json` is ignored local scratch data and is not read by the runtime.

### Validate recipient profiles

```powershell
python tools/validate_recipient_profiles.py --enabled-only
```

This uses the same normalization path as `run_all.py`, so it catches schema drift before a real run.

### Save and replay a run

```powershell
python run_all.py --save-run runs/latest.json
python tools/replay_run.py runs/latest.json --recipient demo-recipient
```

Replay mode is useful for tuning profiles against the same scraped job set without sending email or writing seen-job records.

### Run the scraper normally

```powershell
python run_all.py
```

Required environment variables for a realistic local run are the same core ones documented in `README.md` and `docs/CONFIGURATION.md`.

## Test Map

Current tests are fast, deterministic, and mostly unit-level. They cover:

- config and CLI loading
- URL sanitization and location filtering
- scraper normalization and selected provider edge cases
- matching heuristics, hard filters, title boosts, salary penalties, and model defaults
- Gemini rerank orchestration and prompt construction
- sponsorship enrichment
- recipient-aware seen-job storage
- digest text/HTML rendering

Current gaps to keep in mind:

- no CI step currently runs the test suite explicitly
- no live integration tests against job boards
- no real-network end-to-end orchestration test for `run_all.py`
- limited direct coverage for `nextjs_scraper.py`, `emailer.py`, and Postgres-specific behavior

## Practical Review Checklist

Before merging changes in risky areas, manually review:

1. Whether the code still reflects the product intent of "junior + UK + credible employability now".
2. Whether live scraper assumptions still match the boards you actually target.
3. Whether URL and location heuristics are rejecting or admitting the right edge cases.
4. Whether reviewed-job persistence still matches the intended dedupe behavior.
5. Whether the current docs still describe the real operating path for local and hosted runs.
