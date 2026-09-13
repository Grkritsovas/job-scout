# Job Scraper
### For Entry-Level and Junior Roles in Tech

Scrapes public job boards, ranks roles against configurable recipient profiles, and sends grouped email digests.
<p align="center">
  <img src="examples/example_digest.png" alt="Description" width="600">
</p>


## Intended Usage

This project is primarily meant to run as a scheduled GitHub Actions workflow with persistent seen-job storage.

Typical setup:
- fork the repo
- configure GitHub Actions secrets and variables
- let the workflow run on schedule

The intended scale is a small admin-run setup, roughly up to 8 recipients per run.

## What It Does

- loads public job-board targets from config
- loads recipient profiles from the database
- ingests API data from Ashby, Greenhouse, Lever, and selected Next.js boards
- ranks jobs separately for each recipient profile with semantic matching
- optionally reranks top semantic matches with Gemini for stricter final selection
- skips jobs already reviewed for that recipient
- stores compact review audit records for semantic and Gemini decisions
- sends grouped email digests
<p align="center">
  <img src="examples/job_scraper_workflow.gif" alt="Job scraper workflow animation" width="512">
</p>

## Matching Modes

- semantic-only mode
  Used when `GEMINI_API_KEY` is not set.
- semantic + Gemini rerank mode
  Used when `GEMINI_API_KEY` is set.

Important Gemini behavior:
- reviewed jobs are stored as seen, even if Gemini rejects them
- if Gemini is enabled but unavailable, the app does not fall back to the semantic shortlist for that run
- the first Gemini-enabled run can cost more because many unseen jobs may be reviewed at once

## Setup

Recommended setup:
1. Fork the repo.
2. Create a Postgres database and save the connection string as `DATABASE_URL`.
3. Add your sender email and app password.
4. Load recipient profiles into `app_config.recipient_profiles`.
5. Optionally add `GEMINI_API_KEY`.
6. Run the workflow manually once, then enable the schedule.

The full step-by-step setup, variable reference, database-backed recipient profile shape, and target override documentation are in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

To describe the jobs you want, introduce yourself, and set your preferences, follow [Personalizing Your Job Search](docs/PROFILE_CONFIGURATION.md). It includes plain-language examples for marketing, customer service, HR, and software roles.

Starter config files and example shapes are in [examples/README.md](examples/README.md).

Internal architecture notes, contributor workflows, and agent guardrails are in [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Local Run

Local runs are mainly for testing, debugging, or tuning config before pushing changes.

1. Create and activate a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Set the needed environment variables.
4. Run `python run_all.py`.

Recipient profiles are database-only. The app does not read `recipient_profiles.local.json` at runtime. For realistic local runs, point `DATABASE_URL` at the same Postgres database you use in GitHub Actions, or seed the local SQLite `recipient_profiles` table yourself.

## Extra Tools

- `python manage_targets.py list`
- `python manage_targets.py list ashby`
- `python tools/validate_recipient_profiles.py --enabled-only`
- `python admin_ui.py` after setting `DATABASE_URL`
- `python run_all.py --save-run runs/latest.json`
- `python tools/replay_run.py runs/latest.json --recipient demo-recipient`

## Database

`app_config.recipient_profiles` stores recipient config, `app_config.recipient_seen_jobs` stores per-recipient job processing state, and `app_config.recipient_review_audit` stores compact semantic/Gemini review audit rows.

See [docs/INTENDED_BEHAVIOR.md](docs/INTENDED_BEHAVIOR.md) for the intended behavior of job state, support runs, review audit, semantic matching, Gemini review, and the admin UI.

## Acknowledgements

OpenAI Codex / GPT-5.4 for development assistance.

Sample sponsor list from [Borderless](https://uk-sponsors.getborderless.co.uk/sponsors), which states that data is sourced from GOV.UK.

## License

This project is licensed under the [MIT License](LICENSE).

## Responsible Use

- Use public job boards only.
- Keep request volume low.
- Respect source terms and policies.
- Do not automate applications or scrape non-public data.
