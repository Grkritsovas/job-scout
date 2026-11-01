import sqlite3
import unittest
from pathlib import Path

from config.recipient_profiles import prepare_recipient_profile_db_rows
from storage import EXPIRED_JOB_STATE_CLASSIFICATION, create_storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/.tmp_storage")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for child in self.test_dir.glob("*"):
            child.unlink()
        self.test_dir.rmdir()

    def test_unmark_is_scoped_preserves_history_and_waits_for_full_matching(self):
        storage = create_storage(f"sqlite:///{(self.test_dir / 'unmark.db').resolve()}")
        storage.ensure_schema()
        job = {"url": "https://example.com/retry", "source": "ashby", "sent": True}
        other_job = {"url": "https://example.com/keep"}
        storage.store_seen_jobs("recipient-a", [job, other_job])
        storage.store_seen_jobs("recipient-b", [job])
        storage.store_review_audit_rows("recipient-a", "old-run", [{
            "job_url": job["url"], "review_family": "gemini",
            "classification": "gemini_pass1_rejected_seen", "seen_recorded": True,
        }])
        old_audit = storage.load_review_audit_rows()

        self.assertEqual(1, storage.unmark_seen_job("recipient-a", job["url"]))
        self.assertEqual({other_job["url"]}, storage.load_seen_urls("recipient-a"))
        self.assertEqual({job["url"]}, storage.load_seen_urls("recipient-b"))
        self.assertEqual(old_audit, storage.load_review_audit_rows())
        self.assertEqual([], storage.load_pending_job_backlog("recipient-a"))
        self.assertEqual(0, storage.count_recent_pending_job_backlog())
        row = storage._fetch_all(
            "SELECT * FROM recipient_seen_jobs WHERE recipient_id = ? AND job_url = ?",
            ("recipient-a", job["url"]),
        )[0]
        self.assertEqual("awaiting_main_run", row["processing_status"])
        self.assertEqual("manual_reset_unseen", row["classification"])
        self.assertTrue(row["sent"])
        self.assertEqual(0, storage.unmark_seen_job("recipient-a", job["url"]))
        # A new decision can mark the job seen again through the normal path.
        storage.store_seen_jobs("recipient-a", [job])
        self.assertIn(job["url"], storage.load_seen_urls("recipient-a"))

    def test_unmark_removes_only_the_matching_queued_approval_and_old_scores(self):
        storage = create_storage(f"sqlite:///{(self.test_dir / 'unmark_queue.db').resolve()}")
        storage.ensure_schema()
        job = {"url": "https://example.com/queued", "why_apply": "Old approval."}
        other_job = {"url": "https://example.com/keep-queued"}
        storage.store_job_state_rows("recipient-a", "old-run", [{
            "job_url": job["url"], "is_seen": True,
            "classification": "gemini_pass2_approved_queued_seen",
            "semantic_rank": 1, "raw_embedding_score": 0.5,
            "semantic_score": 0.6, "semantic_threshold": 0.42,
            "semantic_fit_hint": "Old fit",
        }])
        storage.store_digest_queue_jobs("recipient-a", "old-run", [job, other_job])
        storage.store_digest_queue_jobs("recipient-b", "old-run", [job])

        self.assertEqual(1, storage.unmark_seen_job("recipient-a", job["url"]))
        self.assertEqual([other_job], storage.load_digest_queue_jobs("recipient-a"))
        self.assertEqual([job], storage.load_digest_queue_jobs("recipient-b"))
        row = storage._fetch_all("SELECT * FROM recipient_seen_jobs", ())[0]
        for field in ("run_id", "semantic_rank", "raw_embedding_score", "semantic_score",
                      "semantic_threshold", "semantic_fit_hint"):
            self.assertIsNone(row[field], field)

    def test_unmark_ignores_unknown_jobs_and_existing_pending_backlog(self):
        storage = create_storage(f"sqlite:///{(self.test_dir / 'unmark_pending.db').resolve()}")
        storage.ensure_schema()
        storage.store_job_state_rows("recipient-a", "run", [{
            "job_url": "https://example.com/pending", "is_seen": False,
            "classification": "gemini_batch_failed_not_seen",
        }])
        before = storage.load_pending_job_backlog("recipient-a")
        for recipient, url in (
            ("recipient-a", "https://example.com/pending"),
            ("recipient-a", "https://example.com/unknown"),
            ("recipient-b", "https://example.com/pending"),
            ("", "https://example.com/pending"),
        ):
            self.assertEqual(0, storage.unmark_seen_job(recipient, url))
        self.assertEqual(before, storage.load_pending_job_backlog("recipient-a"))

    def test_unmark_rolls_back_if_the_queued_approval_cannot_be_removed(self):
        storage = create_storage(f"sqlite:///{(self.test_dir / 'unmark_rollback.db').resolve()}")
        storage.ensure_schema()
        job = {"url": "https://example.com/queued"}
        storage.store_seen_jobs("recipient-a", [job])
        storage.store_digest_queue_jobs("recipient-a", "run", [job])
        connection = storage._connect_sqlite()
        try:
            connection.execute("""
                CREATE TRIGGER prevent_queue_delete BEFORE DELETE ON recipient_digest_queue
                BEGIN SELECT RAISE(ABORT, 'queue locked'); END
            """)
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "queue locked"):
            storage.unmark_seen_job("recipient-a", job["url"])
        self.assertIn(job["url"], storage.load_seen_urls("recipient-a"))
        self.assertEqual([job], storage.load_digest_queue_jobs("recipient-a"))

    def test_recipient_seen_jobs_are_recipient_aware(self):
        db_path = (self.test_dir / "test.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()
        storage.store_seen_jobs(
            "george",
            [
                {
                    "url": "https://example.com/job-1",
                    "source": "ashby",
                    "target_value": "example",
                    "company": "Example",
                    "title": "Software Engineer",
                    "location": "London",
                }
            ],
        )

        self.assertEqual(
            {"https://example.com/job-1"},
            storage.load_seen_urls("george"),
        )
        self.assertEqual(set(), storage.load_seen_urls("elisabeth"))

    def test_sqlite_seen_jobs_schema_upgrades_legacy_table_before_index(self):
        db_path = (self.test_dir / "legacy_seen_jobs.db").resolve()
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                """
                CREATE TABLE recipient_seen_jobs (
                    recipient_id TEXT NOT NULL,
                    job_url TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT '',
                    target_value TEXT,
                    company_name TEXT,
                    title TEXT,
                    location TEXT,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (recipient_id, job_url)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO recipient_seen_jobs (
                    recipient_id,
                    job_url,
                    source_type,
                    company_name,
                    title,
                    location
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "demo-recipient",
                    "https://example.com/legacy-job",
                    "ashby",
                    "Example",
                    "Software Engineer",
                    "London",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()

        connection = sqlite3.connect(db_path)
        try:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(recipient_seen_jobs)")
            }
        finally:
            connection.close()

        self.assertIn("is_seen", columns)
        self.assertIn("classification", columns)
        self.assertIn("semantic_fit_hint", columns)
        self.assertIn("salary_upper_bound_gbp", columns)
        self.assertEqual(
            {"https://example.com/legacy-job"},
            storage.load_seen_urls("demo-recipient"),
        )

    def test_recipient_profile_configs_round_trip(self):
        db_path = (self.test_dir / "profiles.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()
        rows = prepare_recipient_profile_db_rows(
            [
                {
                    "id": "george",
                    "delivery": {"email": "george@example.com"},
                    "candidate": {
                        "summary": "Strong Python and ML project experience.",
                        "target_roles": [{"id": "swe"}],
                    },
                    "job_preferences": {
                        "target_seniority": {
                            "max_explicit_years": 2,
                            "boost_multiplier": 1.1,
                            "boost_title_terms": ["junior", "graduate"],
                        },
                        "salary": {
                            "preferred_max_gbp": 45000,
                            "hard_cap_gbp": 55000,
                            "penalty_strength": 0.2,
                        },
                    },
                    "eligibility": {
                        "needs_sponsorship": False,
                        "check_hard_eligibility": True,
                        "use_sponsor_lookup": True,
                    },
                    "matching": {
                        "semantic_threshold": 0.5,
                    },
                    "llm_review": {
                        "extra_screening_guidance": ["Prefer early-career roles."],
                        "extra_final_ranking_guidance": ["Prefer clearer evidence."],
                    },
                }
            ]
        )

        storage.upsert_recipient_profile_configs(rows)
        loaded = storage.load_recipient_profile_configs(enabled_only=False)
        records = storage.load_recipient_profile_records(enabled_only=False)

        self.assertEqual(1, len(loaded))
        self.assertEqual("george", loaded[0]["id"])
        self.assertEqual("george@example.com", loaded[0]["delivery"]["email"])
        self.assertEqual(2, loaded[0]["job_preferences"]["target_seniority"]["max_explicit_years"])
        self.assertEqual("george", records[0]["recipient_id"])
        self.assertEqual("george@example.com", records[0]["email"])
        self.assertTrue(records[0]["enabled"])

    def test_recipient_profile_versions_can_be_loaded(self):
        db_path = (self.test_dir / "profile_versions.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()

        first_profile = {
            "id": "demo-recipient",
            "delivery": {"email": "recipient@example.com"},
            "candidate": {
                "summary": "First summary.",
                "target_roles": [{"id": "swe"}],
            },
        }
        second_profile = {
            **first_profile,
            "candidate": {
                "summary": "Second summary.",
                "target_roles": [{"id": "data_science"}],
            },
        }

        storage.upsert_recipient_profile_configs(
            prepare_recipient_profile_db_rows([first_profile])
        )
        storage.upsert_recipient_profile_configs(
            prepare_recipient_profile_db_rows([second_profile])
        )

        versions = storage.load_recipient_profile_versions("demo_recipient")
        loaded_version = storage.load_recipient_profile_version(
            "demo_recipient",
            versions[-1]["version_id"],
        )

        self.assertEqual(2, len(versions))
        self.assertEqual("Second summary.", versions[0]["config"]["candidate"]["summary"])
        self.assertEqual("First summary.", loaded_version["config"]["candidate"]["summary"])

    def test_review_audit_rows_round_trip_and_retention(self):
        db_path = (self.test_dir / "audit.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()

        rows = [
            {
                "job_url": f"https://example.com/job-{index}",
                "source_type": "ashby",
                "target_value": "example",
                "company_name": "Example",
                "title": f"Job {index}",
                "location": "London",
                "review_family": "semantic",
                "classification": "semantic_above_threshold",
                "stage": "semantic_ranking",
                "semantic_rank": index,
                "raw_embedding_score": 0.7 - index / 100,
                "semantic_score": 0.5 + index / 100,
                "semantic_threshold": 0.42,
                "supporting_evidence": ["Python"],
                "metadata": {"selected_for_gemini": False},
            }
            for index in range(1, 7)
        ]

        storage.store_review_audit_rows("recipient-a", "run-1", rows)
        deleted = storage.prune_review_audit_rows(keep_rows=3, high_water_rows=5)
        loaded = storage.load_review_audit_rows()
        latest = storage.load_review_audit_rows(
            limit=2,
            recipient_id="recipient-a",
            classification="semantic_above_threshold",
            latest_first=True,
        )
        weakest = storage.load_review_audit_rows(
            limit=2,
            recipient_id="recipient-a",
            classification="semantic_above_threshold",
            sort="semantic_score_asc",
        )
        strongest = storage.load_review_audit_rows(
            limit=2,
            recipient_id="recipient-a",
            classification="semantic_above_threshold",
            sort="semantic_score_desc",
        )
        strongest_raw = storage.load_review_audit_rows(
            limit=2,
            recipient_id="recipient-a",
            classification="semantic_above_threshold",
            sort="raw_embedding_score_desc",
        )
        filter_values = storage.load_review_audit_filter_values()

        self.assertEqual(3, deleted)
        self.assertEqual(3, len(loaded))
        self.assertEqual(
            [
                "https://example.com/job-4",
                "https://example.com/job-5",
                "https://example.com/job-6",
            ],
            [row["job_url"] for row in loaded],
        )
        self.assertEqual("recipient-a", loaded[0]["recipient_id"])
        self.assertEqual("run-1", loaded[0]["run_id"])
        self.assertEqual("semantic_above_threshold", loaded[0]["classification"])
        self.assertAlmostEqual(0.66, loaded[0]["raw_embedding_score"])
        self.assertEqual(
            ["https://example.com/job-6", "https://example.com/job-5"],
            [row["job_url"] for row in latest],
        )
        self.assertEqual(
            ["https://example.com/job-4", "https://example.com/job-5"],
            [row["job_url"] for row in weakest],
        )
        self.assertEqual(
            ["https://example.com/job-6", "https://example.com/job-5"],
            [row["job_url"] for row in strongest],
        )
        self.assertEqual(
            ["https://example.com/job-4", "https://example.com/job-5"],
            [row["job_url"] for row in strongest_raw],
        )
        self.assertEqual(["recipient-a"], filter_values["recipient_ids"])
        self.assertEqual(["semantic"], filter_values["review_families"])

    def test_pending_semantic_job_state_stores_prompt_metadata(self):
        db_path = (self.test_dir / "state_prompt_metadata.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()

        storage.store_job_state_rows(
            "recipient-a",
            "run-1",
            [
                {
                    "job_url": "https://example.com/semantic-backlog",
                    "source_type": "ashby",
                    "company_name": "Example",
                    "title": "Semantic Backlog",
                    "location": "London",
                    "review_family": "semantic",
                    "classification": "semantic_above_threshold_not_reviewed",
                    "stage": "semantic_ranking",
                    "is_seen": False,
                    "semantic_rank": 2,
                    "semantic_score": 0.71,
                    "semantic_threshold": 0.42,
                    "semantic_fit_hint": "Software Engineer 71% | Data 64%",
                    "salary_upper_bound_gbp": 55000.0,
                }
            ],
        )

        connection = storage._connect_sqlite()
        try:
            row = connection.execute(
                """
                SELECT
                    is_seen,
                    processing_status,
                    classification,
                    semantic_rank,
                    semantic_score,
                    semantic_threshold,
                    semantic_fit_hint,
                    salary_upper_bound_gbp
                FROM recipient_seen_jobs
                WHERE recipient_id = ?
                  AND job_url = ?
                """,
                ("recipient-a", "https://example.com/semantic-backlog"),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(
            (
                0,
                "pending_review",
                "semantic_above_threshold_not_reviewed",
                2,
                0.71,
                0.42,
                "Software Engineer 71% | Data 64%",
                55000.0,
            ),
            row,
        )

    def test_load_pending_job_backlog_filters_and_orders_rows(self):
        db_path = (self.test_dir / "pending_backlog.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()
        rows = [
            {
                "job_url": "https://example.com/rank-2-high",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Rank Two High",
                "location": "London",
                "review_family": "gemini",
                "classification": "gemini_batch_failed_not_seen",
                "stage": "gemini_pass1",
                "is_seen": False,
                "semantic_rank": 2,
                "semantic_score": 0.83,
                "semantic_fit_hint": "Software Engineer 83%",
                "salary_upper_bound_gbp": 62000.0,
            },
            {
                "job_url": "https://example.com/rank-1",
                "source_type": "lever",
                "company_name": "Example",
                "title": "Rank One",
                "location": "London",
                "review_family": "semantic",
                "classification": "semantic_above_threshold_not_reviewed",
                "stage": "semantic_ranking",
                "is_seen": False,
                "semantic_rank": 1,
                "semantic_score": 0.7,
                "semantic_fit_hint": "Software Engineer 70%",
                "salary_upper_bound_gbp": 50000.0,
            },
            {
                "job_url": "https://example.com/null-rank",
                "source_type": "greenhouse",
                "company_name": "Example",
                "title": "Null Rank",
                "location": "London",
                "review_family": "gemini",
                "classification": "gemini_client_setup_failed_not_seen",
                "stage": "gemini_pass1",
                "is_seen": False,
                "semantic_score": 0.99,
                "semantic_fit_hint": "Software Engineer 99%",
                "salary_upper_bound_gbp": 70000.0,
            },
            {
                "job_url": "https://example.com/rank-2-low",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Rank Two Low",
                "location": "London",
                "review_family": "semantic",
                "classification": "semantic_above_threshold_not_reviewed",
                "stage": "semantic_ranking",
                "is_seen": False,
                "semantic_rank": 2,
                "semantic_score": 0.75,
                "semantic_fit_hint": "Software Engineer 75%",
                "salary_upper_bound_gbp": 54000.0,
            },
            {
                "job_url": "https://example.com/seen",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Seen",
                "location": "London",
                "review_family": "semantic",
                "classification": "semantic_above_threshold_seen",
                "stage": "semantic_ranking",
                "is_seen": True,
                "semantic_rank": 0,
                "semantic_score": 1.0,
            },
            {
                "job_url": "https://example.com/hard-filtered",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Hard Filtered",
                "location": "London",
                "review_family": "hard_filter",
                "classification": "hard_filtered",
                "stage": "hard_filter",
                "is_seen": False,
                "semantic_rank": 0,
                "semantic_score": 1.0,
            },
        ]
        storage.store_job_state_rows("recipient-a", "run-1", rows)
        storage.store_job_state_rows(
            "recipient-b",
            "run-1",
            [
                {
                    "job_url": "https://example.com/other-recipient",
                    "classification": "semantic_above_threshold_not_reviewed",
                    "is_seen": False,
                    "semantic_rank": 0,
                    "semantic_score": 1.0,
                }
            ],
        )

        connection = storage._connect_sqlite()
        try:
            updates = [
                ("2026-01-01 00:00:03", "https://example.com/rank-2-high"),
                ("2026-01-01 00:00:02", "https://example.com/rank-1"),
                ("2026-01-01 00:00:01", "https://example.com/null-rank"),
                ("2026-01-01 00:00:04", "https://example.com/rank-2-low"),
            ]
            connection.executemany(
                """
                UPDATE recipient_seen_jobs
                SET updated_at = ?
                WHERE recipient_id = 'recipient-a'
                  AND job_url = ?
                """,
                updates,
            )
            connection.commit()
        finally:
            connection.close()

        loaded = storage.load_pending_job_backlog("recipient-a")
        limited = storage.load_pending_job_backlog("recipient-a", limit=2)

        self.assertEqual(
            [
                "https://example.com/rank-1",
                "https://example.com/rank-2-high",
                "https://example.com/rank-2-low",
                "https://example.com/null-rank",
            ],
            [row["job_url"] for row in loaded],
        )
        self.assertEqual(
            [
                "https://example.com/rank-1",
                "https://example.com/rank-2-high",
            ],
            [row["job_url"] for row in limited],
        )
        self.assertEqual("Software Engineer 70%", loaded[0]["semantic_fit_hint"])
        self.assertEqual(50000.0, loaded[0]["salary_upper_bound_gbp"])
        self.assertEqual("gemini_batch_failed_not_seen", loaded[1]["classification"])
        self.assertEqual(5, storage.count_recent_pending_job_backlog())

    def test_mark_pending_job_expired_marks_dead_row_seen(self):
        db_path = (self.test_dir / "expired_backlog.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()
        storage.store_job_state_rows(
            "recipient-a",
            "run-1",
            [
                {
                    "job_url": "https://example.com/dead",
                    "source_type": "ashby",
                    "company_name": "Example",
                    "title": "Dead Backlog",
                    "location": "London",
                    "review_family": "semantic",
                    "classification": "semantic_above_threshold_not_reviewed",
                    "stage": "semantic_ranking",
                    "is_seen": False,
                    "semantic_rank": 1,
                    "semantic_score": 0.8,
                },
                {
                    "job_url": "https://example.com/temporary",
                    "source_type": "lever",
                    "company_name": "Example",
                    "title": "Temporary Failure",
                    "location": "London",
                    "review_family": "gemini",
                    "classification": "gemini_batch_failed_not_seen",
                    "stage": "gemini_pass1",
                    "is_seen": False,
                    "semantic_rank": 2,
                    "semantic_score": 0.7,
                },
            ],
        )
        connection = storage._connect_sqlite()
        try:
            connection.execute(
                """
                UPDATE recipient_seen_jobs
                SET updated_at = '2000-01-01 00:00:00'
                WHERE recipient_id = ?
                  AND job_url = ?
                """,
                ("recipient-a", "https://example.com/dead"),
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(2, storage.count_recent_pending_job_backlog())

        updated_count = storage.mark_pending_job_expired(
            "recipient-a",
            "https://example.com/dead",
            run_id="support-run",
            reason="404",
        )

        self.assertEqual(1, updated_count)
        self.assertEqual(1, storage.count_recent_pending_job_backlog())
        self.assertEqual(
            ["https://example.com/temporary"],
            [
                row["job_url"]
                for row in storage.load_pending_job_backlog("recipient-a")
            ],
        )
        self.assertEqual(
            {"https://example.com/dead"},
            storage.load_seen_urls("recipient-a"),
        )

        connection = storage._connect_sqlite()
        try:
            row = connection.execute(
                """
                SELECT
                    is_seen,
                    processing_status,
                    classification,
                    review_error_stage,
                    run_id,
                    updated_at
                FROM recipient_seen_jobs
                WHERE recipient_id = ?
                  AND job_url = ?
                """,
                ("recipient-a", "https://example.com/dead"),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(1, row[0])
        self.assertEqual("processed", row[1])
        self.assertEqual(EXPIRED_JOB_STATE_CLASSIFICATION, row[2])
        self.assertEqual("url_refetch", row[3])
        self.assertEqual("support-run", row[4])
        self.assertNotEqual("2000-01-01 00:00:00", row[5])

    def test_mark_pending_job_expired_ignores_non_pending_rows(self):
        db_path = (self.test_dir / "expired_non_pending.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()
        storage.store_job_state_rows(
            "recipient-a",
            "run-1",
            [
                {
                    "job_url": "https://example.com/hard-filtered",
                    "source_type": "ashby",
                    "company_name": "Example",
                    "title": "Hard Filtered",
                    "location": "London",
                    "review_family": "hard_filter",
                    "classification": "hard_filtered",
                    "stage": "hard_filter",
                    "is_seen": False,
                },
                {
                    "job_url": "https://example.com/already-seen",
                    "source_type": "ashby",
                    "company_name": "Example",
                    "title": "Already Seen",
                    "location": "London",
                    "review_family": "semantic",
                    "classification": "semantic_above_threshold_seen",
                    "stage": "semantic_ranking",
                    "is_seen": True,
                },
            ],
        )

        self.assertEqual(
            0,
            storage.mark_pending_job_expired(
                "recipient-a",
                "https://example.com/hard-filtered",
                run_id="support-run",
            ),
        )
        self.assertEqual(
            0,
            storage.mark_pending_job_expired(
                "recipient-a",
                "https://example.com/already-seen",
                run_id="support-run",
            ),
        )

        connection = storage._connect_sqlite()
        try:
            rows = connection.execute(
                """
                SELECT job_url, is_seen, classification, review_error_stage, run_id
                FROM recipient_seen_jobs
                WHERE recipient_id = ?
                ORDER BY job_url
                """,
                ("recipient-a",),
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(
            [
                (
                    "https://example.com/already-seen",
                    1,
                    "semantic_above_threshold_seen",
                    None,
                    "run-1",
                ),
                (
                    "https://example.com/hard-filtered",
                    0,
                    "hard_filtered",
                    None,
                    "run-1",
                ),
            ],
            rows,
        )

    def test_review_backlog_count_uses_recent_pending_job_state_rows(self):
        db_path = (self.test_dir / "state_backlog.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()
        rows = [
            {
                "job_url": "https://example.com/semantic-backlog",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Semantic Backlog",
                "location": "London",
                "review_family": "semantic",
                "classification": "semantic_above_threshold_not_reviewed",
                "stage": "semantic_ranking",
                "is_seen": False,
            },
            {
                "job_url": "https://example.com/already-seen",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Already Seen",
                "location": "London",
                "review_family": "semantic",
                "classification": "semantic_above_threshold_seen",
                "stage": "semantic_ranking",
                "is_seen": True,
            },
            {
                "job_url": "https://example.com/gemini-failed",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Gemini Failed",
                "location": "London",
                "review_family": "gemini",
                "classification": "gemini_batch_failed_not_seen",
                "stage": "gemini_pass1",
                "is_seen": False,
            },
            {
                "job_url": "https://example.com/below-threshold",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Below Threshold",
                "location": "London",
                "review_family": "semantic",
                "classification": "semantic_below_threshold",
                "stage": "semantic_ranking",
                "is_seen": True,
            },
            {
                "job_url": "https://example.com/hard-filtered",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Hard Filtered",
                "location": "London",
                "review_family": "hard_filter",
                "classification": "hard_filtered",
                "stage": "hard_filter",
                "is_seen": False,
            },
            {
                "job_url": "https://example.com/recorded-seen",
                "source_type": "ashby",
                "company_name": "Example",
                "title": "Recorded Seen",
                "location": "London",
                "review_family": "gemini",
                "classification": "gemini_pass2_approved_sent_seen",
                "stage": "gemini_pass2",
                "is_seen": True,
            },
        ]
        storage.store_job_state_rows("recipient-a", "run-1", rows)

        self.assertEqual(2, storage.count_recent_pending_job_backlog())
        self.assertEqual(
            {
                "https://example.com/already-seen",
                "https://example.com/below-threshold",
                "https://example.com/recorded-seen",
            },
            storage.load_seen_urls("recipient-a"),
        )

        connection = storage._connect_sqlite()
        try:
            connection.execute(
                """
                UPDATE recipient_seen_jobs
                SET updated_at = '2000-01-01 00:00:00'
                WHERE job_url IN (
                    'https://example.com/semantic-backlog',
                    'https://example.com/gemini-failed'
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(
            0,
            storage.count_recent_pending_job_backlog(max_age_hours=48),
        )

    def test_digest_queue_round_trip_and_marks_sent(self):
        db_path = (self.test_dir / "digest_queue.db").resolve()
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()
        job = {
            "url": "https://example.com/queued",
            "source": "ashby",
            "company": "Example",
            "title": "Queued Job",
            "location": "London",
            "why_apply": "Good fit.",
        }
        storage.store_job_state_rows(
            "recipient-a",
            "support-run",
            [
                {
                    "job_url": job["url"],
                    "source_type": job["source"],
                    "company_name": job["company"],
                    "title": job["title"],
                    "location": job["location"],
                    "review_family": "gemini",
                    "classification": "gemini_pass2_approved_queued_seen",
                    "stage": "gemini_pass2",
                    "is_seen": True,
                    "sent": False,
                }
            ],
        )
        storage.store_digest_queue_jobs("recipient-a", "support-run", [job])

        self.assertEqual([job], storage.load_digest_queue_jobs("recipient-a"))

        storage.mark_digest_queue_jobs_sent(
            "recipient-a",
            [job["url"]],
            run_id="main-run",
        )

        self.assertEqual([], storage.load_digest_queue_jobs("recipient-a"))
        connection = storage._connect_sqlite()
        try:
            row = connection.execute(
                """
                SELECT sent, classification, run_id
                FROM recipient_seen_jobs
                WHERE recipient_id = ?
                  AND job_url = ?
                """,
                ("recipient-a", job["url"]),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual((1, "gemini_pass2_approved_sent_seen", "main-run"), row)


if __name__ == "__main__":
    unittest.main()
