import json
from pathlib import Path
import unittest
from unittest.mock import patch

import matching.gemini_rerank as gemini_rerank_module
from run_all import (
    MAX_RECIPIENT_CONCURRENCY,
    RECIPIENT_CONCURRENCY_CAP,
    RUN_SNAPSHOT_SCHEMA_VERSION,
    backlog_row_to_gemini_job,
    build_job_state_rows,
    build_run_summary,
    build_run_snapshot,
    collect_all_jobs,
    main,
    merge_seen_jobs,
    process_recipient,
    recipient_worker_count,
    required_location_presets,
    select_jobs_for_recipient,
    semantic_below_threshold_seen_jobs,
    write_run_snapshot,
)


def make_job(index):
    return {
        "company": "Example",
        "title": f"Software Engineer {index}",
        "url": f"https://example.com/job-{index}",
        "description": "Build Python APIs.",
        "location": "London",
        "source": "example",
        "target_value": "example",
    }


class FakeStorage:
    def __init__(self, seen_urls):
        self._seen_urls = set(seen_urls)
        self.stored = []
        self.state_rows = []
        self.audit_rows = []
        self.queued_jobs = []
        self.queue_jobs_to_load = []
        self.marked_sent = []
        self.pending_backlog_rows = []
        self.expired_jobs = []

    def load_seen_urls(self, recipient_id):
        return set(self._seen_urls)

    def store_seen_jobs(self, recipient_id, jobs):
        self.stored.append((recipient_id, list(jobs)))

    def store_job_state_rows(self, recipient_id, run_id, rows):
        self.state_rows.append((recipient_id, run_id, list(rows)))

    def store_digest_queue_jobs(self, recipient_id, run_id, jobs):
        self.queued_jobs.append((recipient_id, run_id, list(jobs)))

    def load_digest_queue_jobs(self, recipient_id):
        return list(self.queue_jobs_to_load)

    def mark_digest_queue_jobs_sent(self, recipient_id, job_urls, run_id=None):
        self.marked_sent.append((recipient_id, list(job_urls), run_id))

    def store_review_audit_rows(self, recipient_id, run_id, rows):
        self.audit_rows.append((recipient_id, run_id, list(rows)))

    def load_pending_job_backlog(self, recipient_id, limit=None):
        rows = [
            row
            for row in self.pending_backlog_rows
            if row.get("recipient_id", recipient_id) == recipient_id
        ]
        if limit is not None:
            return rows[:limit]
        return rows

    def mark_pending_job_expired(self, recipient_id, job_url, run_id=None, reason=None):
        self.expired_jobs.append((recipient_id, job_url, run_id, reason))
        return 1


class FakeDiagnostics:
    def __init__(self):
        self.calls = []
        self.source_failures = []
        self.recipient_summaries = []

    def record_recipient_summary(self, recipient_id, summary):
        self.calls.append((recipient_id, summary))
        self.recipient_summaries.append({"recipient_id": recipient_id, **summary})

    def record_source_failure(self, source, error):
        self.source_failures.append((source, str(error)))


class RunAllTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/.tmp_run_all")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for child in self.test_dir.glob("*"):
            child.unlink()
        self.test_dir.rmdir()

    def test_collect_all_jobs_dedupes_urls_after_parallel_source_collection(self):
        shared_job = make_job(1)
        ashby_job = {**make_job(2), "source": "ashby", "target_value": "ashby"}
        lever_job = {**make_job(3), "source": "lever", "target_value": "lever"}
        targets = {
            "ashby": ["ashby-company"],
            "greenhouse": ["greenhouse-board"],
            "lever": ["lever-company"],
            "nextjs": ["nextjs-site"],
        }

        with (
            patch(
                "run_all.collect_ashby_jobs",
                return_value=[shared_job, ashby_job],
            ) as ashby_mock,
            patch(
                "run_all.collect_greenhouse_jobs",
                return_value=[shared_job],
            ) as greenhouse_mock,
            patch(
                "run_all.collect_lever_jobs",
                return_value=[lever_job],
            ) as lever_mock,
            patch("run_all.collect_nextjs_jobs", return_value=[]) as nextjs_mock,
        ):
            jobs = collect_all_jobs(
                targets,
                diagnostics=None,
                location_presets=["UK", "Greece"],
            )

        self.assertEqual(
            [
                "https://example.com/job-1",
                "https://example.com/job-2",
                "https://example.com/job-3",
            ],
            [job["url"] for job in jobs],
        )
        for mock in (ashby_mock, greenhouse_mock, lever_mock, nextjs_mock):
            self.assertIsInstance(mock.call_args.args[0], set)
            self.assertEqual(
                ["UK", "Greece"],
                mock.call_args.kwargs["location_presets"],
            )

    def test_required_location_presets_defaults_to_uk_and_dedupes(self):
        self.assertEqual(
            ["UK", "Greece"],
            required_location_presets(
                [
                    {"id": "one"},
                    {"id": "two", "location_preset": "Greece"},
                    {"id": "three", "location_preset": "UK"},
                ]
            ),
        )

    def test_collect_all_jobs_keeps_successful_sources_when_one_source_fails(self):
        ashby_job = {**make_job(1), "source": "ashby", "target_value": "ashby"}
        lever_job = {**make_job(2), "source": "lever", "target_value": "lever"}
        targets = {
            "ashby": ["ashby-company"],
            "greenhouse": ["greenhouse-board"],
            "lever": ["lever-company"],
            "nextjs": ["nextjs-site"],
        }
        diagnostics = FakeDiagnostics()

        with (
            patch("run_all.collect_ashby_jobs", return_value=[ashby_job]),
            patch(
                "run_all.collect_greenhouse_jobs",
                side_effect=RuntimeError("boom"),
            ),
            patch("run_all.collect_lever_jobs", return_value=[lever_job]),
            patch("run_all.collect_nextjs_jobs", return_value=[]),
        ):
            jobs = collect_all_jobs(targets, diagnostics=diagnostics)

        self.assertEqual(
            ["https://example.com/job-1", "https://example.com/job-2"],
            [job["url"] for job in jobs],
        )
        self.assertEqual([("greenhouse", "boom")], diagnostics.source_failures)

    def test_collect_all_jobs_fails_when_every_source_fails(self):
        targets = {
            "ashby": ["ashby-company"],
            "greenhouse": ["greenhouse-board"],
            "lever": ["lever-company"],
            "nextjs": ["nextjs-site"],
        }
        diagnostics = FakeDiagnostics()

        with (
            patch("run_all.collect_ashby_jobs", side_effect=RuntimeError("ashby")),
            patch(
                "run_all.collect_greenhouse_jobs",
                side_effect=RuntimeError("greenhouse"),
            ),
            patch("run_all.collect_lever_jobs", side_effect=RuntimeError("lever")),
            patch("run_all.collect_nextjs_jobs", side_effect=RuntimeError("nextjs")),
        ):
            with self.assertRaisesRegex(RuntimeError, "All source collection failed"):
                collect_all_jobs(targets, diagnostics=diagnostics)

        self.assertEqual(
            {"ashby", "greenhouse", "lever", "nextjs"},
            {source for source, _error in diagnostics.source_failures},
        )

    def test_select_jobs_for_recipient_skips_seen_urls_before_ranking(self):
        candidates = [make_job(1), make_job(2), make_job(3)]
        recipient_profile = {"id": "george"}
        storage = FakeStorage({"https://example.com/job-2"})
        diagnostics = FakeDiagnostics()

        ranked_jobs = [make_job(1), make_job(3)]
        ranking_stats = {
            "input_jobs": len(ranked_jobs),
            "hard_filtered_jobs": 1,
            "below_threshold_jobs": 0,
            "ranked_jobs": len(ranked_jobs),
            "hard_filter_reasons": {"title_seniority": 1},
        }
        review_result = {
            "jobs_to_send": [make_job(1)],
            "reviewed_jobs": [make_job(1)],
            "review_mode": "gemini",
            "llm_shortlisted_jobs": 1,
            "gemini_reviewed_jobs": 2,
            "review_error": None,
        }

        with (
            patch(
                "run_all.rank_jobs",
                return_value=(ranked_jobs, ranking_stats),
            ) as rank_mock,
            patch(
                "run_all.rerank_jobs_with_gemini",
                return_value=review_result,
            ) as rerank_mock,
        ):
            result = select_jobs_for_recipient(
                candidates,
                recipient_profile,
                storage,
                diagnostics,
            )

        ranked_input_jobs = rank_mock.call_args.args[0]
        self.assertEqual(
            ["https://example.com/job-1", "https://example.com/job-3"],
            [job["url"] for job in ranked_input_jobs],
        )
        rerank_input_jobs = rerank_mock.call_args.args[0]
        self.assertEqual(
            ["https://example.com/job-1", "https://example.com/job-3"],
            [job["url"] for job in rerank_input_jobs],
        )
        self.assertEqual(review_result, result)
        self.assertEqual(1, len(diagnostics.calls))
        recipient_id, summary = diagnostics.calls[0]
        self.assertEqual("george", recipient_id)
        self.assertEqual(3, summary["input_jobs"])
        self.assertEqual(1, summary["seen_skipped_jobs"])
        self.assertEqual(2, summary["ranked_jobs_passed_to_review"])
        self.assertEqual(0, summary["ranked_jobs_not_passed_to_review"])
        self.assertEqual(1, summary["seen_recorded_jobs"])
        self.assertEqual(1, summary["recipient_seen_urls"])

    def test_select_jobs_for_recipient_caps_review_input_with_llm_top_n(self):
        candidates = [make_job(1), make_job(2), make_job(3)]
        recipient_profile = {"id": "george"}
        storage = FakeStorage(set())
        diagnostics = FakeDiagnostics()
        ranked_jobs = [make_job(1), make_job(2), make_job(3)]
        ranking_stats = {
            "input_jobs": len(ranked_jobs),
            "hard_filtered_jobs": 0,
            "below_threshold_jobs": 0,
            "ranked_jobs": len(ranked_jobs),
            "hard_filter_reasons": {},
        }
        review_result = {
            "jobs_to_send": [make_job(1)],
            "reviewed_jobs": [make_job(1)],
            "review_mode": "gemini",
            "llm_shortlisted_jobs": 1,
            "gemini_reviewed_jobs": 1,
            "review_error": None,
        }

        with (
            patch.dict("os.environ", {"JOB_SCRAPER_LLM_TOP_N": "1"}),
            patch(
                "run_all.rank_jobs",
                return_value=(ranked_jobs, ranking_stats),
            ),
            patch(
                "run_all.rerank_jobs_with_gemini",
                return_value=review_result,
            ) as rerank_mock,
        ):
            select_jobs_for_recipient(
                candidates,
                recipient_profile,
                storage,
                diagnostics,
            )

        rerank_input_jobs = rerank_mock.call_args.args[0]
        self.assertEqual(
            ["https://example.com/job-1"],
            [job["url"] for job in rerank_input_jobs],
        )
        summary = diagnostics.calls[0][1]
        self.assertEqual(3, summary["ranked_jobs"])
        self.assertEqual(1, summary["ranked_jobs_passed_to_review"])
        self.assertEqual(2, summary["ranked_jobs_not_passed_to_review"])
        self.assertEqual(1, summary["seen_recorded_jobs"])
        self.assertEqual(0, summary["recipient_seen_urls"])

    def test_select_jobs_for_recipient_marks_semantic_below_threshold_seen(self):
        candidates = [make_job(1), make_job(2), make_job(3)]
        recipient_profile = {"id": "george"}
        storage = FakeStorage(set())
        diagnostics = FakeDiagnostics()
        below_threshold_audit_row = {
            "job_url": "https://example.com/job-2",
            "source_type": "example",
            "target_value": "example",
            "company_name": "Example",
            "title": "Software Engineer 2",
            "location": "London",
            "review_family": "semantic",
            "classification": "semantic_below_threshold",
            "stage": "semantic_ranking",
        }
        hard_filter_audit_row = {
            "job_url": "https://example.com/job-3",
            "source_type": "example",
            "target_value": "example",
            "company_name": "Example",
            "title": "Senior Engineer",
            "location": "London",
            "review_family": "hard_filter",
            "classification": "hard_filtered",
            "stage": "hard_filter",
        }
        ranking_stats = {
            "input_jobs": 3,
            "hard_filtered_jobs": 1,
            "below_threshold_jobs": 1,
            "ranked_jobs": 1,
            "hard_filter_reasons": {"title_seniority": 1},
            "audit_rows": [below_threshold_audit_row, hard_filter_audit_row],
        }
        review_result = {
            "jobs_to_send": [make_job(1)],
            "reviewed_jobs": [make_job(1)],
            "review_mode": "gemini",
            "llm_shortlisted_jobs": 1,
            "gemini_reviewed_jobs": 1,
            "review_error": None,
            "audit_rows": [],
        }

        with (
            patch("run_all.rank_jobs", return_value=([make_job(1)], ranking_stats)),
            patch("run_all.rerank_jobs_with_gemini", return_value=review_result),
        ):
            result = select_jobs_for_recipient(
                candidates,
                recipient_profile,
                storage,
                diagnostics,
            )

        self.assertEqual(
            ["https://example.com/job-1", "https://example.com/job-2"],
            [job["url"] for job in result["seen_jobs"]],
        )
        audit_by_url = {row["job_url"]: row for row in result["audit_rows"]}
        self.assertTrue(audit_by_url["https://example.com/job-2"]["seen_recorded"])
        self.assertFalse(audit_by_url["https://example.com/job-3"].get("seen_recorded", False))

    def test_semantic_below_threshold_seen_jobs_maps_audit_rows(self):
        rows = [
            {
                "job_url": "https://example.com/below",
                "source_type": "ashby",
                "target_value": "example",
                "company_name": "Example",
                "title": "Data Analyst",
                "location": "London",
                "classification": "semantic_below_threshold",
            },
            {
                "job_url": "https://example.com/hard",
                "classification": "hard_filtered",
            },
        ]

        seen_jobs = semantic_below_threshold_seen_jobs(rows)

        self.assertEqual(
            [
                {
                    "url": "https://example.com/below",
                    "source": "ashby",
                    "target_value": "example",
                    "company": "Example",
                    "title": "Data Analyst",
                    "location": "London",
                }
            ],
            seen_jobs,
        )

    def test_build_job_state_rows_tracks_seen_and_pending_states(self):
        rows = [
            {
                "job_url": "https://example.com/below",
                "review_family": "semantic",
                "classification": "semantic_below_threshold",
                "stage": "semantic_ranking",
                "seen_recorded": True,
            },
            {
                "job_url": "https://example.com/backlog",
                "review_family": "semantic",
                "classification": "semantic_above_threshold",
                "stage": "semantic_ranking",
                "seen_recorded": False,
                "semantic_rank": 3,
                "semantic_score": 0.76,
                "semantic_fit_summary": "Software Engineer 76% | Data 64%",
                "salary_upper_bound_gbp": 52000.0,
            },
            {
                "job_url": "https://example.com/gemini-failed",
                "review_family": "gemini",
                "classification": "gemini_batch_failed_not_seen",
                "stage": "gemini_pass1",
                "seen_recorded": False,
                "semantic_fit_hint": "Software Engineer 74% | Data 61%",
                "salary_upper_bound_gbp": 61000.0,
            },
            {
                "job_url": "https://example.com/hard",
                "review_family": "hard_filter",
                "classification": "hard_filtered",
                "stage": "hard_filter",
            },
        ]

        state_rows = build_job_state_rows(rows)
        state_by_url = {row["job_url"]: row for row in state_rows}

        self.assertEqual(
            {
                "https://example.com/below",
                "https://example.com/backlog",
                "https://example.com/gemini-failed",
            },
            set(state_by_url),
        )
        self.assertTrue(state_by_url["https://example.com/below"]["is_seen"])
        self.assertFalse(state_by_url["https://example.com/backlog"]["is_seen"])
        self.assertEqual(
            "semantic_above_threshold_not_reviewed",
            state_by_url["https://example.com/backlog"]["classification"],
        )
        self.assertEqual(
            "Software Engineer 76% | Data 64%",
            state_by_url["https://example.com/backlog"]["semantic_fit_hint"],
        )
        self.assertEqual(
            52000.0,
            state_by_url["https://example.com/backlog"]["salary_upper_bound_gbp"],
        )
        self.assertEqual(
            "pending_review",
            state_by_url["https://example.com/gemini-failed"]["processing_status"],
        )
        self.assertEqual(
            "Software Engineer 74% | Data 61%",
            state_by_url["https://example.com/gemini-failed"]["semantic_fit_hint"],
        )
        self.assertEqual(
            61000.0,
            state_by_url["https://example.com/gemini-failed"]["salary_upper_bound_gbp"],
        )

    def test_backlog_row_to_gemini_job_preserves_prompt_metadata(self):
        row = {
            "job_url": "https://example.com/backlog",
            "company_name": "Example",
            "title": "Graduate Software Engineer",
            "location": "London",
            "source_type": "ashby",
            "target_value": "example",
            "semantic_rank": 4,
            "raw_embedding_score": 0.68,
            "semantic_score": 0.74,
            "semantic_threshold": 0.42,
            "semantic_fit_hint": "Software Engineer 74% | Data 61%",
            "salary_upper_bound_gbp": 58000.0,
        }

        job = backlog_row_to_gemini_job(
            row,
            "Freshly fetched description with Python API work.",
        )

        self.assertEqual("https://example.com/backlog", job["url"])
        self.assertEqual("Example", job["company"])
        self.assertEqual("Graduate Software Engineer", job["title"])
        self.assertEqual("London", job["location"])
        self.assertEqual("ashby", job["source"])
        self.assertEqual("example", job["target_value"])
        self.assertEqual(
            "Freshly fetched description with Python API work.",
            job["description"],
        )
        self.assertEqual(4, job["semantic_rank"])
        self.assertEqual(0.68, job["raw_embedding_score"])
        self.assertEqual(0.74, job["ranking_score"])
        self.assertEqual(0.42, job["semantic_threshold"])
        self.assertEqual(58000.0, job["salary_upper_bound_gbp"])
        self.assertEqual("Software Engineer 74% | Data 61%", job["fit_summary"])

        prompt = gemini_rerank_module._build_pass_one_prompt(
            {
                "semantic_profiles": ["swe"],
                "semantic_profile_texts": {
                    "swe": "Software engineering roles using Python APIs.",
                },
                "cv_summary": "Python backend projects.",
            },
            [job],
            gemini_rerank_module.DEFAULT_DESCRIPTION_CHARS,
        )

        self.assertIn(
            '"semantic_fit_hint": "Software Engineer 74% | Data 61%"',
            prompt,
        )
        self.assertIn('"salary_upper_bound_gbp": 58000.0', prompt)

    def test_support_run_reviews_only_pending_backlog_jobs(self):
        recipient_profile = {"id": "george", "email": "george@example.com"}
        storage = FakeStorage(set())
        diagnostics = FakeDiagnostics()
        approved_url = "https://example.com/backlog-approved"
        rejected_url = "https://example.com/backlog-rejected"
        dead_url = "https://example.com/backlog-dead"
        temporary_url = "https://example.com/backlog-temporary"
        storage.pending_backlog_rows = [
            {
                "recipient_id": "george",
                "job_url": approved_url,
                "source_type": "ashby",
                "target_value": "example",
                "company_name": "Example",
                "title": "Approved Backlog",
                "location": "London",
                "semantic_rank": 1,
                "raw_embedding_score": 0.7,
                "semantic_score": 0.82,
                "semantic_threshold": 0.42,
                "semantic_fit_hint": "SWE 82%",
                "salary_upper_bound_gbp": 52000.0,
            },
            {
                "recipient_id": "george",
                "job_url": rejected_url,
                "source_type": "lever",
                "target_value": "example",
                "company_name": "Example",
                "title": "Rejected Backlog",
                "location": "London",
                "semantic_rank": 2,
                "raw_embedding_score": 0.68,
                "semantic_score": 0.73,
                "semantic_threshold": 0.42,
                "semantic_fit_hint": "SWE 73%",
            },
            {
                "recipient_id": "george",
                "job_url": dead_url,
                "source_type": "greenhouse",
                "target_value": "example",
                "company_name": "Example",
                "title": "Dead Backlog",
                "location": "London",
                "semantic_rank": 3,
                "semantic_score": 0.71,
            },
            {
                "recipient_id": "george",
                "job_url": temporary_url,
                "source_type": "ashby",
                "target_value": "example",
                "company_name": "Example",
                "title": "Temporary Backlog",
                "location": "London",
                "semantic_rank": 4,
                "semantic_score": 0.69,
            },
        ]
        approved_job = {
            "url": approved_url,
            "company": "Example",
            "title": "Approved Backlog",
            "location": "London",
            "source": "ashby",
            "target_value": "example",
            "why_apply": "Strong support evidence.",
        }
        review_result = {
            "jobs_to_send": [approved_job],
            "reviewed_jobs": [approved_job],
            "review_mode": "gemini",
            "llm_shortlisted_jobs": 1,
            "gemini_reviewed_jobs": 2,
            "audit_rows": [
                {
                    "job_url": approved_url,
                    "source_type": "ashby",
                    "target_value": "example",
                    "company_name": "Example",
                    "title": "Approved Backlog",
                    "location": "London",
                    "review_family": "gemini",
                    "classification": "gemini_pass2_approved_sent_seen",
                    "stage": "gemini_pass2",
                    "seen_recorded": True,
                    "sent": True,
                    "semantic_rank": 1,
                    "semantic_score": 0.82,
                    "semantic_fit_hint": "SWE 82%",
                },
                {
                    "job_url": rejected_url,
                    "source_type": "lever",
                    "target_value": "example",
                    "company_name": "Example",
                    "title": "Rejected Backlog",
                    "location": "London",
                    "review_family": "gemini",
                    "classification": "gemini_pass1_rejected_seen",
                    "stage": "gemini_pass1",
                    "seen_recorded": True,
                    "sent": False,
                    "semantic_rank": 2,
                    "semantic_score": 0.73,
                    "semantic_fit_hint": "SWE 73%",
                },
            ],
        }

        def fake_refetch(url):
            results = {
                approved_url: {
                    "status": "ok",
                    "description": "Fresh approved backlog description.",
                },
                rejected_url: {
                    "status": "ok",
                    "description": "Fresh rejected backlog description.",
                },
                dead_url: {"status": "dead", "reason": "missing_page"},
                temporary_url: {"status": "temporary_failure", "reason": "timeout"},
            }
            return results[url]

        with (
            patch("run_all.rank_jobs") as rank_mock,
            patch("run_all.select_jobs_for_recipient") as select_mock,
            patch(
                "run_all.refetch_backlog_job_description",
                side_effect=fake_refetch,
            ) as refetch_mock,
            patch(
                "run_all.rerank_jobs_with_gemini",
                return_value=review_result,
            ) as rerank_mock,
            patch("run_all.send_digest") as send_digest_mock,
        ):
            result = process_recipient(
                recipient_profile,
                [make_job(99)],
                storage,
                diagnostics,
                run_id="support-run",
                support_run=True,
            )

        rank_mock.assert_not_called()
        select_mock.assert_not_called()
        send_digest_mock.assert_not_called()
        self.assertEqual(
            [approved_url, rejected_url, dead_url, temporary_url],
            [call.args[0] for call in refetch_mock.call_args_list],
        )
        rerank_input_jobs = rerank_mock.call_args.args[0]
        self.assertEqual(
            [approved_url, rejected_url],
            [job["url"] for job in rerank_input_jobs],
        )
        self.assertEqual(
            [
                "Fresh approved backlog description.",
                "Fresh rejected backlog description.",
            ],
            [job["description"] for job in rerank_input_jobs],
        )
        self.assertEqual(
            [("george", dead_url, "support-run", "missing_page")],
            storage.expired_jobs,
        )
        self.assertEqual(
            [("george", "support-run", [approved_job])],
            storage.queued_jobs,
        )
        self.assertEqual([], result["jobs_to_send"])
        self.assertEqual([approved_job], result["queued_jobs"])
        self.assertEqual(1, result["jobs_queued_count"])
        stored_audit_by_url = {row["job_url"]: row for row in storage.audit_rows[0][2]}
        self.assertEqual(
            "gemini_pass2_approved_queued_seen",
            stored_audit_by_url[approved_url]["classification"],
        )
        self.assertFalse(stored_audit_by_url[approved_url]["sent"])
        self.assertEqual(
            "gemini_pass1_rejected_seen",
            stored_audit_by_url[rejected_url]["classification"],
        )
        stored_state_by_url = {row["job_url"]: row for row in storage.state_rows[0][2]}
        self.assertTrue(stored_state_by_url[approved_url]["is_seen"])
        self.assertTrue(stored_state_by_url[rejected_url]["is_seen"])
        self.assertNotIn(temporary_url, stored_state_by_url)
        self.assertEqual(4, diagnostics.calls[0][1]["backlog_rows_refetched"])
        self.assertEqual(1, diagnostics.calls[0][1]["backlog_rows_expired"])
        self.assertEqual(
            {"ok": 2, "dead": 1, "temporary_failure": 1},
            diagnostics.calls[0][1]["backlog_refetch_statuses"],
        )

    def test_support_run_keeps_gemini_failure_rows_pending(self):
        recipient_profile = {"id": "george", "email": "george@example.com"}
        storage = FakeStorage(set())
        diagnostics = FakeDiagnostics()
        job_url = "https://example.com/backlog-gemini-failed"
        storage.pending_backlog_rows = [
            {
                "recipient_id": "george",
                "job_url": job_url,
                "source_type": "ashby",
                "target_value": "example",
                "company_name": "Example",
                "title": "Gemini Failed Backlog",
                "location": "London",
                "semantic_rank": 1,
                "semantic_score": 0.8,
                "semantic_threshold": 0.42,
                "semantic_fit_hint": "SWE 80%",
            },
        ]
        review_result = {
            "jobs_to_send": [],
            "reviewed_jobs": [],
            "review_mode": "gemini_failed",
            "llm_shortlisted_jobs": 0,
            "gemini_reviewed_jobs": 0,
            "review_error": "503 UNAVAILABLE",
            "review_error_stage": "batch_screening",
            "audit_rows": [
                {
                    "job_url": job_url,
                    "source_type": "ashby",
                    "target_value": "example",
                    "company_name": "Example",
                    "title": "Gemini Failed Backlog",
                    "location": "London",
                    "review_family": "gemini",
                    "classification": "gemini_batch_failed_not_seen",
                    "stage": "gemini_pass1",
                    "seen_recorded": False,
                    "review_error_stage": "batch_screening",
                }
            ],
        }

        with (
            patch(
                "run_all.refetch_backlog_job_description",
                return_value={"status": "ok", "description": "Fresh description."},
            ),
            patch("run_all.rerank_jobs_with_gemini", return_value=review_result),
            patch("run_all.send_digest") as send_digest_mock,
        ):
            result = process_recipient(
                recipient_profile,
                [make_job(1)],
                storage,
                diagnostics,
                run_id="support-run",
                support_run=True,
            )

        send_digest_mock.assert_not_called()
        self.assertEqual([], storage.queued_jobs)
        self.assertEqual([], result["queued_jobs"])
        stored_state = storage.state_rows[0][2][0]
        self.assertEqual(job_url, stored_state["job_url"])
        self.assertFalse(stored_state["is_seen"])
        self.assertEqual("pending_review", stored_state["processing_status"])
        self.assertEqual("gemini_batch_failed_not_seen", stored_state["classification"])

    def test_main_run_sends_queued_jobs_with_current_digest(self):
        recipient_profile = {"id": "george", "email": "george@example.com"}
        storage = FakeStorage(set())
        diagnostics = FakeDiagnostics()
        queued_job = {**make_job(2), "why_apply": "Queued from support run."}
        storage.queue_jobs_to_load = [queued_job]
        review_result = {
            "jobs_to_send": [make_job(1)],
            "reviewed_jobs": [make_job(1)],
            "seen_jobs": [make_job(1)],
            "review_mode": "gemini",
            "llm_shortlisted_jobs": 1,
            "gemini_reviewed_jobs": 1,
            "audit_rows": [],
        }

        with (
            patch("run_all.select_jobs_for_recipient", return_value=review_result),
            patch("run_all.send_digest") as send_digest_mock,
        ):
            result = process_recipient(
                recipient_profile,
                [make_job(1)],
                storage,
                diagnostics,
                run_id="main-run",
            )

        send_digest_mock.assert_called_once_with(
            recipient_profile,
            [make_job(1), queued_job],
        )
        self.assertEqual(
            [("george", ["https://example.com/job-2"], "main-run")],
            storage.marked_sent,
        )
        self.assertEqual([make_job(1), queued_job], result["jobs_to_send"])
        self.assertEqual([queued_job], result["queued_jobs_delivered"])
        self.assertEqual(2, result["jobs_sent_count"])

    def test_merge_seen_jobs_dedupes_urls(self):
        merged = merge_seen_jobs(
            [make_job(1), make_job(2)],
            [make_job(2), make_job(3)],
        )

        self.assertEqual(
            [
                "https://example.com/job-1",
                "https://example.com/job-2",
                "https://example.com/job-3",
            ],
            [job["url"] for job in merged],
        )

    def test_process_recipient_sends_digest_and_stores_reviewed_jobs(self):
        recipient_profile = {"id": "george", "email": "george@example.com"}
        storage = FakeStorage(set())
        diagnostics = FakeDiagnostics()
        review_result = {
            "jobs_to_send": [make_job(1)],
            "reviewed_jobs": [make_job(1), make_job(2)],
            "review_mode": "gemini",
            "llm_shortlisted_jobs": 1,
            "gemini_reviewed_jobs": 2,
            "review_error": None,
            "audit_rows": [
                {
                    "job_url": "https://example.com/job-1",
                    "review_family": "gemini",
                    "classification": "gemini_pass2_approved_sent_seen",
                    "stage": "gemini_pass2",
                }
            ],
        }

        with (
            patch("run_all.select_jobs_for_recipient", return_value=review_result),
            patch("run_all.send_digest") as send_digest_mock,
        ):
            result = process_recipient(
                recipient_profile,
                [make_job(1), make_job(2)],
                storage,
                diagnostics,
                run_id="test-run",
            )

        self.assertEqual(review_result, result)
        send_digest_mock.assert_called_once_with(
            recipient_profile,
            review_result["jobs_to_send"],
        )
        self.assertEqual(
            [("george", review_result["reviewed_jobs"])],
            storage.stored,
        )
        self.assertEqual(
            [("george", "test-run", review_result["audit_rows"])],
            storage.audit_rows,
        )

    def test_recipient_worker_count_uses_code_cap_and_hard_max(self):
        profiles = [{"id": str(index)} for index in range(10)]

        self.assertEqual(
            min(len(profiles), RECIPIENT_CONCURRENCY_CAP, MAX_RECIPIENT_CONCURRENCY),
            recipient_worker_count(profiles),
        )
        self.assertEqual(1, recipient_worker_count([]))

    def test_build_run_summary_counts_recipient_outcomes(self):
        results = [
            {
                "review_mode": "gemini",
                "jobs_to_send": [make_job(1), make_job(2)],
                "reviewed_jobs": [make_job(1), make_job(2), make_job(3)],
            },
            {
                "review_mode": "gemini_failed",
                "review_error_stage": "batch_screening",
                "jobs_to_send": [],
                "reviewed_jobs": [],
            },
        ]

        summary = build_run_summary(
            candidates=[make_job(1), make_job(2), make_job(3)],
            enriched_candidates=[make_job(1), make_job(2), make_job(3)],
            recipient_profiles=[{"id": "one"}, {"id": "two"}],
            results=results,
        )

        self.assertEqual(3, summary["candidate_jobs"])
        self.assertEqual(2, summary["recipient_count"])
        self.assertEqual(2, summary["jobs_sent"])
        self.assertEqual(3, summary["reviewed_jobs"])
        self.assertEqual({"gemini": 1, "gemini_failed": 1}, summary["review_modes"])
        self.assertEqual(
            {"batch_screening": 1},
            summary["gemini_failure_stages"],
        )

    def test_build_run_summary_counts_support_backlog_candidates(self):
        summary = build_run_summary(
            candidates=[],
            enriched_candidates=[],
            recipient_profiles=[{"id": "one"}, {"id": "two"}],
            results=[
                {
                    "review_mode": "gemini",
                    "reviewed_jobs": [],
                    "backlog_rows_loaded": 3,
                    "backlog_rows_refetched": 2,
                    "backlog_rows_expired": 1,
                    "backlog_refetch_statuses": {"ok": 1, "dead": 1},
                },
                {
                    "review_mode": "empty",
                    "reviewed_jobs": [],
                    "backlog_rows_loaded": 4,
                    "backlog_rows_refetched": 1,
                    "backlog_rows_expired": 0,
                    "backlog_refetch_statuses": {"temporary_failure": 1},
                },
            ],
        )

        self.assertEqual(0, summary["candidate_jobs"])
        self.assertEqual(7, summary["support_backlog_candidates"])
        self.assertEqual(3, summary["support_backlog_refetched"])
        self.assertEqual(1, summary["support_backlog_expired"])
        self.assertEqual(
            {"dead": 1, "ok": 1, "temporary_failure": 1},
            summary["support_backlog_refetch_statuses"],
        )

    def test_support_run_main_skips_full_scraping(self):
        storage = FakeStorage(set())
        recipient_profiles = [{"id": "george", "email": "george@example.com"}]
        recipient_results = [
            {
                "review_mode": "gemini",
                "jobs_to_send": [],
                "reviewed_jobs": [],
                "jobs_queued_count": 1,
                "backlog_rows_loaded": 3,
                "backlog_rows_refetched": 2,
                "backlog_rows_expired": 1,
                "backlog_refetch_statuses": {"ok": 1, "dead": 1},
            }
        ]

        with (
            patch("run_all.create_storage", return_value=storage),
            patch("run_all.initialize_storage") as initialize_mock,
            patch("run_all.load_recipient_profiles", return_value=recipient_profiles),
            patch("run_all.load_configured_targets") as load_targets_mock,
            patch("run_all.load_sponsor_company_lookup") as sponsor_mock,
            patch("run_all.collect_all_jobs") as collect_mock,
            patch("run_all.enrich_jobs") as enrich_mock,
            patch(
                "run_all.process_recipients",
                return_value=recipient_results,
            ) as process_mock,
            patch("builtins.print") as print_mock,
        ):
            main(["--support-run"])

        initialize_mock.assert_called_once_with(storage)
        load_targets_mock.assert_not_called()
        sponsor_mock.assert_not_called()
        collect_mock.assert_not_called()
        enrich_mock.assert_not_called()
        process_mock.assert_called_once()
        process_args = process_mock.call_args.args
        process_kwargs = process_mock.call_args.kwargs
        self.assertEqual(recipient_profiles, process_args[0])
        self.assertEqual([], process_args[1])
        self.assertIs(storage, process_args[2])
        self.assertTrue(process_kwargs.get("support_run"))
        run_summary_line = [
            call.args[0]
            for call in print_mock.call_args_list
            if call.args and str(call.args[0]).startswith("[run_summary]")
        ][0]
        self.assertIn("support_backlog_candidates=3", run_summary_line)

    def test_main_run_still_uses_full_scraping_path(self):
        storage = FakeStorage(set())
        recipient_profiles = [{"id": "george", "email": "george@example.com"}]
        targets = {"ashby": ["example"], "greenhouse": [], "lever": [], "nextjs": []}
        candidates = [make_job(1)]
        enriched_candidates = [{**make_job(1), "is_sponsor_licensed_employer": True}]
        recipient_results = [
            {
                "review_mode": "gemini",
                "jobs_to_send": [make_job(1)],
                "reviewed_jobs": [make_job(1)],
            }
        ]

        with (
            patch("run_all.create_storage", return_value=storage),
            patch("run_all.initialize_storage"),
            patch("run_all.load_recipient_profiles", return_value=recipient_profiles),
            patch(
                "run_all.load_configured_targets",
                return_value=targets,
            ) as load_targets_mock,
            patch(
                "run_all.load_sponsor_company_lookup",
                return_value={"Example"},
            ) as sponsor_mock,
            patch("run_all.collect_all_jobs", return_value=candidates) as collect_mock,
            patch("run_all.enrich_jobs", return_value=enriched_candidates) as enrich_mock,
            patch(
                "run_all.process_recipients",
                return_value=recipient_results,
            ) as process_mock,
            patch("builtins.print"),
        ):
            main([])

        load_targets_mock.assert_called_once_with()
        sponsor_mock.assert_called_once_with()
        collect_mock.assert_called_once()
        self.assertEqual(targets, collect_mock.call_args.args[0])
        self.assertEqual(
            ["UK"],
            collect_mock.call_args.kwargs["location_presets"],
        )
        enrich_mock.assert_called_once_with(candidates, {"Example"})
        process_args = process_mock.call_args.args
        process_kwargs = process_mock.call_args.kwargs
        self.assertEqual(enriched_candidates, process_args[1])
        self.assertFalse(process_kwargs.get("support_run"))

    def test_build_and_write_run_snapshot(self):
        diagnostics = FakeDiagnostics()
        diagnostics.source_failures.append({"source": "greenhouse", "error": "boom"})
        diagnostics.record_recipient_summary(
            "george",
            {
                "review_mode": "gemini",
                "ranked_jobs": 1,
            },
        )
        candidates = [make_job(1)]
        enriched_candidates = [{**make_job(1), "is_sponsor_licensed_employer": True}]
        recipient_profiles = [{"id": "george", "email": "george@example.com"}]
        recipient_results = [
            {
                "review_mode": "gemini",
                "jobs_to_send": [make_job(1)],
                "reviewed_jobs": [make_job(1)],
            }
        ]
        run_summary = build_run_summary(
            candidates,
            enriched_candidates,
            recipient_profiles,
            recipient_results,
        )

        snapshot = build_run_snapshot(
            candidates,
            enriched_candidates,
            recipient_profiles,
            recipient_results,
            run_summary,
            diagnostics,
        )
        output_path = write_run_snapshot(
            self.test_dir / "snapshot.json",
            snapshot,
        )
        saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(RUN_SNAPSHOT_SCHEMA_VERSION, saved["schema_version"])
        self.assertEqual(candidates, saved["candidates"])
        self.assertEqual(enriched_candidates, saved["enriched_candidates"])
        self.assertEqual(recipient_profiles, saved["recipient_profiles"])
        self.assertEqual({"gemini": 1}, saved["run_summary"]["review_modes"])
        self.assertEqual(
            [{"source": "greenhouse", "error": "boom"}],
            saved["source_failures"],
        )


if __name__ == "__main__":
    unittest.main()
