import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from backlog_refetch import refetch_backlog_job_description
from config.recipient_profiles import load_recipient_profiles
from config.target_config import load_configured_targets
from emailer import send_email
from matching.gemini_rerank import get_llm_top_n, rerank_jobs_with_gemini
from matching.ranking import rank_jobs
from scrapers.ashby_scraper import collect_jobs as collect_ashby_jobs
from scrapers.greenhouse_scraper import collect_jobs as collect_greenhouse_jobs
from scrapers.lever_scraper import collect_jobs as collect_lever_jobs
from scrapers.nextjs_scraper import collect_jobs as collect_nextjs_jobs
from scrapers.scrape_diagnostics import ScrapeDiagnostics
from shared.digest import build_digest_payloads
from shared.locations import DEFAULT_LOCATION_PRESET, normalize_location_preset
from sponsorship import enrich_jobs, load_sponsor_company_lookup
from storage import create_storage

RECIPIENT_CONCURRENCY_CAP = 4
MAX_RECIPIENT_CONCURRENCY = 8
SOURCE_FAMILY_CONCURRENCY = 4
RUN_SNAPSHOT_SCHEMA_VERSION = 1


def build_parser():
    parser = argparse.ArgumentParser(
        description="Scrape, rank, optionally rerank, and send job digests."
    )
    parser.add_argument(
        "--save-run",
        help=(
            "Write a local JSON replay snapshot after the run. "
            "The snapshot can include job descriptions and candidate summaries."
        ),
    )
    parser.add_argument(
        "--support-run",
        action="store_true",
        help="Review backlog candidates but queue approved jobs for the next main digest.",
    )
    return parser


def sponsor_aware_profiles(recipient_profiles):
    return any(profile.get("use_sponsor_lookup", False) for profile in recipient_profiles)


def build_run_id():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def required_location_presets(recipient_profiles):
    return list(
        dict.fromkeys(
            normalize_location_preset(
                profile.get("location_preset") or DEFAULT_LOCATION_PRESET
            )
            for profile in recipient_profiles
        )
    )


def collect_all_jobs(targets, diagnostics, location_presets=None):
    source_collectors = [
        (
            "ashby",
            lambda: collect_ashby_jobs(
                set(),
                targets["ashby"],
                diagnostics=diagnostics,
                location_presets=location_presets,
            ),
        ),
        (
            "greenhouse",
            lambda: collect_greenhouse_jobs(
                set(),
                targets["greenhouse"],
                diagnostics=diagnostics,
                location_presets=location_presets,
            ),
        ),
        (
            "lever",
            lambda: collect_lever_jobs(
                set(),
                targets["lever"],
                diagnostics=diagnostics,
                location_presets=location_presets,
            ),
        ),
        (
            "nextjs",
            lambda: collect_nextjs_jobs(
                set(),
                targets["nextjs"],
                diagnostics=diagnostics,
                location_presets=location_presets,
            ),
        ),
    ]

    collected_by_source = {}
    failed_sources = []
    with ThreadPoolExecutor(
        max_workers=min(SOURCE_FAMILY_CONCURRENCY, len(source_collectors))
    ) as executor:
        future_by_source = {
            executor.submit(collector): source_name
            for source_name, collector in source_collectors
        }
        for future in as_completed(future_by_source):
            source_name = future_by_source[future]
            try:
                collected_by_source[source_name] = future.result()
            except Exception as exc:
                failed_sources.append(source_name)
                if diagnostics is not None:
                    diagnostics.record_source_failure(source_name, exc)

    if failed_sources and not collected_by_source:
        raise RuntimeError(
            "All source collection failed: "
            + ", ".join(sorted(failed_sources))
        )

    merged_candidates = []
    seen_urls = set()
    for source_name, _collector in source_collectors:
        for job in collected_by_source.get(source_name) or []:
            job_url = job.get("url")
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            merged_candidates.append(job)

    return merged_candidates


