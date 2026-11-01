import os
import re
import threading
from collections import Counter

from matching.cv import chunk_cv_text
from matching.hard_filters import (
    DEFAULT_MAX_YEARS_EXPERIENCE,
    get_hard_filter_reason,
)
from matching.models import ALL_MINILM_L6_V2
from matching.profile_library import build_profile_specs
from shared.descriptions import build_matching_text


# Change this assignment to swap the default embedding model in code.
SELECTED_EMBEDDING_MODEL = ALL_MINILM_L6_V2
EMBEDDING_MODEL_NAME = os.getenv(
    "JOB_SCRAPER_EMBEDDING_MODEL", SELECTED_EMBEDDING_MODEL.model_name
)
DEFAULT_MIN_PROFILE_SCORE = float(os.getenv("JOB_SCRAPER_MIN_SCORE", "0.42"))
DEFAULT_SALARY_PENALTY_MAX = 0.35
DEFAULT_JUNIOR_BOOST_MULTIPLIER = 1.2
DEFAULT_JUNIOR_BOOST_TERMS = (
    "junior",
    "grad",
    "graduate",
    "entry level",
    "entry-level",
)
HARD_FILTER_AUDIT_LIMIT_PER_REASON = 30
CV_EVIDENCE_WEIGHT = 0.2
CV_RELEVANCE_THRESHOLD = 0.25
CV_PASSAGES_PER_PROFILE = 3

SALARY_RANGE_PATTERNS = [
    re.compile(
        r"(?:\u00a3|gbp\s*)\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k)?"
        r"\s*(?:-|to|\u2013|\u2014)\s*(?:\u00a3|gbp\s*)?\s*"
        r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k)?",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?:salary|compensation|pay)\D{0,20}(?:\u00a3|gbp\s*)\s*"
        r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k)?",
        flags=re.IGNORECASE,
    ),
]
SALARY_RATE_MARKERS = ("hour", "day", "daily", "week", "monthly")

_PROFILE_MATCHER = None
_PROFILE_MATCHER_LOCK = threading.Lock()


