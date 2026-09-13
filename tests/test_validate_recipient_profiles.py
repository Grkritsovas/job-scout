import unittest
from unittest.mock import patch

from tools.validate_recipient_profiles import (
    print_validation_results,
    validate_profile_configs,
)


def make_profile(**overrides):
    profile = {
        "id": "george",
        "enabled": True,
        "delivery": {"email": "george@example.com", "language": "Greek"},
        "candidate": {
            "summary": "Early-career Python and ML project experience.",
            "target_roles": [{"id": "swe"}],
        },
        "job_preferences": {
            "location": "Greece",
            "target_seniority": {
                "max_explicit_years": 1,
                "boost_multiplier": 1.2,
                "boost_title_terms": ["junior", "graduate"],
            },
            "salary": {
                "preferred_max_gbp": 45000,
                "hard_cap_gbp": 55000,
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
    }
    profile.update(overrides)
    return profile


class ValidateRecipientProfilesTests(unittest.TestCase):
    def test_validate_profile_configs_accepts_valid_grouped_profile(self):
        results = validate_profile_configs([make_profile()])

        self.assertEqual(1, len(results))
        self.assertTrue(results[0]["ok"])
        self.assertEqual("george", results[0]["recipient_id"])
        self.assertEqual("george@example.com", results[0]["email"])
        self.assertEqual("Greek", results[0]["language"])
        self.assertEqual("Greece", results[0]["location"])
        self.assertEqual(["swe"], results[0]["target_roles"])

    def test_validate_profile_configs_collects_invalid_profile_errors(self):
        results = validate_profile_configs(
            [
                make_profile(
                    id="missing-email",
                    delivery={"email": ""},
                )
            ]
        )

        self.assertEqual(1, len(results))
        self.assertFalse(results[0]["ok"])
        self.assertIn("missing delivery.email", results[0]["error"])

    def test_validate_profile_configs_reports_duplicate_normalized_ids(self):
        results = validate_profile_configs(
            [
                make_profile(id="George"),
                make_profile(id="george", delivery={"email": "other@example.com"}),
            ]
        )

        self.assertEqual(2, len(results))
        self.assertFalse(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertIn("Duplicate normalized recipient id", results[0]["error"])
        self.assertIn("Duplicate normalized recipient id", results[1]["error"])

    def test_print_validation_results_uses_compact_lines(self):
        results = validate_profile_configs([make_profile()])

        with patch("builtins.print") as print_mock:
            print_validation_results(results)

        line = print_mock.call_args.args[0]
        self.assertIn("OK profile[0]", line)
        self.assertIn("id=george", line)
        self.assertIn("language=Greek", line)
        self.assertIn("location=Greece", line)
        self.assertIn("target_roles=swe", line)


if __name__ == "__main__":
    unittest.main()
