# Configuration Guide

This project now loads recipient profiles from the database only. Runtime recipient config lives in `app_config.recipient_profiles.config_json`.

For a simple walkthrough of filling in your profile, see [Personalizing Your Job Search](PROFILE_CONFIGURATION.md). It covers what to write about yourself, the jobs you want, and your preferences. This reference covers setup and technical details.

## Required Hosted Setup

Required GitHub Actions secrets:
- `JOB_SCRAPER_EMAIL`
- `JOB_SCRAPER_APP_PASSWORD`
- `DATABASE_URL`

Optional GitHub Actions secret:
- `GEMINI_API_KEY`

Optional GitHub Actions variables:
- `JOB_SCRAPER_LLM_MODEL`
- `JOB_SCRAPER_LLM_TOP_N`
- `JOB_SCRAPER_LLM_BATCH_SIZE`
- `JOB_SCRAPER_LLM_DESCRIPTION_CHARS`
- `JOB_SCRAPER_LLM_RETRY_ATTEMPTS`
- `JOB_SCRAPER_LLM_RETRY_BASE_SECONDS`
- `JOB_SCRAPER_SUPPORT_BACKLOG_HOURS`
- `JOB_SCRAPER_AUDIT_KEEP_ROWS`
- `JOB_SCRAPER_AUDIT_HIGH_WATER_ROWS`
- `ASHBY_COMPANIES_JSON`
- `GREENHOUSE_BOARD_TOKENS_JSON`
- `LEVER_COMPANIES_JSON`
- `NEXTJS_URLS_JSON`
- `SPONSOR_COMPANIES_CSV`

## Runtime Recipient Profiles

The scraper reads enabled profiles from:
- `app_config.recipient_profiles`

Schema columns:
- `recipient_id`
- `email`
- `enabled`
- `config_json`
- `created_at`
- `updated_at`

Version history lives in:
- `app_config.recipient_profile_versions`

The app uses a direct Postgres connection through `DATABASE_URL`. It does not read recipient profiles from GitHub secrets or local runtime JSON files.

Ignored files such as `recipient_profiles.local.json` may still exist as old scratch data in a local checkout, but they are not part of the runtime config path. Treat the database row as the source of truth.

## Review Caps

`JOB_SCRAPER_LLM_TOP_N` controls how many ranked semantic matches are passed into the review stage. When Gemini is enabled, these are the jobs Gemini reviews. If Gemini is disabled, the same cap is used for the semantic-only digest path.

Semantic matches above the threshold but outside this top-N cap are stored as pending backlog. They can be picked up in a later run after higher-ranked reviewed jobs have been stored as seen.

Semantic matches below the threshold are marked seen after ranking so the same weak matches are not repeatedly embedded on later runs. Hard-filtered jobs are not marked seen; those checks are deterministic and cheap to repeat.

## Support Runs

The workflow has main scheduled runs and support schedules. Main schedules run the full scraper. Support schedules first run `check_review_backlog.py`, which queries recent pending rows in the job state table. If no recent backlog exists, the workflow skips full dependency installation and scraper execution. If backlog exists, the support run processes only stored pending backlog rows.

Current scheduled times are UTC:
- main runs: `09:30`, `16:30`
- support checks: `00:00`, `03:00`, `12:00`, `14:00`, `20:00`

`JOB_SCRAPER_SUPPORT_BACKLOG_HOURS` controls the age window for support-run backlog checks. The default is `48` hours.

## Local Admin UI

Run the local admin UI with:

```powershell
python admin_ui.py
```

The admin UI requires an explicit database target. For normal use, set `DATABASE_URL` to the Supabase/Postgres database before launching it:

```powershell
$env:DATABASE_URL = "postgresql://user:password@host:5432/database"
python admin_ui.py
```

You can also pass a database URL directly:

```powershell
python admin_ui.py "postgresql://user:password@host:5432/database"
```

SQLite is only used when you explicitly request it, for example:

```powershell
python admin_ui.py --database-url "sqlite:///job_scraper.db"
```