def select_jobs_for_recipient(candidates, recipient_profile, storage, diagnostics):
    seen_urls = storage.load_seen_urls(recipient_profile["id"])
    unseen_candidates = [
        job for job in candidates if job.get("url") not in seen_urls
    ]
    ranked_jobs, ranking_stats = rank_jobs(
        unseen_candidates,
        recipient_profile,
        return_stats=True,
    )
    ranked_jobs_for_review = ranked_jobs[: get_llm_top_n(len(ranked_jobs))]
    ranking_audit_rows = ranking_stats.pop("audit_rows", [])
    review_result = rerank_jobs_with_gemini(ranked_jobs_for_review, recipient_profile)
    semantic_rejected_seen_jobs = semantic_below_threshold_seen_jobs(
        ranking_audit_rows
    )
    review_result["seen_jobs"] = merge_seen_jobs(
        review_result["reviewed_jobs"],
        semantic_rejected_seen_jobs,
    )
    review_result["audit_rows"] = build_review_audit_rows(
        ranking_audit_rows,
        review_result,
    )
    review_result["job_state_rows"] = build_job_state_rows(
        review_result["audit_rows"],
    )
    review_result["seen_recorded_count"] = count_seen_job_state_rows(
        review_result["job_state_rows"],
        fallback_count=len(review_result["seen_jobs"]),
    )
    diagnostics.record_recipient_summary(
        recipient_profile["id"],
        {
            **ranking_stats,
            "input_jobs": len(candidates),
            "seen_skipped_jobs": len(candidates) - len(unseen_candidates),
            "ranked_jobs_passed_to_review": len(ranked_jobs_for_review),
            "ranked_jobs_not_passed_to_review": (
                len(ranked_jobs) - len(ranked_jobs_for_review)
            ),
            "review_mode": review_result["review_mode"],
            "reviewed_jobs": len(review_result["reviewed_jobs"]),
            "seen_recorded_jobs": review_result["seen_recorded_count"],
            "llm_shortlisted_jobs": review_result.get("llm_shortlisted_jobs"),
            "gemini_reviewed_jobs": review_result.get("gemini_reviewed_jobs"),
            "review_error": review_result.get("review_error"),
            "review_error_stage": review_result.get("review_error_stage"),
            "recipient_seen_urls": len(seen_urls),
        },
    )
    return review_result


def select_backlog_jobs_for_support_recipient(
    recipient_profile,
    storage,
    diagnostics,
    run_id=None,
):
    recipient_id = recipient_profile["id"]
    if not hasattr(storage, "load_pending_job_backlog"):
        raise RuntimeError("Support runs require pending backlog storage support.")

    pending_rows = storage.load_pending_job_backlog(recipient_id)
    refetch_statuses = Counter()
    expired_rows = 0
    jobs_for_review = []

    for row in pending_rows:
        job_url = row.get("job_url")
        if not job_url:
            continue

        refetch_result = refetch_backlog_job_description(job_url)
        refetch_status = refetch_result.get("status") or "temporary_failure"
        refetch_statuses[refetch_status] += 1

        if refetch_status == "ok":
            jobs_for_review.append(
                backlog_row_to_gemini_job(
                    row,
                    refetch_result.get("description", ""),
                )
            )
            continue

        if refetch_status == "dead" and hasattr(storage, "mark_pending_job_expired"):
            expired_rows += storage.mark_pending_job_expired(
                recipient_id,
                job_url,
                run_id=run_id,
                reason=refetch_result.get("reason"),
            )

    review_result = rerank_jobs_with_gemini(jobs_for_review, recipient_profile)
    review_result["seen_jobs"] = review_result.get("reviewed_jobs", [])
    review_result["audit_rows"] = list(review_result.get("audit_rows") or [])
    review_result["job_state_rows"] = build_job_state_rows(
        review_result["audit_rows"],
    )
    review_result["seen_recorded_count"] = count_seen_job_state_rows(
        review_result["job_state_rows"],
        fallback_count=len(review_result.get("seen_jobs") or []),
    )
    review_result["backlog_rows_loaded"] = len(pending_rows)
    review_result["backlog_rows_refetched"] = sum(refetch_statuses.values())
    review_result["backlog_rows_expired"] = expired_rows
    review_result["backlog_refetch_statuses"] = dict(refetch_statuses)

    diagnostics.record_recipient_summary(
        recipient_id,
        {
            "input_jobs": 0,
            "seen_skipped_jobs": 0,
            "ranked_jobs": 0,
            "ranked_jobs_passed_to_review": len(jobs_for_review),
            "ranked_jobs_not_passed_to_review": 0,
            "review_mode": review_result["review_mode"],
            "reviewed_jobs": len(review_result["reviewed_jobs"]),
            "seen_recorded_jobs": review_result["seen_recorded_count"],
            "llm_shortlisted_jobs": review_result.get("llm_shortlisted_jobs"),
            "gemini_reviewed_jobs": review_result.get("gemini_reviewed_jobs"),
            "review_error": review_result.get("review_error"),
            "review_error_stage": review_result.get("review_error_stage"),
            "backlog_rows_loaded": len(pending_rows),
            "backlog_rows_refetched": sum(refetch_statuses.values()),
            "backlog_rows_expired": expired_rows,
            "backlog_refetch_statuses": dict(refetch_statuses),
        },
    )
    return review_result


