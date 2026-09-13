import unittest

from semantic_matching import (
    build_profile_specs,
    extract_required_experience_years,
    extract_salary_upper_bound_gbp,
    get_hard_filter_reason,
    rank_jobs,
)


class FakeMatcher:
    def __init__(self):
        self.scored_descriptions = []

    def score_description(self, description, profile_specs):
        self.scored_descriptions.append(description)
        top_label = profile_specs[0]["label"]
        second_label = profile_specs[1]["label"] if len(profile_specs) > 1 else top_label
        if "strong_fit" in description:
            top_score = 0.56
        elif "borderline_fit" in description:
            top_score = 0.46
        else:
            top_score = 0.52
        second_score = max(0.0, top_score - 0.08)
        return {
            "profile_scores": {
                spec["label"]: top_score - (index * 0.08)
                for index, spec in enumerate(profile_specs)
            },
            "top_profile": top_label,
            "top_score": top_score,
            "ranking_score": top_score,
            "second_profile": second_label,
            "second_score": second_score,
            "score_margin": top_score - second_score,
            "fit_summary": " | ".join(
                f"{spec['label']} {round((top_score - (index * 0.08)) * 100)}%"
                for index, spec in enumerate(profile_specs)
            ),
        }


def make_job(**overrides):
    base = {
        "company": "Example",
        "title": "Software Engineer",
        "url": "https://example.com/job",
        "description": "strong_fit",
        "locations": ["London"],
        "location": "London",
        "source": "example",
        "target_value": "example",
        "sponsorship_status": "unknown",
        "is_sponsor_licensed_employer": False,
    }
    base.update(overrides)
    return base


