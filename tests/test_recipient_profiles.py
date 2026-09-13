import os
import unittest
from pathlib import Path
from unittest.mock import patch

from config.recipient_profiles import (
    load_recipient_profiles,
    normalize_grouped_profile,
    prepare_recipient_profile_db_rows,
)
from storage import create_storage


class RecipientProfilesTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/.tmp_recipient_profiles")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for child in self.test_dir.glob("*"):
            child.unlink()
        self.test_dir.rmdir()

    def test_normalize_grouped_profile_maps_runtime_fields(self):
        grouped_profile = normalize_grouped_profile(
            {
                "id": "george",
                "enabled": True,
                "delivery": {"email": "george@example.com", "language": "Greek"},
                "candidate": {
                    "summary": "Strong Python and ML project experience for junior roles.",
                    "education_status": "Graduated Oct 2025; not a current student.",
                    "target_roles": [
                        {"id": "swe"},
                        {
                            "id": "data_analyst",
                            "match_text": "Early-career data analyst profile text.",
                        },
                    ],
                },
                "job_preferences": {
                    "location": "Greece",
                    "target_seniority": {
                        "max_explicit_years": 2,
                        "boost_multiplier": 1.15,
                        "boost_title_terms": ["junior", "graduate", "apprentice"],
                    },
                    "salary": {
                        "preferred_max_gbp": 45000,
                        "hard_cap_gbp": 50000,
                        "penalty_strength": 0.35,
                    },
                },
                "eligibility": {
                    "needs_sponsorship": True,
                    "work_authorization_summary": "Graduate visa valid until Feb 2028.",
                    "check_hard_eligibility": True,
                    "use_sponsor_lookup": True,
                },
                "matching": {
                    "semantic_threshold": 0.51,
                },
                "llm_review": {
                    "extra_screening_guidance": [
                        "Prefer clearly junior titles.",
                    ],
                    "extra_final_ranking_guidance": [
                        "Prefer realistic employability over prestige.",
                    ],
                },
            }
        )

        rows = prepare_recipient_profile_db_rows([grouped_profile])
        self.assertEqual(1, len(rows))
        self.assertEqual("george", rows[0]["recipient_id"])
        self.assertEqual("george@example.com", rows[0]["email"])
        self.assertEqual("Greek", rows[0]["config"]["delivery"]["language"])
        self.assertEqual(
            "Greece",
            rows[0]["config"]["job_preferences"]["location"],
        )
        self.assertEqual(2, rows[0]["config"]["job_preferences"]["target_seniority"]["max_explicit_years"])
        self.assertEqual(
            "Graduated Oct 2025; not a current student.",
            rows[0]["config"]["candidate"]["education_status"],
        )
        self.assertEqual(
            "Graduate visa valid until Feb 2028.",
            rows[0]["config"]["eligibility"]["work_authorization_summary"],
        )

    def test_normalize_grouped_profile_rejects_unknown_eligibility_fields(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "Unknown recipient profile field 'eligibility.education_status'",
        ):
            normalize_grouped_profile(
                {
                    "id": "demo",
                    "delivery": {"email": "demo@example.com"},
                    "candidate": {
                        "summary": "Profile summary.",
                        "target_roles": [{"id": "swe"}],
                    },
                    "eligibility": {
                        "needs_sponsorship": False,
                        "education_status": "Graduated Oct 2025.",
                    },
                }
            )

    def test_normalize_grouped_profile_rejects_unknown_target_role_fields(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "Unknown recipient profile field 'candidate.target_roles\\[\\].education_status'",
        ):
            normalize_grouped_profile(
                {
                    "id": "demo",
                    "delivery": {"email": "demo@example.com"},
                    "candidate": {
                        "summary": "Profile summary.",
                        "target_roles": [
                            {
                                "id": "swe",
                                "education_status": "Graduated Oct 2025.",
                            }
                        ],
                    },
                }
            )

    def test_normalize_grouped_profile_rejects_unsupported_location(self):
        with self.assertRaisesRegex(ValueError, "Unsupported location preset"):
            normalize_grouped_profile(
                {
                    "id": "demo",
                    "delivery": {"email": "demo@example.com"},
                    "candidate": {"target_roles": [{"id": "swe"}]},
                    "job_preferences": {"location": "Spain"},
                }
            )

    def test_loads_profiles_from_storage(self):
        db_path = self.test_dir / "profiles.db"
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()
        storage.upsert_recipient_profile_configs(
            prepare_recipient_profile_db_rows(
                [
                    {
                        "id": "george",
                        "enabled": True,
                        "delivery": {"email": "george@example.com", "language": "Greek"},
                        "candidate": {
                            "summary": "Strong Python and ML project experience.",
                            "education_status": "Graduated Oct 2025; not a current student.",
                            "target_roles": [{"id": "swe"}],
                        },
                        "job_preferences": {
                            "location": "Greece",
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
                            "work_authorization_summary": (
                                "Greek citizen with pre-settled status."
                            ),
                            "check_hard_eligibility": True,
                            "use_sponsor_lookup": True,
                        },
                        "matching": {
                            "semantic_threshold": 0.5,
                        },
                        "llm_review": {
                            "extra_screening_guidance": [
                                "Prefer early-career roles."
                            ],
                            "extra_final_ranking_guidance": [
                                "Prefer clearer evidence."
                            ],
                        },
                    },
                    {
                        "id": "disabled",
                        "enabled": False,
                        "delivery": {"email": "disabled@example.com"},
                        "candidate": {
                            "summary": "",
                            "target_roles": [{"id": "swe"}],
                        },
                        "job_preferences": {
                            "target_seniority": {
                                "max_explicit_years": 1,
                                "boost_multiplier": 1.2,
                                "boost_title_terms": ["junior"],
                            },
                            "salary": {
                                "preferred_max_gbp": None,
                                "hard_cap_gbp": None,
                                "penalty_strength": 0.35,
                            },
                        },
                        "eligibility": {
                            "needs_sponsorship": False,
                            "check_hard_eligibility": False,
                            "use_sponsor_lookup": False,
                        },
                        "matching": {
                            "semantic_threshold": 0.42,
                        },
                        "llm_review": {
                            "extra_screening_guidance": [],
                            "extra_final_ranking_guidance": [],
                        },
                    },
                ]
            )
        )

        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": f"sqlite:///{db_path}",
                "JOB_SCRAPER_EMAIL": "sender@example.com",
            },
            clear=True,
        ):
            profiles = load_recipient_profiles(storage=storage)

        self.assertEqual(1, len(profiles))
        self.assertEqual("george", profiles[0]["id"])
        self.assertEqual("george@example.com", profiles[0]["email"])
        self.assertEqual("Greek", profiles[0]["communication_language"])
        self.assertEqual("Greece", profiles[0]["location_preset"])
        self.assertEqual(["swe"], profiles[0]["semantic_profiles"])
        self.assertEqual(2, profiles[0]["max_years_experience"])
        self.assertEqual(
            "Graduated Oct 2025; not a current student.",
            profiles[0]["education_status"],
        )
        self.assertEqual(
            "Greek citizen with pre-settled status.",
            profiles[0]["work_authorization_summary"],
        )
        self.assertEqual(["Prefer early-career roles."], profiles[0]["extra_screening_guidance"])
        self.assertEqual(["Prefer clearer evidence."], profiles[0]["extra_final_ranking_guidance"])

    def test_load_recipient_profiles_requires_database_url(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is required"):
                load_recipient_profiles()

    def test_load_recipient_profiles_requires_db_profiles(self):
        db_path = self.test_dir / "empty.db"
        storage = create_storage(f"sqlite:///{db_path}")
        storage.ensure_schema()

        with self.assertRaisesRegex(RuntimeError, "No enabled recipient profiles"):
            load_recipient_profiles(storage=storage)


if __name__ == "__main__":
    unittest.main()