def semantic_below_threshold_seen_jobs(ranking_audit_rows):
    return [
        {
            "url": row.get("job_url", ""),
            "source": row.get("source_type", ""),
            "target_value": row.get("target_value", ""),
            "company": row.get("company_name", ""),
            "title": row.get("title", ""),
            "location": row.get("location", ""),
        }
        for row in ranking_audit_rows
        if row.get("classification") == "semantic_below_threshold"
        and row.get("job_url")
    ]


def merge_seen_jobs(*job_groups):
    merged_jobs = []
    seen_urls = set()
    for jobs in job_groups:
        for job in jobs or []:
            job_url = job.get("url")
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            merged_jobs.append(job)
    return merged_jobs


def merge_digest_jobs(*job_groups):
    return merge_seen_jobs(*job_groups)


def build_review_audit_rows(ranking_audit_rows, review_result):
    review_audit_rows = list(review_result.get("audit_rows") or [])
    review_audit_urls = {
        row.get("job_url")
        for row in review_audit_rows
        if row.get("job_url")
    }
    semantic_sent_urls = {
        job.get("url")
        for job in (review_result.get("jobs_to_send") or [])
        if job.get("url")
    }
    review_mode = review_result.get("review_mode", "")
    merged_rows = []

    for row in ranking_audit_rows:
        job_url = row.get("job_url")
        classification = row.get("classification")
        if (
            classification == "semantic_above_threshold"
            and job_url in review_audit_urls
        ):
            continue

        if classification == "semantic_above_threshold":
            metadata = dict(row.get("metadata") or {})
            if review_mode == "semantic":
                selected = job_url in semantic_sent_urls
                metadata["semantic_selected_for_digest"] = selected
                row = {
                    **row,
                    "metadata": metadata,
                    "sent": selected,
                    "seen_recorded": selected,
                }
            elif review_mode in {"gemini", "gemini_failed"}:
                metadata["selected_for_gemini"] = False
                row = {**row, "metadata": metadata}
        elif classification == "semantic_below_threshold":
            row = {**row, "seen_recorded": True}

        merged_rows.append(row)

    return merged_rows + review_audit_rows


def build_job_state_rows(audit_rows):
    state_rows = []
    for row in audit_rows or []:
        state_row = job_state_row_from_audit_row(row)
        if state_row is not None:
            state_rows.append(state_row)
    return state_rows


def backlog_row_to_gemini_job(row, description):
    return {
        "url": row.get("job_url", ""),
        "company": row.get("company_name", ""),
        "title": row.get("title", ""),
        "location": row.get("location", ""),
        "source": row.get("source_type", ""),
        "target_value": row.get("target_value", ""),
        "description": description or "",
        "semantic_rank": row.get("semantic_rank"),
        "raw_embedding_score": row.get("raw_embedding_score"),
        "ranking_score": row.get("semantic_score"),
        "semantic_threshold": row.get("semantic_threshold"),
        "salary_upper_bound_gbp": row.get("salary_upper_bound_gbp"),
        "fit_summary": row.get("semantic_fit_hint", ""),
    }


