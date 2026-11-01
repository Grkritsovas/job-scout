import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from matching.cv import chunk_cv_text
from matching.profile_library import build_profile_specs
from matching.ranking import ProfileMatcher


class FakeEmbeddingModel:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def encode(self, texts, normalize_embeddings=True):
        self.calls.append(texts)
        if isinstance(texts, str):
            return np.array(self.vectors[texts], dtype=float)
        return np.array([self.vectors[text] for text in texts], dtype=float)


def cosine_similarity(left, right):
    left = np.atleast_2d(left)
    right = np.atleast_2d(right)
    return (left / np.linalg.norm(left, axis=1, keepdims=True)) @ (
        right / np.linalg.norm(right, axis=1, keepdims=True)
    ).T


class CvMatchingTests(unittest.TestCase):
    def make_matcher(self, vectors):
        model = FakeEmbeddingModel(vectors)
        module = SimpleNamespace(
            SentenceTransformer=lambda name: model,
            util=SimpleNamespace(cos_sim=cosine_similarity),
        )
        with patch.dict(sys.modules, {"sentence_transformers": module}):
            return ProfileMatcher("fake-model")

    def test_chunks_cover_the_whole_cv_with_overlap_and_no_empty_tail(self):
        words = [f"word{i}" for i in range(201)]
        chunks = chunk_cv_text("\n".join(words))
        self.assertTrue(all(len(chunk.split()) <= 80 for chunk in chunks))
        self.assertEqual(words[:80], chunks[0].split())
        self.assertEqual(chunks[0].split()[-20:], chunks[1].split()[:20])
        self.assertEqual("word200", chunks[-1].split()[-1])
        self.assertEqual(set(words), set(" ".join(chunks).split()))
        self.assertEqual(1, len(chunk_cv_text(" ".join(words[:80]))))
        self.assertEqual([], chunk_cv_text(" \n "))

    def test_cv_reaches_each_profile_without_changing_role_text_or_labels(self):
        base = {"semantic_profiles": ["swe", "marketing_assistant"]}
        original = build_profile_specs(base)
        enriched = build_profile_specs({**base, "cv": "Python and marketing projects."})
        self.assertEqual(original, [{k: v for k, v in spec.items() if k != "cv"} for spec in enriched])
        self.assertTrue(all(spec["cv"] == "Python and marketing projects." for spec in enriched))
        self.assertEqual(original, build_profile_specs({**base, "cv": " \n "}))

    def test_relevant_cv_evidence_can_lift_a_borderline_job_above_threshold(self):
        job_vector = [0.4, 0, np.sqrt(0.84)]
        matcher = self.make_matcher({
            "software role": [1, 0, 0],
            "job": job_vector,
            "Python project": job_vector,
        })
        spec = {"id": "swe", "label": "SWE", "text": "software role"}
        baseline = matcher.score_description("job", [spec])
        enriched = matcher.score_description("job", [{**spec, "cv": "Python project"}])
        self.assertAlmostEqual(0.4, baseline["top_score"])
        self.assertAlmostEqual(0.52, enriched["top_score"])
        self.assertEqual("SWE", enriched["top_profile"])

    def test_lower_cv_similarity_does_not_reduce_the_original_role_score(self):
        matcher = self.make_matcher({
            "software role": [1, 0, 0],
            "job": [0.4, 0, np.sqrt(0.84)],
            "older experience": [0.5, np.sqrt(0.75), 0],
        })
        spec = {"id": "swe", "label": "SWE", "text": "software role", "cv": "older experience"}
        self.assertAlmostEqual(0.4, matcher.score_description("job", [spec])["top_score"])

    def test_cv_passages_are_selected_for_each_target_and_cached_between_jobs(self):
        cv = " ".join(["software"] * 80 + ["marketing"] * 60)
        software_chunk, marketing_chunk = chunk_cv_text(cv)
        job_vector = [0.4, 0, np.sqrt(0.84)]
        matcher = self.make_matcher({
            "software role": [1, 0, 0],
            "marketing role": [0, 1, 0],
            software_chunk: job_vector,
            marketing_chunk: [0, 1, 0],
            "job": job_vector,
        })
        specs = [
            {"id": "swe", "label": "SWE", "text": "software role", "cv": cv},
            {"id": "marketing", "label": "Marketing", "text": "marketing role", "cv": cv},
        ]
        result = matcher.score_description("job", specs)
        self.assertAlmostEqual(0.52, result["profile_scores"]["SWE"])
        self.assertAlmostEqual(0, result["profile_scores"]["Marketing"])
        calls_after_first_job = len(matcher.model.calls)
        self.assertEqual(result, matcher.score_description("job", specs))
        self.assertEqual(calls_after_first_job, len(matcher.model.calls))
        self.assertEqual(1, matcher.model.calls.count([software_chunk, marketing_chunk]))

    def test_updated_cv_invalidates_evidence_and_unrelated_evidence_is_ignored(self):
        job_vector = [0.4, 0, np.sqrt(0.84)]
        matcher = self.make_matcher({
            "software role": [1, 0, 0], "job": job_vector,
            "Python project": job_vector, "unrelated work": [0, 1, 0],
        })
        spec = {"id": "swe", "label": "SWE", "text": "software role"}
        original = matcher.score_description("job", [{**spec, "cv": "Python project"}])
        updated = matcher.score_description("job", [{**spec, "cv": "unrelated work"}])
        self.assertAlmostEqual(0.52, original["top_score"])
        self.assertAlmostEqual(0.4, updated["top_score"])
        self.assertEqual(2, len(matcher.cv_profile_embedding_cache))


if __name__ == "__main__":
    unittest.main()