The UI can edit database-backed recipient profiles through locked schema fields, preview the generated JSON, validate/normalize it through the runtime profile loader, compare/restore saved profile versions, and browse recent `app_config.recipient_review_audit` rows. It does not edit GitHub secrets, local recipient JSON files, or job state records.

## Review Audit

The scraper writes compact review audit rows to:
- `app_config.recipient_review_audit` on Postgres/Supabase
- `recipient_review_audit` on local SQLite

Rows are keyed for review by `run_id`, `recipient_id`, `job_url`, `review_family`, and `classification`. The audit stores job metadata, semantic scores, hard-filter reasons, Gemini pass/fail classification, concise Gemini reasons, and short evidence snippets. It does not store full job descriptions or recipient profile JSON.

Audit retention is controlled by:
- `JOB_SCRAPER_AUDIT_KEEP_ROWS`, default `1000`
- `JOB_SCRAPER_AUDIT_HIGH_WATER_ROWS`, default `1500`

When total audit rows exceed the high-water value, the oldest rows are pruned until only the keep count remains.

## Job State And Support Runs

The scraper stores per-recipient job processing state in:
- `app_config.recipient_seen_jobs` on Postgres/Supabase
- `recipient_seen_jobs` on local SQLite

Rows with `is_seen=true` are skipped in future runs. Rows with `is_seen=false` are pending backlog rows that can be picked up by support runs. Support runs check recent pending rows before installing full scraper dependencies.

Support runs are backlog-only. They do not scrape the configured source families,
do not apply hard filters, and do not run semantic ranking. They load pending
rows, refetch each stored job URL, and pass only successfully refetched backlog
jobs to Gemini using the stored semantic metadata. Full descriptions from the
refetch are not stored.

Temporary URL refetch failures remain pending. Clearly dead URLs, such as 404 or
410 pages, are marked seen with an expired classification so they no longer
trigger backlog processing.

Support runs do not send digest emails directly. Approved support-run jobs are queued in:
- `app_config.recipient_digest_queue` on Postgres/Supabase
- `recipient_digest_queue` on local SQLite

Main runs send queued approved jobs together with newly approved jobs, then mark the queued rows as sent.

The support-run backlog age is controlled by:
- `JOB_SCRAPER_SUPPORT_BACKLOG_HOURS`, default `48`

See `docs/INTENDED_BEHAVIOR.md` for the concise behavior contract.

## Grouped Recipient Profile Shape

Each `config_json` record should look like this:

```json
{
  "id": "demo-recipient",
  "enabled": true,
  "delivery": {
    "email": "recipient@example.com",
    "language": ""
  },
  "candidate": {
    "summary": "Short factual candidate summary.",
    "education_status": "Graduated Oct 2025; not a current student.",
    "target_roles": [
      {"id": "swe"},
      {"id": "data_science", "match_text": "Custom profile text"}
    ]
  },
  "job_preferences": {
    "location": "UK",
    "target_seniority": {
      "max_explicit_years": 1,
      "boost_multiplier": 1.2,
      "boost_title_terms": ["junior", "grad", "graduate", "entry level", "entry-level"]
    },
    "salary": {
      "preferred_max_gbp": 45000,
      "hard_cap_gbp": 70000,
      "penalty_strength": 0.35
    }
  },
  "eligibility": {
    "needs_sponsorship": false,
    "work_authorization_summary": "Compact UK work authorization context for Gemini.",
    "check_hard_eligibility": false,
    "use_sponsor_lookup": false
  },
  "matching": {
    "semantic_threshold": 0.42
  },
  "llm_review": {
    "extra_screening_guidance": [],
    "extra_final_ranking_guidance": []
  }
}
```

## What Each Field Affects

- `delivery.email`
  Recipient email address for digest delivery.
- `delivery.language`
  Optional preferred language for user-facing Gemini `why_apply` digest text, for example `Greek`. If omitted, Gemini uses its default response language.