def mark_result_jobs_queued_for_digest(review_result):
    queued_jobs = list(review_result.get("jobs_to_send") or [])
    queued_urls = {job.get("url") for job in queued_jobs if job.get("url")}
    if not queued_urls:
        review_result["queued_jobs"] = []
        review_result["jobs_queued_count"] = 0
        return review_result

    review_result["audit_rows"] = [
        mark_audit_row_queued_for_digest(row, queued_urls)
        for row in review_result.get("audit_rows", [])
    ]
    review_result["job_state_rows"] = build_job_state_rows(
        review_result["audit_rows"],
    )
    review_result["seen_recorded_count"] = count_seen_job_state_rows(
        review_result["job_state_rows"],
        fallback_count=len(review_result.get("seen_jobs") or []),
    )
    review_result["queued_jobs"] = queued_jobs
    review_result["jobs_queued_count"] = len(queued_jobs)
    review_result["jobs_to_send"] = []
    review_result["jobs_sent_count"] = 0
    return review_result


def mark_audit_row_queued_for_digest(row, queued_urls):
    if row.get("job_url") not in queued_urls or not row.get("sent"):
        return row

    classification = row.get("classification", "")
    if classification == "gemini_pass2_approved_sent_seen":
        classification = "gemini_pass2_approved_queued_seen"
    elif classification == "semantic_above_threshold":
        classification = "semantic_above_threshold_queued_seen"

    metadata = dict(row.get("metadata") or {})
    metadata["queued_for_digest"] = True
    return {
        **row,
        "classification": classification,
        "sent": False,
        "metadata": metadata,
    }


def count_seen_job_state_rows(job_state_rows, fallback_count=0):
    if not job_state_rows:
        return fallback_count
    return sum(1 for row in job_state_rows if row.get("is_seen"))


def job_state_row_from_audit_row(row):
    classification = row.get("classification", "")
    if row.get("review_family") == "hard_filter" or classification == "hard_filtered":
        return None

    is_seen = bool(row.get("seen_recorded", False))
    state_classification = classification

    if classification == "semantic_above_threshold":
        if is_seen or row.get("sent"):
            state_classification = "semantic_above_threshold_seen"
            is_seen = True
        else:
            state_classification = "semantic_above_threshold_not_reviewed"
    elif classification == "gemini_pass1_rejected_final_failed_not_seen":
        state_classification = "gemini_pass1_rejected_seen"
        is_seen = True

    return {
        "job_url": row.get("job_url", ""),
        "source_type": row.get("source_type", ""),
        "target_value": row.get("target_value", ""),
        "company_name": row.get("company_name", ""),
        "title": row.get("title", ""),
        "location": row.get("location", ""),
        "is_seen": is_seen,
        "processing_status": "processed" if is_seen else "pending_review",
        "review_family": row.get("review_family"),
        "classification": state_classification,
        "stage": row.get("stage"),
        "semantic_rank": row.get("semantic_rank"),
        "raw_embedding_score": row.get("raw_embedding_score"),
        "semantic_score": row.get("semantic_score"),
        "semantic_threshold": row.get("semantic_threshold"),
        "semantic_fit_hint": (
            row.get("semantic_fit_hint") or row.get("semantic_fit_summary")
        ),
        "salary_upper_bound_gbp": row.get("salary_upper_bound_gbp"),
        "sent": bool(row.get("sent", False)),
        "review_error_stage": row.get("review_error_stage"),
    }


def send_digest(recipient_profile, jobs):
    payloads = build_digest_payloads(jobs, recipient_profile)

    for index, payload in enumerate(payloads, start=1):
        subject = f"Job digest: {len(jobs)} new job matches"
        if len(payloads) > 1:
            subject += f" ({index}/{len(payloads)})"
        send_email(
            subject,
            payload["text"],
            recipient_profile["email"],
            html_body=payload["html"],
        )


