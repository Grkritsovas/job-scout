import json
import os
import threading
import unittest
from unittest.mock import patch

import matching.gemini_rerank as gemini_rerank_module
from matching.gemini_rerank import rerank_jobs_with_gemini


def make_job(index, **overrides):
    base = {
        "company": "Example",
        "title": f"Software Engineer {index}",
        "url": f"https://example.com/job-{index}",
        "description": (
            "Build backend APIs in Python and support product features for an "
            "early-career engineering team."
        ),
        "location": "London",
        "top_profile": "SWE",
        "top_score": 0.58,
        "second_profile": "Data Science",
        "second_score": 0.46,
        "ranking_score": 0.58,
        "score_margin": 0.12,
    }
    base.update(overrides)
    return base


class FakeResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload)


class FakeModels:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(
            {
                "model": model,
                "contents": contents,
                "config": config,
            }
        )
        return FakeResponse(self.payloads.pop(0))


class FakeClient:
    def __init__(self, payloads):
        self.models = FakeModels(payloads)


class GeminiRerankTests(unittest.TestCase):
    def test_generate_json_response_caps_concurrent_gemini_calls_at_four(self):
        state = {
            "active_calls": 0,
            "max_active_calls": 0,
        }
        state_lock = threading.Lock()
        release_event = threading.Event()
        completed = []

        class BlockingModels:
            def generate_content(self, model, contents, config):
                with state_lock:
                    state["active_calls"] += 1
                    state["max_active_calls"] = max(
                        state["max_active_calls"],
                        state["active_calls"],
                    )
                release_event.wait(timeout=2)
                with state_lock:
                    state["active_calls"] -= 1
                return FakeResponse({"candidates": []})

        class BlockingClient:
            def __init__(self):
                self.models = BlockingModels()

        def run_request():
            payload = gemini_rerank_module._generate_json_response(
                BlockingClient(),
                "gemini-2.5-flash",
                "prompt",
                {"type": "object"},
                retry_deadline=time.monotonic() + 5,
            )
            completed.append(payload)

        import time

        threads = [threading.Thread(target=run_request) for _ in range(5)]
        for thread in threads:
            thread.start()

        while True:
            with state_lock:
                if state["active_calls"] == 4:
                    break

        release_event.set()

        for thread in threads:
            thread.join(timeout=2)

        self.assertEqual(5, len(completed))
        self.assertEqual(4, state["max_active_calls"])

    def test_rerank_uses_profiles_cv_summary_and_two_pass_shortlist(self):
        jobs = [
            make_job(1),
            make_job(
                2,
                title="Graduate Data Analyst",
                salary_upper_bound_gbp=100000.0,
            ),
        ]
        recipient_profile = {
            "semantic_profiles": ["swe", "data_science"],
            "semantic_profile_texts": {},
            "cv_summary": "Strong Python, ML, and data project experience.",
            "education_status": "Graduated Oct 2025; not a current student.",
            "work_authorization_summary": "Graduate visa valid until Feb 2028.",
            "communication_language": "Greek",
            "max_years_experience": 1,
            "preferred_salary_max_gbp": 85000.0,
            "salary_hard_cap_gbp": 95000.0,
            "extra_screening_guidance": [
                "Prefer roles explicitly framed as junior or early-career opportunities."
            ],
            "extra_final_ranking_guidance": [
                "Prefer realistic employability over prestige or thematic overlap."
            ],
        }
        client = FakeClient(
            [
                {
                    "candidates": [
                        {
                            "job_url": "https://example.com/job-2",
                            "matched_profile": "Data Science",
                            "fit_score": 84,
                            "why_apply": (
                                "Junior-friendly role with analytical work. "
                                "Your Python and ML experience transfer well."
                            ),
                            "supporting_evidence": [
                                "Graduate Data Analyst",
                                "Build backend APIs in Python",
                            ],
                            "mismatch_evidence": [],
                        }
                    ]
                },
                {
                    "shortlisted_jobs": [
                        {
                            "job_url": "https://example.com/job-2",
                            "fit_score": 88,
                            "why_apply": (
                                "Strong junior data fit with practical analysis work. "
                                "Your Python and ML project experience transfer well."
                            ),
                        }
                    ]
                }
            ]
        )

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            result = rerank_jobs_with_gemini(
                jobs,
                recipient_profile,
                client=client,
                top_n=2,
                batch_size=10,
            )

        reranked = result["jobs_to_send"]
        self.assertEqual("gemini", result["review_mode"])
        self.assertEqual(2, len(result["reviewed_jobs"]))
        self.assertEqual(1, result["llm_shortlisted_jobs"])
        self.assertEqual(2, result["gemini_reviewed_jobs"])
        self.assertEqual(1, len(reranked))
        self.assertEqual("https://example.com/job-2", reranked[0]["url"])
        self.assertEqual(88, reranked[0]["llm_fit_score"])
        self.assertAlmostEqual(0.88, reranked[0]["ranking_score"])
        self.assertEqual("Data Science", reranked[0]["llm_matched_profile"])
        self.assertIn("Strong junior data fit", reranked[0]["why_apply"])
        self.assertEqual(
            ["Graduate Data Analyst", "Build backend APIs in Python"],
            reranked[0]["supporting_evidence"],
        )
        audit_by_url = {
            row["job_url"]: row
            for row in result["audit_rows"]
        }
        self.assertEqual(
            "gemini_pass1_rejected_seen",
            audit_by_url["https://example.com/job-1"]["classification"],
        )
        self.assertTrue(audit_by_url["https://example.com/job-1"]["seen_recorded"])
        self.assertEqual(
            "gemini_pass2_approved_sent_seen",
            audit_by_url["https://example.com/job-2"]["classification"],
        )
        self.assertTrue(audit_by_url["https://example.com/job-2"]["sent"])
        self.assertEqual(84, audit_by_url["https://example.com/job-2"]["gemini_pass1_score"])
        self.assertEqual(88, audit_by_url["https://example.com/job-2"]["gemini_pass2_score"])

        first_prompt = client.models.calls[0]["contents"]
        second_prompt = client.models.calls[1]["contents"]
        semantic_hint_warning = (
            "semantic_fit_hint is a rough embedding retrieval signal, not calibrated "
            "probability or evidence of realistic fit."
        )
        self.assertIn("Strong Python, ML, and data project experience.", first_prompt)
        self.assertIn("Graduated Oct 2025; not a current student.", first_prompt)
        self.assertIn("Graduate visa valid until Feb 2028.", first_prompt)
        self.assertIn('"label": "SWE"', first_prompt)
        self.assertIn('"label": "Data Science"', first_prompt)
        self.assertIn('"url": "https://example.com/job-2"', first_prompt)
        self.assertIn('"semantic_fit_hint": "SWE 58% | Data Science 46%"', first_prompt)
        self.assertIn('"preferred_salary_max_gbp": 85000.0', first_prompt)
        self.assertIn('"salary_hard_cap_gbp": 95000.0', first_prompt)
        self.assertIn('"salary_upper_bound_gbp": 100000.0', first_prompt)
        self.assertIn(
            "Prefer roles explicitly framed as junior or early-career opportunities.",
            first_prompt,
        )
        self.assertIn('"student_programme_rule"', first_prompt)
        self.assertIn("current-student status", first_prompt)
        self.assertIn("Do not reject an internship merely", first_prompt)
        self.assertIn('"domain_mismatch_examples"', first_prompt)
        self.assertIn("Software mismatch example", first_prompt)
        self.assertIn("Data mismatch example", first_prompt)
        self.assertIn('"fit_dimension_rule"', first_prompt)
        self.assertIn("strong thematic relevance", first_prompt)
        self.assertIn('"hard_requirement_rule"', first_prompt)
        self.assertIn("Penalize hard requirements", first_prompt)
        self.assertIn('"semantic_hint_rule"', first_prompt)
        self.assertIn(semantic_hint_warning, first_prompt)
        self.assertIn('"junior_claim_rule"', first_prompt)
        self.assertIn("Do not describe a role as junior", first_prompt)
        self.assertIn('"junior_targeting_rule"', first_prompt)
        self.assertIn("accepts academic/project experience", first_prompt)
        self.assertIn('"communication_language_rule"', first_prompt)
        self.assertIn("Write user-facing why_apply text in Greek", first_prompt)
        self.assertIn('"matched_profile": "Data Science"', second_prompt)
        self.assertIn('"semantic_fit_hint": "SWE 58% | Data Science 46%"', second_prompt)
        self.assertIn("Graduated Oct 2025; not a current student.", second_prompt)
        self.assertIn("Graduate visa valid until Feb 2028.", second_prompt)
        self.assertIn('"supporting_evidence": [', second_prompt)
        self.assertIn('"batch_fit_score": 84', second_prompt)
        self.assertIn('"salary_upper_bound_gbp": 100000.0', second_prompt)
        self.assertIn(
            "Prefer realistic employability over prestige or thematic overlap.",
            second_prompt,
        )
        self.assertIn('"student_programme_rule"', second_prompt)
        self.assertIn("Do not drop an internship merely", second_prompt)
        self.assertIn('"domain_mismatch_examples"', second_prompt)
        self.assertIn("Software mismatch example", second_prompt)
        self.assertIn("Data mismatch example", second_prompt)
        self.assertIn('"fit_dimension_rule"', second_prompt)
        self.assertIn('"hard_requirement_rule"', second_prompt)
        self.assertIn('"semantic_hint_rule"', second_prompt)
        self.assertIn(semantic_hint_warning, second_prompt)
        self.assertIn('"junior_claim_rule"', second_prompt)
        self.assertIn('"junior_targeting_rule"', second_prompt)
        self.assertIn('"communication_language_rule"', second_prompt)
        self.assertIn("Write user-facing why_apply text in Greek", second_prompt)

    def test_gemini_job_payload_uses_role_focused_default_excerpt(self):
        description = (
            ("Company intro and mission statement. " * 12)
            + "About the role "
            + ("requirements detail " * 120)
            + "Our benefits "
            + ("low signal benefit text " * 30)
        )

        payload = gemini_rerank_module._build_job_payload(
            make_job(1, description=description),
            gemini_rerank_module.DEFAULT_DESCRIPTION_CHARS,
        )

        excerpt = payload["description_excerpt"]
        self.assertEqual(8000, gemini_rerank_module.DEFAULT_DESCRIPTION_CHARS)
        self.assertGreater(len(excerpt), 1600)
        self.assertTrue(excerpt.startswith("About the role"))
        self.assertNotIn("Company intro", excerpt)
        self.assertNotIn("Our benefits", excerpt)

    def test_junior_targeting_rule_requires_low_experience_flag(self):
        base_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }

        general_prompt = gemini_rerank_module._build_pass_one_prompt(
            base_profile,
            [make_job(1)],
            gemini_rerank_module.DEFAULT_DESCRIPTION_CHARS,
        )
        junior_prompt = gemini_rerank_module._build_pass_one_prompt(
            {**base_profile, "max_years_experience": 2},
            [make_job(1)],
            gemini_rerank_module.DEFAULT_DESCRIPTION_CHARS,
        )

        self.assertNotIn('"junior_targeting_rule"', general_prompt)
        self.assertIn('"junior_targeting_rule"', junior_prompt)

    def test_domain_mismatch_examples_follow_target_role_words(self):
        marketing_prompt = gemini_rerank_module._build_pass_one_prompt(
            {
                "semantic_profiles": ["growth_marketing_coordinator"],
                "semantic_profile_texts": {},
            },
            [make_job(1)],
            gemini_rerank_module.DEFAULT_DESCRIPTION_CHARS,
        )
        software_prompt = gemini_rerank_module._build_pass_one_prompt(
            {
                "semantic_profiles": ["sde"],
                "semantic_profile_texts": {},
            },
            [make_job(1)],
            gemini_rerank_module.DEFAULT_DESCRIPTION_CHARS,
        )

        self.assertIn("Marketing mismatch example", marketing_prompt)
        self.assertNotIn("Software mismatch example", marketing_prompt)
        self.assertIn("Software mismatch example", software_prompt)
        self.assertNotIn("Marketing mismatch example", software_prompt)

    def test_rerank_uses_top_n_and_splits_batches(self):
        jobs = [make_job(index) for index in range(1, 13)]
        recipient_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }
        client = FakeClient(
            [
                {"candidates": []},
                {"candidates": []},
            ]
        )

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            result = rerank_jobs_with_gemini(
                jobs,
                recipient_profile,
                client=client,
                top_n=11,
                batch_size=10,
            )

        self.assertEqual("gemini", result["review_mode"])
        self.assertEqual([], result["jobs_to_send"])
        self.assertEqual(11, len(result["reviewed_jobs"]))
        self.assertEqual(0, result["llm_shortlisted_jobs"])
        self.assertEqual(11, result["gemini_reviewed_jobs"])
        self.assertEqual(2, len(client.models.calls))
        self.assertIn('"url": "https://example.com/job-10"', client.models.calls[0]["contents"])
        self.assertNotIn(
            '"url": "https://example.com/job-11"',
            client.models.calls[0]["contents"],
        )
        self.assertIn('"url": "https://example.com/job-11"', client.models.calls[1]["contents"])
        self.assertNotIn('"url": "https://example.com/job-12"', client.models.calls[1]["contents"])

    def test_rerank_audits_pass_two_rejections_as_seen(self):
        jobs = [make_job(1)]
        recipient_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }
        client = FakeClient(
            [
                {
                    "candidates": [
                        {
                            "job_url": "https://example.com/job-1",
                            "matched_profile": "SWE",
                            "fit_score": 78,
                            "why_apply": "Possible junior engineering fit.",
                            "supporting_evidence": ["Software Engineer 1"],
                            "mismatch_evidence": [],
                        }
                    ],
                    "rejected_jobs": [],
                },
                {
                    "shortlisted_jobs": [],
                    "rejected_jobs": [
                        {
                            "job_url": "https://example.com/job-1",
                            "rejection_reason": "Weaker than the final shortlist.",
                            "mismatch_evidence": ["Possible junior engineering fit."],
                        }
                    ],
                },
            ]
        )

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            result = rerank_jobs_with_gemini(
                jobs,
                recipient_profile,
                client=client,
                top_n=1,
                batch_size=10,
            )

        self.assertEqual([], result["jobs_to_send"])
        self.assertEqual(1, len(result["reviewed_jobs"]))
        self.assertEqual(
            ["gemini_pass1_approved_pass2_rejected_seen"],
            [row["classification"] for row in result["audit_rows"]],
        )
        self.assertTrue(result["audit_rows"][0]["seen_recorded"])

    def test_rerank_returns_no_jobs_if_final_pass_fails(self):
        jobs = [make_job(1), make_job(2)]
        recipient_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }

        class FinalPassFailingModels(FakeModels):
            def generate_content(self, model, contents, config):
                self.calls.append(
                    {
                        "model": model,
                        "contents": contents,
                        "config": config,
                    }
                )
                if len(self.calls) == 2:
                    raise RuntimeError("final pass failed")
                return FakeResponse(
                    {
                        "candidates": [
                            {
                                "job_url": "https://example.com/job-1",
                                "matched_profile": "SWE",
                                "fit_score": 81,
                                "why_apply": "Good junior engineering fit.",
                                "supporting_evidence": ["Software Engineer 1"],
                                "mismatch_evidence": [],
                            }
                        ],
                        "rejected_jobs": [
                            {
                                "job_url": "https://example.com/job-2",
                                "rejection_reason": "Too senior.",
                                "mismatch_evidence": ["Requires ownership."],
                            }
                        ],
                    }
                )

        class FinalPassFailingClient:
            def __init__(self):
                self.models = FinalPassFailingModels([])

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            result = rerank_jobs_with_gemini(
                jobs,
                recipient_profile,
                client=FinalPassFailingClient(),
                top_n=2,
                batch_size=10,
            )

        self.assertEqual("gemini_failed", result["review_mode"])
        self.assertEqual([], result["jobs_to_send"])
        self.assertEqual([], result["reviewed_jobs"])
        self.assertEqual(0, result["llm_shortlisted_jobs"])
        self.assertEqual(0, result["gemini_reviewed_jobs"])
        self.assertEqual("final_rerank", result["review_error_stage"])
        self.assertIn("final pass failed", result["review_error"])
        self.assertEqual(
            [
                "gemini_pass1_rejected_seen",
                "gemini_pass1_approved_final_failed_not_seen",
            ],
            [row["classification"] for row in result["audit_rows"]],
        )
        self.assertTrue(result["audit_rows"][0]["seen_recorded"])
        self.assertFalse(result["audit_rows"][1]["seen_recorded"])

    def test_rerank_records_batch_screening_failure_stage(self):
        jobs = [make_job(1)]
        recipient_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }

        class BatchFailingModels(FakeModels):
            def generate_content(self, model, contents, config):
                raise RuntimeError("503 UNAVAILABLE")

        class BatchFailingClient:
            def __init__(self):
                self.models = BatchFailingModels([])

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-key",
                "JOB_SCRAPER_LLM_RETRY_ATTEMPTS": "1",
            },
            clear=True,
        ):
            result = rerank_jobs_with_gemini(
                jobs,
                recipient_profile,
                client=BatchFailingClient(),
                top_n=1,
                batch_size=10,
            )

        self.assertEqual("gemini_failed", result["review_mode"])
        self.assertEqual("batch_screening", result["review_error_stage"])
        self.assertIn("503 UNAVAILABLE", result["review_error"])
        self.assertEqual(
            ["gemini_batch_failed_not_seen"],
            [row["classification"] for row in result["audit_rows"]],
        )

    def test_rerank_retries_retryable_batch_failure_and_recovers(self):
        jobs = [make_job(1)]
        recipient_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }

        class RetryableBatchModels(FakeModels):
            def generate_content(self, model, contents, config):
                self.calls.append(
                    {
                        "model": model,
                        "contents": contents,
                        "config": config,
                    }
                )
                if len(self.calls) == 1:
                    raise RuntimeError("503 UNAVAILABLE")
                if len(self.calls) == 2:
                    return FakeResponse(
                        {
                            "candidates": [
                                {
                                    "job_url": "https://example.com/job-1",
                                    "matched_profile": "SWE",
                                    "fit_score": 80,
                                    "why_apply": "Good junior engineering fit.",
                                    "supporting_evidence": ["Software Engineer 1"],
                                    "mismatch_evidence": [],
                                }
                            ]
                        }
                    )
                return FakeResponse(
                    {
                        "shortlisted_jobs": [
                            {
                                "job_url": "https://example.com/job-1",
                                "fit_score": 84,
                                "why_apply": "Strong junior engineering fit.",
                            }
                        ]
                    }
                )

        class RetryableBatchClient:
            def __init__(self):
                self.models = RetryableBatchModels([])

        retryable_batch_client = RetryableBatchClient()

        with (
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "JOB_SCRAPER_LLM_RETRY_ATTEMPTS": "3",
                    "JOB_SCRAPER_LLM_RETRY_BASE_SECONDS": "0",
                },
                clear=True,
            ),
            patch("matching.gemini_rerank.time.sleep") as sleep_mock,
        ):
            result = rerank_jobs_with_gemini(
                jobs,
                recipient_profile,
                client=retryable_batch_client,
                top_n=1,
                batch_size=10,
            )

        self.assertEqual("gemini", result["review_mode"])
        self.assertEqual(1, len(result["jobs_to_send"]))
        self.assertEqual(1, len(result["reviewed_jobs"]))
        self.assertEqual(1, result["llm_shortlisted_jobs"])
        self.assertEqual(1, result["gemini_reviewed_jobs"])
        self.assertEqual(3, len(retryable_batch_client.models.calls))
        self.assertEqual(0, sleep_mock.call_count)

    def test_rerank_retries_retryable_final_pass_failure_and_recovers(self):
        jobs = [make_job(1)]
        recipient_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }

        class RetryableFinalModels(FakeModels):
            def generate_content(self, model, contents, config):
                self.calls.append(
                    {
                        "model": model,
                        "contents": contents,
                        "config": config,
                    }
                )
                if len(self.calls) == 1:
                    return FakeResponse(
                        {
                            "candidates": [
                                {
                                    "job_url": "https://example.com/job-1",
                                    "matched_profile": "SWE",
                                    "fit_score": 82,
                                    "why_apply": "Good junior engineering fit.",
                                    "supporting_evidence": ["Software Engineer 1"],
                                    "mismatch_evidence": [],
                                }
                            ]
                        }
                    )
                if len(self.calls) == 2:
                    raise RuntimeError("503 UNAVAILABLE")
                return FakeResponse(
                    {
                        "shortlisted_jobs": [
                            {
                                "job_url": "https://example.com/job-1",
                                "fit_score": 86,
                                "why_apply": "Strong junior engineering fit.",
                            }
                        ]
                    }
                )

        class RetryableFinalClient:
            def __init__(self):
                self.models = RetryableFinalModels([])

        retryable_final_client = RetryableFinalClient()

        with (
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "JOB_SCRAPER_LLM_RETRY_ATTEMPTS": "3",
                    "JOB_SCRAPER_LLM_RETRY_BASE_SECONDS": "0",
                },
                clear=True,
            ),
            patch("matching.gemini_rerank.time.sleep") as sleep_mock,
        ):
            result = rerank_jobs_with_gemini(
                jobs,
                recipient_profile,
                client=retryable_final_client,
                top_n=1,
                batch_size=10,
            )

        self.assertEqual("gemini", result["review_mode"])
        self.assertEqual(1, len(result["jobs_to_send"]))
        self.assertEqual(1, len(result["reviewed_jobs"]))
        self.assertEqual(1, result["llm_shortlisted_jobs"])
        self.assertEqual(1, result["gemini_reviewed_jobs"])
        self.assertEqual(3, len(retryable_final_client.models.calls))
        self.assertEqual(0, sleep_mock.call_count)

    def test_rerank_returns_capped_semantic_jobs_when_disabled(self):
        jobs = [make_job(index) for index in range(1, 120)]
        recipient_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }

        with patch.dict(os.environ, {}, clear=True):
            result = rerank_jobs_with_gemini(jobs, recipient_profile)

        self.assertEqual("semantic", result["review_mode"])
        self.assertEqual(100, len(result["jobs_to_send"]))
        self.assertEqual(100, len(result["reviewed_jobs"]))
        self.assertEqual("https://example.com/job-1", result["jobs_to_send"][0]["url"])
        self.assertEqual("https://example.com/job-100", result["jobs_to_send"][-1]["url"])

    def test_rerank_uses_llm_top_n_when_gemini_is_disabled(self):
        jobs = [make_job(index) for index in range(1, 20)]
        recipient_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }

        with patch.dict(
            os.environ,
            {"JOB_SCRAPER_LLM_TOP_N": "7"},
            clear=True,
        ):
            result = rerank_jobs_with_gemini(jobs, recipient_profile)

        self.assertEqual("semantic", result["review_mode"])
        self.assertEqual(7, len(result["jobs_to_send"]))
        self.assertEqual(7, len(result["reviewed_jobs"]))
        self.assertEqual("https://example.com/job-7", result["jobs_to_send"][-1]["url"])

    def test_rerank_only_includes_eligibility_rule_when_hard_eligibility_matters(self):
        jobs = [make_job(1)]
        base_profile = {
            "semantic_profiles": ["swe"],
            "semantic_profile_texts": {},
            "cv_summary": "",
        }
        client_false = FakeClient(
            [
                {
                    "candidates": [
                        {
                            "job_url": "https://example.com/job-1",
                            "matched_profile": "SWE",
                            "fit_score": 80,
                            "why_apply": "Good junior engineering fit.",
                            "supporting_evidence": ["Software Engineer 1"],
                            "mismatch_evidence": [],
                        }
                    ]
                },
                {
                    "shortlisted_jobs": [
                        {
                            "job_url": "https://example.com/job-1",
                            "fit_score": 82,
                            "why_apply": "Strong junior engineering fit.",
                        }
                    ]
                },
            ]
        )
        client_true = FakeClient(
            [
                {
                    "candidates": [
                        {
                            "job_url": "https://example.com/job-1",
                            "matched_profile": "SWE",
                            "fit_score": 80,
                            "why_apply": "Good junior engineering fit.",
                            "supporting_evidence": ["Software Engineer 1"],
                            "mismatch_evidence": [],
                        }
                    ]
                },
                {
                    "shortlisted_jobs": [
                        {
                            "job_url": "https://example.com/job-1",
                            "fit_score": 82,
                            "why_apply": "Strong junior engineering fit.",
                        }
                    ]
                },
            ]
        )

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            rerank_jobs_with_gemini(
                jobs,
                {**base_profile, "care_about_hard_eligibility": False},
                client=client_false,
                top_n=1,
                batch_size=10,
            )
            rerank_jobs_with_gemini(
                jobs,
                {**base_profile, "care_about_hard_eligibility": True},
                client=client_true,
                top_n=1,
                batch_size=10,
            )

        false_first_prompt = client_false.models.calls[0]["contents"]
        false_second_prompt = client_false.models.calls[1]["contents"]
        true_first_prompt = client_true.models.calls[0]["contents"]
        true_second_prompt = client_true.models.calls[1]["contents"]

        self.assertNotIn('"eligibility_rule"', false_first_prompt)
        self.assertNotIn('"eligibility_rule"', false_second_prompt)
        self.assertIn('"eligibility_rule"', true_first_prompt)
        self.assertIn('"eligibility_rule"', true_second_prompt)
        self.assertIn("SC clearance", true_first_prompt)
        self.assertIn("SC clearance", true_second_prompt)
        self.assertIn("Use work_authorization_summary", true_first_prompt)
        self.assertIn("Use work_authorization_summary", true_second_prompt)
        self.assertIn("time-limited authorization", true_first_prompt)
        self.assertIn("time-limited authorization", true_second_prompt)
        self.assertIn("do not reject solely because sponsorship is unstated", true_first_prompt)
        self.assertIn("do not reject solely because sponsorship is unstated", true_second_prompt)


if __name__ == "__main__":
    unittest.main()
