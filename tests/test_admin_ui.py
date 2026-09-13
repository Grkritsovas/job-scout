import unittest
from pathlib import Path
from unittest.mock import patch

from admin_ui import AdminController, AdminApiError, create_admin_storage, database_label
from storage import create_storage


class AdminUiTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/.tmp_admin_ui")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = (self.test_dir / "admin.db").resolve()
        self.storage = create_storage(f"sqlite:///{self.db_path}")
        self.storage.ensure_schema()
        self.controller = AdminController(self.storage)

    def tearDown(self):
        for child in self.test_dir.glob("*"):
            child.unlink()
        self.test_dir.rmdir()

    def test_save_profile_validates_and_writes_db_config(self):
        result = self.controller.save_profile(
            {
                "id": "demo-recipient",
                "delivery": {
                    "email": "recipient@example.com",
                    "language": "Greek",
                },
                "candidate": {
                    "summary": "Python projects.",
                    "target_roles": [{"id": "swe"}],
                },
                "job_preferences": {"location": "Greece"},
            }
        )

        self.assertTrue(result["saved"])
        self.assertEqual("demo_recipient", result["summary"]["id"])

        profiles = self.controller.list_profiles()["profiles"]
        self.assertEqual(1, len(profiles))
        self.assertEqual("demo_recipient", profiles[0]["id"])
        self.assertEqual("Greek", profiles[0]["language"])
        self.assertEqual("Greece", profiles[0]["location"])
        self.assertEqual(["swe"], profiles[0]["target_roles"])

        loaded = self.controller.get_profile("demo_recipient")
        self.assertEqual("recipient@example.com", loaded["summary"]["email"])
        self.assertEqual("Greek", loaded["summary"]["language"])
        self.assertEqual("Greece", loaded["summary"]["location"])
        self.assertEqual("Greek", loaded["profile"]["delivery"]["language"])
        self.assertEqual(
            "Greece",
            loaded["profile"]["job_preferences"]["location"],
        )
        self.assertEqual(0.42, loaded["profile"]["matching"]["semantic_threshold"])

    def test_validate_profile_reports_normalization_errors(self):
        with self.assertRaises(AdminApiError) as raised:
            self.controller.validate_profile(
                {
                    "id": "bad-profile",
                    "delivery": {"email": "recipient@example.com"},
                    "candidate": {"target_roles": [123]},
                }
            )

        self.assertIn("must be a string or object", raised.exception.message)

    def test_profile_versions_can_be_listed_and_restored(self):
        first = self.controller.save_profile(
            {
                "id": "demo-recipient",
                "delivery": {"email": "recipient@example.com"},
                "candidate": {
                    "summary": "First summary.",
                    "target_roles": [{"id": "swe"}],
                },
            }
        )
        self.controller.save_profile(
            {
                **first["profile"],
                "candidate": {
                    **first["profile"]["candidate"],
                    "summary": "Second summary.",
                },
            }
        )

        versions = self.controller.list_profile_versions("demo_recipient")["versions"]
        restored = self.controller.restore_profile_version(
            "demo_recipient",
            versions[-1]["version_id"],
        )

        self.assertEqual(2, len(versions))
        self.assertEqual("Second summary.", versions[0]["profile"]["candidate"]["summary"])
        self.assertEqual("First summary.", restored["profile"]["candidate"]["summary"])

    def test_audit_rows_are_filterable_for_the_ui(self):
        self.storage.store_review_audit_rows(
            "demo-recipient",
            "run-1",
            [
                {
                    "job_url": "https://example.com/job-1",
                    "source_type": "ashby",
                    "company_name": "Example",
                    "title": "Software Engineer",
                    "location": "London",
                    "review_family": "semantic",
                    "classification": "semantic_above_threshold",
                    "stage": "semantic_ranking",
                    "raw_embedding_score": 0.51,
                    "semantic_score": 0.56,
                    "semantic_threshold": 0.42,
                    "semantic_top_profile": "SWE",
                },
                {
                    "job_url": "https://example.com/job-2",
                    "source_type": "ashby",
                    "company_name": "Example",
                    "title": "Senior Engineer",
                    "location": "London",
                    "review_family": "hard_filter",
                    "classification": "hard_filtered",
                    "stage": "hard_filter",
                    "hard_filter_reason": "title_seniority",
                },
            ],
        )

        payload = self.controller.list_audit_rows(
            {
                "recipient_id": "demo-recipient",
                "classification": "semantic_above_threshold",
                "limit": "10",
                "sort": "semantic_score_desc",
            }
        )

        self.assertEqual(1, payload["summary"]["row_count"])
        self.assertEqual("semantic_above_threshold", payload["rows"][0]["classification"])
        self.assertEqual(0.51, payload["rows"][0]["raw_embedding_score"])
        self.assertEqual("SWE", payload["rows"][0]["semantic_top_profile"])
        self.assertEqual({"semantic_above_threshold": 1}, payload["summary"]["classifications"])

        options = self.controller.audit_filter_values()
        self.assertIn("demo-recipient", options["recipient_ids"])
        self.assertIn("semantic_above_threshold", options["classifications"])

    def test_admin_storage_requires_database_url(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                create_admin_storage()

        self.assertIn("Set DATABASE_URL", str(raised.exception))

    def test_admin_storage_can_use_explicit_sqlite_url(self):
        explicit_path = (self.test_dir / "explicit.db").resolve()

        storage, info = create_admin_storage(f"sqlite:///{explicit_path}")

        self.assertEqual("sqlite", storage.backend)
        self.assertFalse(info["using_fallback"])
        self.assertEqual("argument", info["database_source"])
        self.assertEqual(f"sqlite:///{explicit_path}", info["database_label"])

    def test_database_label_hides_credentials(self):
        label = database_label(
            "postgresql://user:secret@example.supabase.co:5432/postgres?sslmode=require"
        )

        self.assertEqual("postgresql://example.supabase.co:5432/postgres", label)
        self.assertNotIn("secret", label)


if __name__ == "__main__":
    unittest.main()