def initialize_storage(storage):
    storage.ensure_schema()


def require_database_in_github_actions():
    if os.getenv("GITHUB_ACTIONS") == "true" and not os.getenv("DATABASE_URL"):
        raise RuntimeError(
            "GitHub Actions runs require DATABASE_URL so seen jobs persist across runs."
        )


def recipient_worker_count(recipient_profiles):
    if not recipient_profiles:
        return 1

    configured = max(1, min(RECIPIENT_CONCURRENCY_CAP, MAX_RECIPIENT_CONCURRENCY))
    return min(len(recipient_profiles), configured)


def process_recipient(
    recipient_profile,
    candidates,
    storage,
    diagnostics,
    run_id=None,
    support_run=False,
):
    run_id = run_id or build_run_id()
    if support_run:
        review_result = select_backlog_jobs_for_support_recipient(
            recipient_profile,
            storage,
            diagnostics,
            run_id=run_id,
        )
    else:
        review_result = select_jobs_for_recipient(
            candidates,
            recipient_profile,
            storage,
            diagnostics,
        )
    jobs_to_send = review_result["jobs_to_send"]
    reviewed_jobs = review_result["reviewed_jobs"]
    seen_jobs = review_result.get("seen_jobs", reviewed_jobs)

    if support_run:
        if jobs_to_send and hasattr(storage, "store_digest_queue_jobs"):
            storage.store_digest_queue_jobs(
                recipient_profile["id"],
                run_id,
                jobs_to_send,
            )
        review_result = mark_result_jobs_queued_for_digest(review_result)
    else:
        queued_jobs = []
        if hasattr(storage, "load_digest_queue_jobs"):
            queued_jobs = storage.load_digest_queue_jobs(recipient_profile["id"])
        digest_jobs = merge_digest_jobs(jobs_to_send, queued_jobs)
        if digest_jobs:
            send_digest(recipient_profile, digest_jobs)
        if queued_jobs and hasattr(storage, "mark_digest_queue_jobs_sent"):
            storage.mark_digest_queue_jobs_sent(
                recipient_profile["id"],
                [job.get("url") for job in queued_jobs],
                run_id=run_id,
            )
        review_result["queued_jobs_delivered"] = queued_jobs
        review_result["jobs_sent_count"] = len(digest_jobs)
        review_result["jobs_to_send"] = digest_jobs

    job_state_rows = review_result.get("job_state_rows") or []
    if job_state_rows and hasattr(storage, "store_job_state_rows"):
        storage.store_job_state_rows(
            recipient_profile["id"],
            run_id,
            job_state_rows,
        )
    elif seen_jobs:
        storage.store_seen_jobs(recipient_profile["id"], seen_jobs)
    if review_result.get("audit_rows") and hasattr(storage, "store_review_audit_rows"):
        storage.store_review_audit_rows(
            recipient_profile["id"],
            run_id,
            review_result["audit_rows"],
        )
    return review_result


def process_recipients(
    recipient_profiles,
    candidates,
    storage,
    diagnostics,
    run_id=None,
    support_run=False,
):
    run_id = run_id or build_run_id()
    worker_count = recipient_worker_count(recipient_profiles)
    if worker_count == 1:
        return [
            process_recipient(
                recipient_profile,
                candidates,
                storage,
                diagnostics,
                run_id,
                support_run=support_run,
            )
            for recipient_profile in recipient_profiles
        ]

    recipient_results = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_by_recipient_id = {
            executor.submit(
                process_recipient,
                recipient_profile,
                candidates,
                storage,
                diagnostics,
                run_id,
                support_run=support_run,
            ): recipient_profile["id"]
            for recipient_profile in recipient_profiles
        }
        for future in as_completed(future_by_recipient_id):
            recipient_id = future_by_recipient_id[future]
            try:
                recipient_results.append(future.result())
            except Exception as exc:
                raise RuntimeError(
                    f"Recipient processing failed for {recipient_id}: {exc}"
                ) from exc

    return recipient_results


