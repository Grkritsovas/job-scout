# Intended Behavior

The scraper has two run modes: main runs that discover and review new jobs, and
support runs that retry stored pending backlog.

## Job State And Backlog

The backlog feature itself is simple:

- A job is scraped.
- For each recipient, we classify it:
  - hard filtered: don't store as seen, cheap to reject again
  - semantic below threshold: store as processed/seen, skip next time
  - semantic above threshold but not in top N: store as pending/backlog, support run can pick it up later
  - Gemini failed before reviewing: store as pending/backlog
  - pending backlog URL is dead: store as expired/seen
  - Gemini reviewed/rejected/sent: store as processed/seen
- Extra scheduled runs check: "are there pending backlog jobs?" If no, exit. If yes, run.

The source of truth for this workflow state is `recipient_seen_jobs`
(`app_config.recipient_seen_jobs` on Postgres/Supabase). Despite the historic
table name, it now stores per-recipient job processing state:

- `is_seen=true` means the recipient/job pair should be skipped in future runs.
- `is_seen=false` means the recipient/job pair can be reconsidered. Normal
  backlog classifications can trigger a support run; `manual_reset_unseen`
  instead waits for rediscovery in a main run.
- `classification`, `review_family`, `stage`, `run_id`, and score columns explain
  why the row is processed or pending.

Hard-filtered jobs are not stored in this table. They are deterministic and cheap
to reject again, and storing every hard-filtered job would add a lot of low-value
rows.

## Support Runs

The workflow has normal scheduled runs and support scheduled runs.

Normal runs always scrape, rank, review, send, and store state.

Support runs first check the database for recent pending rows in
`recipient_seen_jobs`. If no pending rows exist, the workflow exits before
installing full scraper dependencies.

If pending rows exist, the support run is backlog-only. It does not scrape full
source families and does not run hard filters or semantic ranking. For each
recipient it loads pending backlog rows, refetches the current job URL, rebuilds
a compact Gemini job from stored metadata plus the freshly fetched description,
and sends those jobs to Gemini review.

Temporary URL refetch failures, such as timeouts, connection errors, rate limits,
and 5xx responses, remain pending so a later support run can try again. Clearly
dead URLs, such as 404 or 410 pages, are marked expired/seen and no longer count
as backlog.

Support runs are review-only for email delivery. If Gemini approves jobs during a
support run, those jobs are stored in `recipient_digest_queue` instead of being
emailed immediately. The next main run sends queued approved jobs together with
that run's newly approved jobs, then marks the queued rows as sent. This keeps
backlog processing active without turning support schedules into extra digest
emails.

## Review Audit

`recipient_review_audit` (`app_config.recipient_review_audit` on
Postgres/Supabase) is for human inspection. It records compact review history for
semantic decisions, hard-filter samples, and Gemini decisions.

The audit is not the workflow source of truth. It can be pruned for readability
and storage control. The job state table decides whether a recipient/job pair is
skipped or retried.

Audit rows intentionally avoid full recipient profile JSON and full job
descriptions. They keep job metadata, scores, thresholds, categories, concise
Gemini reasons, and short evidence snippets.

Support runs also avoid persisting full descriptions. Freshly refetched
descriptions are used for the current Gemini review only.

## Semantic Matching

Semantic matching is a retrieval layer. Its job is to narrow a large scrape down
to a plausible shortlist before Gemini review.

The semantic stage uses role-focused text rather than the entire posting where
possible. It trims common low-signal sections such as benefits, culture,
diversity statements, legal footers, and application-process boilerplate before
embedding the job text.

An optional `candidate.cv` contains the plain text of the application CV. The
semantic matcher splits it into overlapping 80-word passages, then selects up
to three passages per target profile with role similarity of at least 0.25.
These selections are cached for the current role text and CV. It compares the
job against those passages and takes the greater of the original role score
and an 80% role / 20% mean CV-evidence score. Unrelated or missing CV evidence
leaves the original score unchanged. Existing thresholds, title boosts, salary
penalties, hard filters, and top-N limits still apply; CV evidence can change
which jobs reach review through those thresholds and limits.

The audit stores both:

- `raw_embedding_score`: the embedding similarity before title boosts and salary
  penalties.
- `semantic_score`: the final score after boosts and penalties.

The review UI can sort by either score so borderline retrieval behavior can be
inspected.

## Gemini Review

When `GEMINI_API_KEY` is configured, Gemini review is mandatory for ranked jobs
on main runs and refetched backlog jobs on support runs. There is no semantic
fallback if Gemini fails.

Gemini uses a two-pass review:

- pass 1 screens semantic candidates in batches
- pass 2 globally reranks pass-1 approved candidates

Both passes receive the full `candidate.cv` when provided, alongside the story,
target profiles, and existing candidate context. The CV is primary evidence of
what the application demonstrates; target profiles describe desired work, and
the story supplies additional context. Review distinguishes evidence in the CV
from story-only claims and does not assume the application will be rewritten.
Missing skills remain unknown rather than confirmed gaps. Profiles without a
CV continue to use the existing summary and target-role context.

Successful Gemini decisions are stored as processed/seen whether the job is sent
or rejected, so the same borderline jobs do not repeatedly return every run.
Temporary Gemini failures are stored as pending/backlog instead.

## Admin UI

`python admin_ui.py` starts a local admin UI for database-backed recipient
profiles and review audit browsing after `DATABASE_URL` is set. SQLite is only
used when a SQLite URL is explicitly passed to the command.

The profile editor is schema-shaped rather than free-form JSON. Keys are locked
into the canonical structure, values are editable, and the generated JSON preview
shows what will be saved. This is meant to reduce accidental profile corruption
while still allowing practical profile tuning.

The UI can validate profiles through the same runtime loader used by the scraper,
save profile versions, compare previous versions, and restore older versions.

Review Audit has an explicit **Unmark** action on rows recorded as seen. It
clears the authoritative seen flag for only the selected recipient/job pair,
sets `processing_status=awaiting_main_run` and
`classification=manual_reset_unseen`, and clears stale semantic scores. Any
queued approval for that pair is removed in the same transaction. Previous
review audit records, other recipients' state, and historical `sent` flags are
preserved. Missing markers or already-unseen rows are no-ops. Normal job-state
upserts still preserve seen flags; only this explicit reset clears them.

The job is eligible for the full matching pipeline on rediscovery in a main
scrape. It is excluded from the support-run backlog so old retrieval decisions
do not bypass reassessment. Unmarking does not review or email immediately; a
previously emailed job may be emailed again after approval.

The UI does not edit GitHub secrets or local recipient JSON files.