class ProfileMatcher:
    def __init__(self, model_name):
        try:
            from sentence_transformers import SentenceTransformer, util
        except ImportError as exc:
            raise RuntimeError(
                "Semantic job matching requires sentence-transformers. "
                "Install dependencies from requirements.txt."
            ) from exc

        self.model = SentenceTransformer(model_name)
        self.util = util
        self.description_embedding_cache = {}
        self.profile_embedding_cache = {}
        self.cv_profile_embedding_cache = {}
        self.cache_lock = threading.Lock()

    def _get_description_embedding(self, description):
        with self.cache_lock:
            cached_embedding = self.description_embedding_cache.get(description)
        if cached_embedding is not None:
            return cached_embedding

        computed_embedding = self.model.encode(
            description,
            normalize_embeddings=True,
        )
        with self.cache_lock:
            return self.description_embedding_cache.setdefault(
                description,
                computed_embedding,
            )

    def _get_profile_embeddings(self, profile_specs):
        cache_key = tuple((spec["id"], spec["text"]) for spec in profile_specs)
        with self.cache_lock:
            cached_embeddings = self.profile_embedding_cache.get(cache_key)
        if cached_embeddings is not None:
            return cached_embeddings

        computed_embeddings = self.model.encode(
            [spec["text"] for spec in profile_specs],
            normalize_embeddings=True,
        )
        with self.cache_lock:
            return self.profile_embedding_cache.setdefault(
                cache_key,
                computed_embeddings,
            )

    def _get_cv_profile_embeddings(self, profile_specs, profile_embeddings):
        cache_key = tuple(
            (spec["id"], spec["text"], spec.get("cv", ""))
            for spec in profile_specs
        )
        with self.cache_lock:
            cached_embeddings = self.cv_profile_embedding_cache.get(cache_key)
        if cached_embeddings is not None:
            return cached_embeddings

        # Select evidence once per profile/CV, rather than letting each job cherry
        # pick an incidental match from the candidate's entire work history.
        cv_embeddings = {}
        selected_embeddings = []
        for index, spec in enumerate(profile_specs):
            cv = spec.get("cv", "")
            if not cv:
                selected_embeddings.append(None)
                continue
            if cv not in cv_embeddings:
                cv_embeddings[cv] = self.model.encode(
                    chunk_cv_text(cv), normalize_embeddings=True
                )
            embeddings = cv_embeddings[cv]
            relevance = self.util.cos_sim(
                profile_embeddings[index], embeddings
            )[0].tolist()
            relevant_indices = [
                passage_index
                for passage_index in sorted(
                    range(len(relevance)), key=relevance.__getitem__, reverse=True
                )[:CV_PASSAGES_PER_PROFILE]
                if relevance[passage_index] >= CV_RELEVANCE_THRESHOLD
            ]
            selected_embeddings.append(
                embeddings[relevant_indices] if relevant_indices else None
            )

        with self.cache_lock:
            return self.cv_profile_embedding_cache.setdefault(
                cache_key, selected_embeddings
            )

    def score_description(self, description, profile_specs):
        description_embedding = self._get_description_embedding(description)
        profile_embeddings = self._get_profile_embeddings(profile_specs)
        similarities = self.util.cos_sim(
            description_embedding,
            profile_embeddings,
        )[0].tolist()
        if any(spec.get("cv") for spec in profile_specs):
            cv_profile_embeddings = self._get_cv_profile_embeddings(
                profile_specs, profile_embeddings
            )
            for index, embeddings in enumerate(cv_profile_embeddings):
                if embeddings is None:
                    continue
                evidence_scores = self.util.cos_sim(
                    description_embedding, embeddings
                )[0].tolist()
                evidence_score = sum(evidence_scores) / len(evidence_scores)
                role_score = similarities[index]
                # Keep the original role score as a floor. CV evidence may help
                # retrieval without narrowing career moves to past experience.
                similarities[index] = max(
                    role_score,
                    (1 - CV_EVIDENCE_WEIGHT) * role_score
                    + CV_EVIDENCE_WEIGHT * evidence_score,
                )

        profile_scores = {
            spec["label"]: score
            for spec, score in zip(profile_specs, similarities)
        }
        ranked_profiles = sorted(
            profile_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        top_profile, top_score = ranked_profiles[0]
        if len(ranked_profiles) > 1:
            second_profile, second_score = ranked_profiles[1]
        else:
            second_profile, second_score = top_profile, 0.0

        return {
            "profile_scores": profile_scores,
            "top_profile": top_profile,
            "top_score": top_score,
            "second_profile": second_profile,
            "second_score": second_score,
            "score_margin": top_score - second_score,
            "fit_summary": format_fit_summary(ranked_profiles),
        }


def get_profile_matcher():
    global _PROFILE_MATCHER

    if _PROFILE_MATCHER is None:
        with _PROFILE_MATCHER_LOCK:
            if _PROFILE_MATCHER is None:
                _PROFILE_MATCHER = ProfileMatcher(EMBEDDING_MODEL_NAME)

    return _PROFILE_MATCHER


def score_to_percent(score):
    return max(0, round(score * 100))


def format_fit_summary(ranked_profiles):
    return " | ".join(
        f"{label} {score_to_percent(score)}%"
        for label, score in ranked_profiles
    )


def get_junior_boost_multiplier(recipient_profile):
    raw_value = recipient_profile.get("junior_boost_multiplier")
    if raw_value is None:
        return DEFAULT_JUNIOR_BOOST_MULTIPLIER

    try:
        return max(1.0, float(raw_value))
    except (TypeError, ValueError):
        return DEFAULT_JUNIOR_BOOST_MULTIPLIER


def get_junior_boost_terms(recipient_profile):
    raw_value = recipient_profile.get("junior_boost_terms")
    if not raw_value:
        return list(DEFAULT_JUNIOR_BOOST_TERMS)

    terms = [str(term).strip().lower() for term in raw_value if str(term).strip()]
    return terms or list(DEFAULT_JUNIOR_BOOST_TERMS)


def get_junior_title_pattern(recipient_profile):
    term_patterns = []
    for term in get_junior_boost_terms(recipient_profile):
        escaped = re.escape(term)
        escaped = escaped.replace(r"\ ", r"[\s-]+")
        escaped = escaped.replace(r"\-", r"[\s-]+")
        term_patterns.append(escaped)

    return re.compile(
        rf"\b(?:{'|'.join(term_patterns)})\b",
        flags=re.IGNORECASE,
    )


def title_gets_junior_boost(title, recipient_profile):
    return bool(get_junior_title_pattern(recipient_profile).search(title or ""))


def apply_title_boost(score_data, job, recipient_profile):
    if not title_gets_junior_boost(job.get("title", ""), recipient_profile):
        score_data["title_boost_multiplier"] = 1.0
        return score_data

    multiplier = get_junior_boost_multiplier(recipient_profile)
    boosted_profile_scores = {
        label: min(1.0, score * multiplier)
        for label, score in score_data["profile_scores"].items()
    }
    ranked_profiles = sorted(
        boosted_profile_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    top_profile, top_score = ranked_profiles[0]
    if len(ranked_profiles) > 1:
        second_profile, second_score = ranked_profiles[1]
    else:
        second_profile, second_score = top_profile, 0.0

    return {
        **score_data,
        "profile_scores": boosted_profile_scores,
        "top_profile": top_profile,
        "top_score": top_score,
        "second_profile": second_profile,
        "second_score": second_score,
        "score_margin": top_score - second_score,
        "fit_summary": format_fit_summary(ranked_profiles),
        "title_boost_multiplier": multiplier,
    }


def _parse_salary_amount(amount_text, has_k_suffix):
    numeric_value = float(amount_text.replace(",", ""))
    if has_k_suffix:
        numeric_value *= 1000
    return numeric_value


def extract_salary_upper_bound_gbp(text):
    normalized_text = text or ""
    upper_bounds = []

    for pattern in SALARY_RANGE_PATTERNS:
        for match in pattern.finditer(normalized_text):
            trailing_context = normalized_text[match.end() : match.end() + 20].lower()
            if any(marker in trailing_context for marker in SALARY_RATE_MARKERS):
                continue

            groups = match.groups()
            if len(groups) >= 4 and groups[2]:
                upper_bounds.append(_parse_salary_amount(groups[2], groups[3]))
                continue

            upper_bounds.append(_parse_salary_amount(groups[0], groups[1]))

    if not upper_bounds:
        return None

    return max(upper_bounds)


def apply_salary_penalty(job, ranking_score, recipient_profile):
    preferred_salary_max = recipient_profile.get("preferred_salary_max_gbp")
    if preferred_salary_max is None:
        return ranking_score, None, 0.0

    salary_upper_bound = extract_salary_upper_bound_gbp(
        f"{job.get('title', '')}\n{job.get('description', '')}"
    )
    if salary_upper_bound is None:
        return ranking_score, None, 0.0

    salary_hard_cap = recipient_profile.get("salary_hard_cap_gbp")
    if salary_hard_cap is None:
        salary_hard_cap = preferred_salary_max + 5000

    penalty_max = float(
        recipient_profile.get("salary_penalty_max", DEFAULT_SALARY_PENALTY_MAX)
    )

    if salary_upper_bound <= preferred_salary_max:
        return ranking_score, salary_upper_bound, 0.0

    if salary_hard_cap <= preferred_salary_max:
        salary_hard_cap = preferred_salary_max + 1

    if salary_upper_bound >= salary_hard_cap:
        penalty = penalty_max
    else:
        penalty = penalty_max * (
            (salary_upper_bound - preferred_salary_max)
            / (salary_hard_cap - preferred_salary_max)
        )

    return ranking_score - penalty, salary_upper_bound, penalty


def _base_audit_row(job, review_family, classification, stage):
    return {
        "job_url": job.get("url", ""),
        "source_type": job.get("source", ""),
        "target_value": job.get("target_value", ""),
        "company_name": job.get("company", ""),
        "title": job.get("title", ""),
        "location": job.get("location", ""),
        "review_family": review_family,
        "classification": classification,
        "stage": stage,
    }


def _semantic_audit_row(
    job,
    classification,
    min_top_score,
    semantic_rank=None,
):
    return {
        **_base_audit_row(
            job,
            "semantic",
            classification,
            "semantic_ranking",
        ),
        "semantic_rank": semantic_rank,
        "raw_embedding_score": job.get("raw_embedding_score"),
        "semantic_score": job.get("ranking_score"),
        "semantic_threshold": min_top_score,
        "semantic_top_profile": job.get("top_profile"),
        "semantic_second_profile": job.get("second_profile"),
        "semantic_fit_summary": job.get("fit_summary"),
        "title_boost_multiplier": job.get("title_boost_multiplier"),
        "salary_upper_bound_gbp": job.get("salary_upper_bound_gbp"),
        "salary_penalty_applied": job.get("salary_penalty_applied"),
    }


def rank_jobs(jobs, recipient_profile, matcher=None, return_stats=False):
    matcher = matcher or get_profile_matcher()
    profile_specs = build_profile_specs(recipient_profile)
    min_top_score = float(
        recipient_profile.get("min_top_score", DEFAULT_MIN_PROFILE_SCORE)
    )
    ranked_jobs = []
    stats = {
        "input_jobs": len(jobs),
        "hard_filtered_jobs": 0,
        "below_threshold_jobs": 0,
        "ranked_jobs": 0,
        "hard_filter_reasons": {},
        "audit_rows": [],
    }
    hard_filter_reasons = Counter()
    hard_filter_audit_counts = Counter()

    for job in jobs:
        hard_filter_reason = get_hard_filter_reason(
            job,
            recipient_profile.get(
                "max_years_experience",
                DEFAULT_MAX_YEARS_EXPERIENCE,
            ),
            recipient_profile=recipient_profile,
        )
        if hard_filter_reason is not None:
            stats["hard_filtered_jobs"] += 1
            hard_filter_reasons[hard_filter_reason] += 1
            if (
                hard_filter_audit_counts[hard_filter_reason]
                < HARD_FILTER_AUDIT_LIMIT_PER_REASON
            ):
                stats["audit_rows"].append(
                    {
                        **_base_audit_row(
                            job,
                            "hard_filter",
                            "hard_filtered",
                            "hard_filter",
                        ),
                        "hard_filter_reason": hard_filter_reason,
                    }
                )
                hard_filter_audit_counts[hard_filter_reason] += 1
            continue

        match_text = build_matching_text(
            job.get("title", ""),
            job.get("description", ""),
        )
        score_data = matcher.score_description(
            match_text,
            profile_specs,
        )
        raw_embedding_score = score_data["top_score"]
        score_data = apply_title_boost(score_data, job, recipient_profile)
        ranking_score = score_data["top_score"]

        ranking_score, salary_upper_bound, salary_penalty_applied = apply_salary_penalty(
            job,
            ranking_score,
            recipient_profile,
        )
        if ranking_score < min_top_score:
            stats["below_threshold_jobs"] += 1
            stats["audit_rows"].append(
                _semantic_audit_row(
                    {
                        **job,
                        **score_data,
                        "raw_embedding_score": raw_embedding_score,
                        "ranking_score": ranking_score,
                        "semantic_threshold": min_top_score,
                        "salary_upper_bound_gbp": salary_upper_bound,
                        "salary_penalty_applied": salary_penalty_applied,
                    },
                    "semantic_below_threshold",
                    min_top_score,
                )
            )
            continue

        ranked_jobs.append(
            {
                **job,
                **score_data,
                "raw_embedding_score": raw_embedding_score,
                "ranking_score": ranking_score,
                "semantic_threshold": min_top_score,
                "salary_upper_bound_gbp": salary_upper_bound,
                "salary_penalty_applied": salary_penalty_applied,
            }
        )
        stats["ranked_jobs"] += 1

    ranked_jobs.sort(
        key=lambda job: (
            job["ranking_score"],
            job["top_score"],
            job["score_margin"],
            job["second_score"],
            job["title"].lower(),
        ),
        reverse=True,
    )
    for rank_position, job in enumerate(ranked_jobs, start=1):
        job["semantic_rank"] = rank_position
        stats["audit_rows"].append(
            _semantic_audit_row(
                job,
                "semantic_above_threshold",
                min_top_score,
                semantic_rank=rank_position,
            )
        )
    stats["hard_filter_reasons"] = dict(hard_filter_reasons)
    if return_stats:
        return ranked_jobs, stats
    return ranked_jobs