def build_run_summary(candidates, enriched_candidates, recipient_profiles, results):
    review_modes = Counter(
        result.get("review_mode", "unknown") for result in results
    )
    gemini_failure_stages = Counter(
        result.get("review_error_stage") or "unknown"
        for result in results
        if result.get("review_mode") == "gemini_failed"
    )
    support_backlog_refetch_statuses = Counter()
    for result in results:
        support_backlog_refetch_statuses.update(
            result.get("backlog_refetch_statuses") or {}
        )

    return {
        "candidate_jobs": len(candidates),
        "enriched_jobs": len(enriched_candidates),
        "recipient_count": len(recipient_profiles),
        "jobs_sent": sum(
            result.get("jobs_sent_count", len(result.get("jobs_to_send") or []))
            for result in results
        ),
        "reviewed_jobs": sum(
            len(result.get("reviewed_jobs") or []) for result in results
        ),
        "review_modes": dict(review_modes),
        "gemini_failure_stages": dict(gemini_failure_stages),
        "jobs_queued": sum(result.get("jobs_queued_count", 0) for result in results),
        "queued_jobs_delivered": sum(
            len(result.get("queued_jobs_delivered") or []) for result in results
        ),
        "support_backlog_candidates": sum(
            result.get("backlog_rows_loaded", 0) for result in results
        ),
        "support_backlog_refetched": sum(
            result.get("backlog_rows_refetched", 0) for result in results
        ),
        "support_backlog_expired": sum(
            result.get("backlog_rows_expired", 0) for result in results
        ),
        "support_backlog_refetch_statuses": dict(support_backlog_refetch_statuses),
    }


def build_run_snapshot(
    candidates,
    enriched_candidates,
    recipient_profiles,
    recipient_results,
    run_summary,
    diagnostics,
    run_id=None,
):
    return {
        "schema_version": RUN_SNAPSHOT_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
        "enriched_candidates": enriched_candidates,
        "recipient_profiles": recipient_profiles,
        "recipient_results": recipient_results,
        "recipient_summaries": list(
            getattr(diagnostics, "recipient_summaries", [])
        ),
        "source_failures": list(getattr(diagnostics, "source_failures", [])),
        "run_summary": run_summary,
    }


def write_run_snapshot(path, snapshot):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return output_path


def main(argv=None):
    args = build_parser().parse_args(argv)
    run_id = build_run_id()
    require_database_in_github_actions()

    storage = create_storage()
    initialize_storage(storage)
    diagnostics = ScrapeDiagnostics(
        enabled=os.getenv("JOB_SCRAPER_DIAGNOSTICS", "1") != "0"
    )
    recipient_profiles = load_recipient_profiles(storage=storage)

    if args.support_run:
        candidates = []
        enriched_candidates = []
    else:
        targets = load_configured_targets()
        sponsor_company_lookup = load_sponsor_company_lookup()
        diagnostics.record_sponsor_lookup_summary(len(sponsor_company_lookup))
        if sponsor_aware_profiles(recipient_profiles) and not sponsor_company_lookup:
            print(
                "Warning: sponsorship-aware recipient profiles are enabled, but no sponsor "
                "company lookup data was loaded."
            )

        candidates = collect_all_jobs(
            targets,
            diagnostics,
            location_presets=required_location_presets(recipient_profiles),
        )
        enriched_candidates = enrich_jobs(candidates, sponsor_company_lookup)

    recipient_results = process_recipients(
        recipient_profiles,
        enriched_candidates,
        storage,
        diagnostics,
        run_id,
        support_run=args.support_run,
    )
    run_summary = build_run_summary(
        candidates,
        enriched_candidates,
        recipient_profiles,
        recipient_results,
    )
    diagnostics.record_run_summary(run_summary)

    if args.save_run:
        output_path = write_run_snapshot(
            args.save_run,
            build_run_snapshot(
                candidates,
                enriched_candidates,
                recipient_profiles,
                recipient_results,
                run_summary,
                diagnostics,
                run_id=run_id,
            ),
        )
        print(f"[run_snapshot] path={output_path.resolve()}")


if __name__ == "__main__":
    main()