- `candidate.target_roles`
  Defines the role families used for semantic matching. See [role description examples](PROFILE_CONFIGURATION.md#choose-the-jobs-you-want). An empty list restores the built-in `swe`, `data_science`, and `ai_ml_engineer` profiles. Those profiles contain specific technical project experience; use `match_text` to replace it with the recipient's actual experience. Custom IDs without `match_text` get generic descriptions based on the ID. Gemini's preset mismatch examples are selected from role IDs and generated labels, not a separate custom `name`.
- `candidate.target_roles[*].match_text`
  Overrides the built-in semantic profile text for that role.
- `candidate.summary`
  Gives Gemini compact candidate context.
- `candidate.education_status`
  Gives Gemini explicit graduate/student status. This is used for internships, placements, and student-programme judgment.
- `job_preferences.location`
  Selects the location preset used during ATS collection and recipient hard filtering. Supported values are `UK` and `Greece`; omitted profiles default to `UK`. Greece accepts explicit Greek locations such as `Greece`, `Athens`, `Thessaloniki`, and `Remote - Greece`, but not a countryless `Remote` label.
- `job_preferences.target_seniority.max_explicit_years`
  Controls the regex-based experience filter. Blank or `null` restores the default `1`. Ranges use the upper bound: `1-3 years` is treated as `3`. Fixed senior-title and experience-phrase exclusions still apply regardless of this limit.
- `job_preferences.target_seniority.boost_multiplier`
  Multiplies semantic scores for titles that match the configured boost terms. The default is `1.2`; use `1.0` to disable the boost.
- `job_preferences.target_seniority.boost_title_terms`
  Terms that trigger the junior-title boost. An empty list restores the default junior/graduate terms. This is a preference, not a requirement that every job contain one of these words.
- `job_preferences.salary.preferred_max_gbp`
  Soft salary preference ceiling.
- `job_preferences.salary.hard_cap_gbp`
  Salary value where the maximum salary penalty is reached.
- `job_preferences.salary.penalty_strength`
  Maximum salary penalty subtracted from ranking score.
- `eligibility.needs_sponsorship`
  Enables sponsorship-aware output and interpretation.
- `eligibility.work_authorization_summary`
  Gives Gemini compact UK work authorization context, such as visa status, settled/pre-settled status, citizenship, or residency facts.
- `eligibility.check_hard_eligibility`
  Adds stricter Gemini judgment for SC/DV clearance, nationality restrictions, and explicit UK residency requirements. It does not disable earlier authorization or student-eligibility regex checks when off. The authorization summary is supplied to Gemini either way.
- `eligibility.use_sponsor_lookup`
  Adds sponsor-license lookup markers based on the sponsor-company CSV.
- `matching.semantic_threshold`
  Minimum ranking score required after semantic scoring, title boost, and salary penalty. The default is `0.42`. Improve role descriptions before tuning this; try `0.40` to admit weaker matches or `0.45` to require stronger ones, comparing the same jobs via replay. This similarity score is not a hiring probability and cannot override hard-filter rejections.
- `llm_review.extra_screening_guidance`
  Extra natural-language rules injected into Gemini pass one.
- `llm_review.extra_final_ranking_guidance`
  Extra natural-language rules injected into Gemini pass two. See [plain-language instruction examples](PROFILE_CONFIGURATION.md#say-what-matters-to-you). Essential conditions should appear in both passes. These instructions require Gemini to be enabled and cannot recover jobs removed before AI review.

## Main Run Matching Flow

1. Scrape jobs matching the union of enabled recipients' location presets from the configured sources.
2. Drop jobs already seen for that recipient.
3. Apply hard filters:
   - title seniority/eligibility terms; commercial-title exclusions apply only when all target roles are recognized software, data, or AI/ML roles (including the default profiles)
   - the recipient's `job_preferences.location` preset
   - authorization/eligibility mismatch
   - explicit experience requirement above `max_explicit_years`
4. Score remaining jobs against semantic target-role profiles.
5. Apply the configured junior-title boost when the title matches one of the boost terms.
6. Apply the optional salary penalty.
7. Drop jobs below `matching.semantic_threshold`.
8. If Gemini is enabled, run two-pass Gemini screening and reranking.

Support runs skip this matching flow. They use pending backlog rows that already
have stored semantic metadata from an earlier main run.

Recipient diagnostic lines include the review mode and counts. When Gemini fails,
the line also includes `review_error_stage` and a compact `review_error` value so
workflow logs show whether the failure happened during client setup, batch
screening, or final reranking.

The run also prints a final `[run_summary]` line with candidate counts, recipient
outcomes, jobs sent, reviewed jobs, source failures, and Gemini failure stages.
If one source family fails, the run continues with jobs from the successful
source families and records a `[scrape_failure:<source>]` diagnostic line. If
all source families fail, the run stops instead of sending an empty-looking
result.

## Replay Debugging

Save a replay snapshot during a normal run with:

```powershell
python run_all.py --save-run runs/latest.json
```

The snapshot includes scraped jobs, enriched jobs, runtime recipient profiles,
recipient outcomes, and diagnostics. Treat it as local debugging data because it
can include job descriptions and candidate summaries. The default `runs/`
directory is ignored by Git.

Replay ranking and review without scraping, sending email, or marking jobs seen:

```powershell
python tools/replay_run.py runs/latest.json --recipient demo-recipient
```

By default replay uses recipient profiles saved in the snapshot. To tune the
current database profile against the same saved job set, use:

```powershell
python tools/replay_run.py runs/latest.json --profiles current-db --recipient demo-recipient
```

Use `--semantic-only` to temporarily disable Gemini for the replay process, and
`--preview-dir runs/previews` to write local digest HTML/text previews.

## Concurrency

- Recipient processing runs concurrently with a built-in cap of `4`.
- Recipient concurrency is also clamped by the number of enabled profiles, so smaller runs only use the threads they need.
- The implementation enforces a hard upper bound of `8` recipient workers even if the code cap is raised later.
- Gemini calls inside the recipient threads are capped separately at `4` concurrent requests.
- Gemini retrying uses exponential backoff with a shared retry budget of up to `10` minutes per recipient rerank attempt.
- Main-run scraping runs the four source families in parallel:
  - Ashby
  - Greenhouse
  - Lever
  - Next.js
- Each source family still runs serially inside its own scraper.
- Per-job description fetching is unchanged and is not parallelized separately.

This project is intended for a small admin-run setup, roughly up to `8` recipients per run.

## Target Configuration

Supported target config variables:
- `ASHBY_COMPANIES_JSON`
- `GREENHOUSE_BOARD_TOKENS_JSON`
- `LEVER_COMPANIES_JSON`
- `NEXTJS_URLS_JSON`

Target precedence:
1. GitHub Actions variable or environment variable
2. local file such as `ashby_companies.local.json`
3. bundled example file in `examples/`

## Sponsorship Lookup

The default sponsor-company lookup is the checked-in CSV:
- `data/uk_sponsors_companies.csv`

For local overrides, add an ignored file:
- `sponsor_companies.local.csv`

For hosted overrides, set `SPONSOR_COMPANIES_CSV` to a CSV file path in the repository. It is a path override, not raw CSV content.

The CSV only needs a `company_name` column.

If `use_sponsor_lookup` is enabled for a recipient, the app adds a `[Sponsor-licensed]` marker when the company matches the CSV.

## Loading Profiles Into The Database

Create or update grouped recipient profiles directly in:
- `app_config.recipient_profiles`

Recommended workflow:
1. Build the grouped JSON shape shown above.
2. Insert or update each profile in Supabase SQL editor or another Postgres client.
3. Verify enabled rows with:

```sql
select recipient_id, email, enabled
from app_config.recipient_profiles
order by recipient_id;
```

Validate stored profiles before a run with:

```powershell
python tools/validate_recipient_profiles.py
```

Use `--enabled-only` to check only enabled profiles. The validator loads profile
JSON from the configured database and runs the same normalization path used by
the scraper.