class SemanticMatchingTests(unittest.TestCase):
    def test_unknown_profile_id_falls_back_to_generated_profile_text(self):
        recipient_profile = {
            "semantic_profiles": ["marketing_assistant"],
            "semantic_profile_texts": {},
        }

        specs = build_profile_specs(recipient_profile)

        self.assertEqual(1, len(specs))
        self.assertEqual("marketing_assistant", specs[0]["id"])
        self.assertEqual("Marketing Assistant", specs[0]["label"])
        self.assertIn("entry-level marketing assistant roles", specs[0]["text"])

    def test_get_hard_filter_reason_identifies_commercial_title(self):
        reason = get_hard_filter_reason(
            make_job(title="Account Executive", description="strong_fit")
        )
        self.assertEqual("title_commercial", reason)

    def test_commercial_title_matching_uses_whole_terms(self):
        reason = get_hard_filter_reason(
            make_job(title="Salesforce Developer", description="strong_fit")
        )
        self.assertIsNone(reason)

    def test_marketing_title_is_rejected_without_marketing_target(self):
        reason = get_hard_filter_reason(
            make_job(title="Marketing Assistant", description="strong_fit"),
            recipient_profile={"semantic_profiles": ["swe", "data_science"]},
        )
        self.assertEqual("title_commercial", reason)

    def test_marketing_title_is_allowed_for_marketing_target(self):
        reason = get_hard_filter_reason(
            make_job(title="Marketing Assistant", description="strong_fit"),
            recipient_profile={"semantic_profiles": ["marketing_assistant"]},
        )
        self.assertIsNone(reason)

    def test_greece_profile_uses_greece_location_filter(self):
        greek_job = make_job(location="Remote - Greece", locations=["Remote - Greece"])

        self.assertIsNone(
            get_hard_filter_reason(
                greek_job,
                recipient_profile={
                    "semantic_profiles": ["marketing_assistant"],
                    "location_preset": "Greece",
                },
            )
        )
        self.assertEqual(
            "location",
            get_hard_filter_reason(
                greek_job,
                recipient_profile={
                    "semantic_profiles": ["marketing_assistant"],
                    "location_preset": "UK",
                },
            ),
        )

    def test_get_hard_filter_reason_rejects_two_plus_years_for_junior_pipeline(self):
        reason = get_hard_filter_reason(
            make_job(description="Requires 2+ years of experience in Python."),
        )
        self.assertEqual("experience", reason)

    def test_get_hard_filter_reason_rejects_professional_experience_range(self):
        reason = get_hard_filter_reason(
            make_job(
                description=(
                    "Qualifications: 3–7 years of professional software "
                    "engineering experience."
                ),
            ),
        )
        self.assertEqual("experience", reason)

    def test_experience_range_uses_upper_bound(self):
        years = extract_required_experience_years(
            "Requires 1\u20133 years of professional software engineering experience."
        )

        self.assertTrue(years)
        self.assertTrue(all(year == 3 for year in years))

    def test_internship_title_can_pass_when_student_requirement_absent(self):
        reason = get_hard_filter_reason(
            make_job(title="Software Engineering Internship", description="strong_fit")
        )
        self.assertIsNone(reason)

    def test_internship_rejects_current_student_requirement(self):
        reason = get_hard_filter_reason(
            make_job(
                title="Software Engineering Internship",
                description="Applicants must be currently enrolled in a degree.",
            )
        )
        self.assertEqual("eligibility", reason)

    def test_internship_rejects_currently_pursuing_degree_requirement(self):
        reason = get_hard_filter_reason(
            make_job(
                title="Software Engineer Intern",
                description=(
                    "Academic Foundation: Currently pursuing a B.S. or M.S. Degree "
                    "in Computer Science with a graduation date between Autumn 2026 "
                    "and Summer 2027."
                ),
            )
        )
        self.assertEqual("eligibility", reason)

    def test_authorization_ignores_us_applicant_boilerplate_when_uk_section_exists(self):
        reason = get_hard_filter_reason(
            make_job(
                title="Technical Support Specialist",
                location="London",
                locations=["London"],
                description=(
                    "Hybrid role based out of London. "
                    "For United States Applicants: the company will confirm that "
                    "you are authorized to work in the United States. "
                    "For United Kingdom Applicants: the company will verify your "
                    "right to work in the UK before employment."
                ),
            )
        )
        self.assertIsNone(reason)

    def test_authorization_rejects_us_only_requirement(self):
        reason = get_hard_filter_reason(
            make_job(
                description=(
                    "Candidates must be authorized to work in the United States."
                ),
            )
        )
        self.assertEqual("authorization", reason)

    def test_graduating_between_range_is_not_hard_rejected(self):
        reason = get_hard_filter_reason(
            make_job(
                title="Graduate Software Engineer",
                description=(
                    "Open to graduates and people graduating between 2024 and 2026."
                ),
            )
        )
        self.assertIsNone(reason)

    def test_deep_experience_requirement_is_rejected_for_junior_pipeline(self):
        reason = get_hard_filter_reason(
            make_job(
                title="Software Engineer, Internal Infrastructure",
                description=(
                    "You may be a good fit if you have deep experience running "
                    "Kubernetes clusters at scale and troubleshooting cloud native "
                    "infrastructure."
                ),
            )
        )
        self.assertEqual("experience", reason)

    def test_recipient_specific_max_years_experience_relaxes_hard_filter(self):
        jobs = [
            make_job(
                url="https://example.com/two-years",
                description="Requires 2+ years of experience in Python.",
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.45,
            "max_years_experience": 2,
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())
        self.assertEqual(1, len(ranked_jobs))

    def test_sponsorship_status_is_info_only_for_ranking(self):
        jobs = [
            make_job(
                url="https://example.com/no",
                sponsorship_status="explicit_no",
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.45,
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())
        self.assertEqual(1, len(ranked_jobs))

    def test_recipient_specific_threshold_applies(self):
        jobs = [make_job(url="https://example.com/borderline", description="borderline_fit")]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.47,
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())
        self.assertEqual([], ranked_jobs)

    def test_junior_title_boost_can_push_borderline_match_above_threshold(self):
        jobs = [
            make_job(
                title="Graduate Data Analyst",
                url="https://example.com/graduate-borderline",
                description="borderline_fit",
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["data_analyst", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.47,
            "junior_boost_multiplier": 1.2,
            "junior_boost_terms": [
                "junior",
                "grad",
                "graduate",
                "entry level",
                "entry-level",
            ],
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())

        self.assertEqual(1, len(ranked_jobs))
        self.assertAlmostEqual(0.46, ranked_jobs[0]["raw_embedding_score"])
        self.assertAlmostEqual(0.552, ranked_jobs[0]["top_score"])
        self.assertEqual(1.2, ranked_jobs[0]["title_boost_multiplier"])

    def test_junior_title_boost_multiplier_is_configurable(self):
        jobs = [
            make_job(
                title="Graduate Data Analyst",
                url="https://example.com/graduate-custom-boost",
                description="borderline_fit",
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["data_analyst", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.47,
            "junior_boost_multiplier": 1.1,
            "junior_boost_terms": [
                "junior",
                "grad",
                "graduate",
                "entry level",
                "entry-level",
            ],
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())

        self.assertEqual(1, len(ranked_jobs))
        self.assertAlmostEqual(0.506, ranked_jobs[0]["top_score"])
        self.assertEqual(1.1, ranked_jobs[0]["title_boost_multiplier"])

    def test_junior_boost_terms_are_configurable(self):
        jobs = [
            make_job(
                title="Apprentice Data Analyst",
                url="https://example.com/apprentice-borderline",
                description="borderline_fit",
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["data_analyst", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.47,
            "junior_boost_multiplier": 1.2,
            "junior_boost_terms": ["junior", "graduate", "apprentice"],
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())

        self.assertEqual(1, len(ranked_jobs))
        self.assertAlmostEqual(0.552, ranked_jobs[0]["top_score"])
        self.assertEqual(1.2, ranked_jobs[0]["title_boost_multiplier"])

    def test_salary_penalty_filters_unrealistic_salary_range(self):
        jobs = [
            make_job(
                url="https://example.com/high-salary",
                description="Salary range: GBP 51,000 - GBP 80,000 plus benefits.",
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.45,
            "preferred_salary_max_gbp": 45000,
            "salary_hard_cap_gbp": 50000,
            "salary_penalty_max": 0.35,
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())
        self.assertEqual([], ranked_jobs)

    def test_salary_parser_handles_real_pound_and_en_dash(self):
        upper_bound = extract_salary_upper_bound_gbp(
            "Salary range: \u00a351,000 \u2013 \u00a380,000 plus benefits."
        )

        self.assertEqual(80000.0, upper_bound)

    def test_salary_penalty_does_not_apply_when_not_configured(self):
        jobs = [
            make_job(
                url="https://example.com/high-salary-allowed",
                description="Salary range: GBP 51,000 - GBP 80,000 plus benefits.",
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.45,
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())
        self.assertEqual(1, len(ranked_jobs))

    def test_html_like_description_can_still_rank(self):
        jobs = [
            make_job(
                url="https://example.com/html",
                description="<html><body>role page</body></html>",
                description_looks_like_html=True,
                description_status="raw_html_fallback",
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.43,
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        ranked_jobs = rank_jobs(jobs, recipient_profile, matcher=FakeMatcher())
        self.assertEqual(1, len(ranked_jobs))
        self.assertTrue(ranked_jobs[0]["description_looks_like_html"])

    def test_rank_jobs_includes_title_and_strips_boilerplate_in_match_text(self):
        matcher = FakeMatcher()
        jobs = [
            make_job(
                title="Full Stack Engineer",
                description=(
                    "Build full-stack product features with React and Java. "
                    "Our Commitment to Diversity, Equity, Inclusion and Belonging "
                    "We believe attracting and retaining the best talent matters."
                ),
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.43,
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        rank_jobs(jobs, recipient_profile, matcher=matcher)

        self.assertEqual(1, len(matcher.scored_descriptions))
        scored_text = matcher.scored_descriptions[0]
        self.assertIn("Role title: Full Stack Engineer", scored_text)
        self.assertIn("Build full-stack product features with React and Java.", scored_text)
        self.assertNotIn("Our Commitment to Diversity", scored_text)

    def test_rank_jobs_focuses_role_section_in_match_text(self):
        matcher = FakeMatcher()
        company_intro = (
            "Acme builds AI planning software for global enterprises and "
            "celebrates customer success across finance and operations. "
        ) * 5
        jobs = [
            make_job(
                title="Software Engineer",
                description=(
                    company_intro
                    + "About the role You will build strong_fit Python APIs, "
                    "data tools, internal dashboards, tests, and integrations. "
                    "You will work with senior engineers, debug production issues "
                    "with guidance, document decisions, and improve maintainable "
                    "backend services for technical users. Requirements include "
                    "Python, SQL, Git, and curiosity. What we offer benefits and "
                    "perks for employees. Our commitment to Diversity, Equity and "
                    "Inclusion matters."
                ),
            )
        ]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
            "min_top_score": 0.43,
            "care_about_sponsorship": False,
            "use_sponsor_lookup": False,
        }

        rank_jobs(jobs, recipient_profile, matcher=matcher)

        scored_text = matcher.scored_descriptions[0]
        self.assertIn("About the role", scored_text)
        self.assertIn("strong_fit Python APIs", scored_text)
        self.assertNotIn("Acme builds AI planning software", scored_text)
        self.assertNotIn("What we offer", scored_text)
        self.assertNotIn("Diversity, Equity", scored_text)

    def test_rank_jobs_returns_audit_rows_with_hard_filter_cap(self):
        senior_jobs = [
            make_job(
                title=f"Senior Software Engineer {index}",
                url=f"https://example.com/senior-{index}",
            )
            for index in range(35)
        ]
        ranked_jobs, stats = rank_jobs(
            senior_jobs,
            {
                "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
                "min_top_score": 0.43,
            },
            matcher=FakeMatcher(),
            return_stats=True,
        )

        self.assertEqual([], ranked_jobs)
        hard_filter_rows = [
            row
            for row in stats["audit_rows"]
            if row["classification"] == "hard_filtered"
        ]
        self.assertEqual(30, len(hard_filter_rows))
        self.assertTrue(
            all(row["hard_filter_reason"] == "title_seniority" for row in hard_filter_rows)
        )

    def test_rank_jobs_returns_semantic_below_and_above_audit_rows(self):
        jobs = [
            make_job(
                url="https://example.com/below",
                description="borderline_fit",
            ),
            make_job(
                url="https://example.com/above",
                description="strong_fit",
            ),
        ]
        ranked_jobs, stats = rank_jobs(
            jobs,
            {
                "semantic_profiles": ["swe", "data_science", "ai_ml_engineer"],
                "min_top_score": 0.5,
            },
            matcher=FakeMatcher(),
            return_stats=True,
        )

        self.assertEqual(["https://example.com/above"], [job["url"] for job in ranked_jobs])
        classifications = {
            row["job_url"]: row["classification"]
            for row in stats["audit_rows"]
        }
        self.assertEqual("semantic_below_threshold", classifications["https://example.com/below"])
        self.assertEqual("semantic_above_threshold", classifications["https://example.com/above"])
        raw_scores = {
            row["job_url"]: row["raw_embedding_score"]
            for row in stats["audit_rows"]
            if row["classification"].startswith("semantic_")
        }
        self.assertAlmostEqual(0.46, raw_scores["https://example.com/below"])
        self.assertAlmostEqual(0.56, raw_scores["https://example.com/above"])


if __name__ == "__main__":
    unittest.main()
