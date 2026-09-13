import json
import os
import re
import threading
import time

from matching.profile_library import build_profile_specs
from shared.descriptions import focus_role_matching_text, normalize_text_whitespace


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_TOP_N = 100
DEFAULT_BATCH_SIZE = 10
DEFAULT_DESCRIPTION_CHARS = 8000
DEFAULT_EVIDENCE_ITEMS = 2
DEFAULT_GEMINI_RETRY_ATTEMPTS = 20
DEFAULT_GEMINI_RETRY_BASE_SECONDS = 5.0
GEMINI_RETRY_MAX_DELAY_SECONDS = 60.0
GEMINI_RETRY_TOTAL_WAIT_SECONDS = 600.0
GEMINI_CONCURRENCY_CAP = 4
RETRYABLE_GEMINI_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_GEMINI_ERROR_MARKERS = (
    "deadline exceeded",
    "internal error",
    "rate limit",
    "resource exhausted",
    "service unavailable",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "unavailable",
)
DOMAIN_MISMATCH_PRESETS = (
    (
        "marketing",
        re.compile(r"\b(?:market|marketer|marketing|seo|content)\b"),
        (
            "Marketing mismatch example: Product Marketing Manager for a junior "
            "marketing-assistant target. Campaign and content overlap is not enough "
            "when the role requires ownership of go-to-market strategy, product "
            "positioning, sales enablement, and several years of B2B experience."
        ),
    ),
    (
        "software",
        re.compile(
            r"\b(?:software|swe|sde|developer|backend|frontend|full stack|fullstack|web)\b"
        ),
        (
            "Software mismatch example: Platform or SRE Engineer for a general junior "
            "software-engineering target. Python overlap is not enough when Kubernetes, "
            "Terraform, observability, incident response, and production on-call "
            "ownership are the core job."
        ),
    ),
    (
        "data",
        re.compile(r"\b(?:data|analytics?|business intelligence|bi)\b"),
        (
            "Data mismatch example: Senior Data Engineer for an early-career data "
            "target. Shared Python and SQL are not enough when the role requires "
            "independent ownership of production pipelines, warehouse architecture, "
            "Spark or Kafka, and operational reliability."
        ),
    ),
    (
        "ai_ml",
        re.compile(r"\b(?:ai|ml|machine learning|artificial intelligence|llm)\b"),
        (
            "AI/ML mismatch example: ML Platform Engineer for a junior applied-ML "
            "target. Model and Python overlap is not enough when the role centers on "
            "production serving, MLOps infrastructure, cluster operations, and "
            "large-scale deployment ownership."
        ),
    ),
)
GENERIC_MISMATCH_EXAMPLE = (
    "Mismatch example: a role can share broad keywords or tools with a target profile "
    "and still be a poor match when its seniority, core specialty, or ownership scope "
    "requires experience the candidate context does not support."
)
_GEMINI_CALL_LIMITER = threading.BoundedSemaphore(GEMINI_CONCURRENCY_CAP)
PASS_ONE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "job_url": {"type": "string"},
                    "matched_profile": {"type": "string"},
                    "fit_score": {"type": "integer"},
                    "why_apply": {"type": "string"},
                    "supporting_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "mismatch_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "job_url",
                    "matched_profile",
                    "fit_score",
                    "why_apply",
                    "supporting_evidence",
                    "mismatch_evidence",
                ],
            },
        },
        "rejected_jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "job_url": {"type": "string"},
                    "rejection_reason": {"type": "string"},
                    "mismatch_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "job_url",
                    "rejection_reason",
                    "mismatch_evidence",
                ],
            },
        },
    },
    "required": ["candidates", "rejected_jobs"],
}
PASS_TWO_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "shortlisted_jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "job_url": {"type": "string"},
                    "fit_score": {"type": "integer"},
                    "why_apply": {"type": "string"},
                },
                "required": ["job_url", "fit_score", "why_apply"],
            },
        },
        "rejected_jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "job_url": {"type": "string"},
                    "rejection_reason": {"type": "string"},
                    "mismatch_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "job_url",
                    "rejection_reason",
                    "mismatch_evidence",
                ],
            },
        },
    },
    "required": ["shortlisted_jobs", "rejected_jobs"],
}


def gemini_rerank_enabled():
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def _safe_int_env(name, default):
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


def _safe_float_env(name, default):
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return float(raw_value)
    except ValueError:
        return default


def _positive_int(value, default):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def get_llm_top_n(job_count=None, override=None):
    configured = (
        _positive_int(override, DEFAULT_TOP_N)
        if override is not None
        else max(1, _safe_int_env("JOB_SCRAPER_LLM_TOP_N", DEFAULT_TOP_N))
    )
    if job_count is None:
        return configured

    return min(max(0, int(job_count)), configured)


def _build_result(
    jobs_to_send,
    reviewed_jobs,
    review_mode,
    llm_shortlisted_jobs=None,
    gemini_reviewed_jobs=None,
    review_error=None,
    review_error_stage=None,
    audit_rows=None,
):
    return {
        "jobs_to_send": jobs_to_send,
        "reviewed_jobs": reviewed_jobs,
        "review_mode": review_mode,
        "llm_shortlisted_jobs": llm_shortlisted_jobs,
        "gemini_reviewed_jobs": gemini_reviewed_jobs,
        "review_error": review_error,
        "review_error_stage": review_error_stage,
        "audit_rows": audit_rows or [],
    }


def _chunked(values, size):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _trim_description(description, limit):
    trimmed = normalize_text_whitespace(focus_role_matching_text(description))
    if len(trimmed) <= limit:
        return trimmed

    candidate = trimmed[:limit].rsplit(" ", 1)[0].strip()
    return candidate or trimmed[:limit].strip()


def _fit_hint(job):
    top_profile = job.get("top_profile")
    top_score = job.get("top_score")
    if not top_profile or top_score is None:
        return job.get("fit_summary", "")

    parts = [f"{top_profile} {round(float(top_score) * 100)}%"]
    second_profile = job.get("second_profile")
    second_score = job.get("second_score")
    if (
        second_profile
        and second_profile != top_profile
        and second_score is not None
        and second_score > 0
    ):
        parts.append(f"{second_profile} {round(float(second_score) * 100)}%")

    return " | ".join(parts)


def _build_job_payload(job, description_chars):
    payload = {
        "url": job.get("url", ""),
        "company": normalize_text_whitespace(job.get("company", "")),
        "title": normalize_text_whitespace(job.get("title", "")),
        "location": normalize_text_whitespace(job.get("location", "")),
        "semantic_fit_hint": _fit_hint(job),
        "description_excerpt": _trim_description(
            job.get("description", ""),
            description_chars,
        ),
    }
    if job.get("salary_upper_bound_gbp") is not None:
        payload["salary_upper_bound_gbp"] = job.get("salary_upper_bound_gbp")
    return payload


def _base_gemini_audit_row(
    job,
    classification,
    stage,
    seen_recorded=False,
    sent=False,
    reason="",
    supporting_evidence=None,
    mismatch_evidence=None,
    review_error=None,
    review_error_stage=None,
    metadata=None,
):
    return {
        "job_url": job.get("url", ""),
        "source_type": job.get("source", ""),
        "target_value": job.get("target_value", ""),
        "company_name": job.get("company", ""),
        "title": job.get("title", ""),
        "location": job.get("location", ""),
        "review_family": "gemini",
        "classification": classification,
        "stage": stage,
        "seen_recorded": seen_recorded,
        "sent": sent,
        "semantic_rank": job.get("semantic_rank"),
        "raw_embedding_score": job.get("raw_embedding_score"),
        "semantic_score": job.get("semantic_ranking_score", job.get("ranking_score")),
        "semantic_threshold": job.get("semantic_threshold"),
        "semantic_top_profile": job.get("top_profile"),
        "semantic_second_profile": job.get("second_profile"),
        "semantic_fit_summary": job.get("fit_summary"),
        "title_boost_multiplier": job.get("title_boost_multiplier"),
        "salary_upper_bound_gbp": job.get("salary_upper_bound_gbp"),
        "salary_penalty_applied": job.get("salary_penalty_applied"),
        "gemini_pass1_score": job.get(
            "gemini_pass1_fit_score",
            job.get("llm_fit_score"),
        ),
        "gemini_pass2_score": job.get("final_llm_fit_score"),
        "gemini_matched_profile": job.get("llm_matched_profile"),
        "gemini_reason": normalize_text_whitespace(reason),
        "supporting_evidence": supporting_evidence or [],
        "mismatch_evidence": mismatch_evidence or [],
        "review_error": review_error,
        "review_error_stage": review_error_stage,
        "metadata": metadata or {},
    }


def _gemini_failure_audit_rows(
    jobs,
    classification,
    stage,
    review_error,
    review_error_stage,
):
    return [
        _base_gemini_audit_row(
            job,
            classification,
            stage,
            review_error=review_error,
            review_error_stage=review_error_stage,
        )
        for job in jobs
    ]


def _build_candidate_context(recipient_profile):
    profiles = [
        {
            "label": spec["label"],
            "text": normalize_text_whitespace(spec["text"]),
        }
        for spec in build_profile_specs(recipient_profile)
    ]
    context = {
        "target_profiles": profiles,
        "cv_summary": normalize_text_whitespace(recipient_profile.get("cv_summary", "")),
    }
    education_status = normalize_text_whitespace(
        recipient_profile.get("education_status", "")
    )
    if education_status:
        context["education_status"] = education_status
    work_authorization_summary = normalize_text_whitespace(
        recipient_profile.get("work_authorization_summary", "")
    )
    if work_authorization_summary:
        context["work_authorization_summary"] = work_authorization_summary
    if recipient_profile.get("preferred_salary_max_gbp") is not None:
        context["preferred_salary_max_gbp"] = recipient_profile.get(
            "preferred_salary_max_gbp"
        )
    if recipient_profile.get("salary_hard_cap_gbp") is not None:
        context["salary_hard_cap_gbp"] = recipient_profile.get("salary_hard_cap_gbp")
    return context


def _add_salary_rule(instructions, recipient_profile):
    preferred_salary_max = recipient_profile.get("preferred_salary_max_gbp")
    if preferred_salary_max is None:
        return

    instructions["salary_rule"] = (
        "If salary context is provided, prefer roles whose compensation does not "
        "clearly exceed the candidate's target range. Treat roles far above the "
        "preferred salary as weaker matches, even when the skills overlap."
    )


def _add_communication_language_rule(instructions, recipient_profile):
    communication_language = normalize_text_whitespace(
        recipient_profile.get("communication_language", "")
    )
    if not communication_language:
        return

    instructions["communication_language_rule"] = (
        "The recipient prefers to read digest explanations in "
        f"{communication_language}. Write user-facing why_apply text in "
        f"{communication_language}. Keep supporting_evidence and "
        "mismatch_evidence as exact or near-exact snippets from the job text."
    )


def _add_extra_guidance(instructions, key, guidance_items):
    cleaned = [
        normalize_text_whitespace(item)
        for item in (guidance_items or [])
        if normalize_text_whitespace(item)
    ]
    if cleaned:
        instructions[key] = cleaned


def _targets_junior_roles(recipient_profile):
    max_years_experience = recipient_profile.get("max_years_experience")
    if max_years_experience is None:
        return False

    try:
        return float(max_years_experience) <= 2
    except (TypeError, ValueError):
        return False


def _add_junior_targeting_rule(instructions, recipient_profile):
    if not _targets_junior_roles(recipient_profile):
        return

    instructions["junior_targeting_rule"] = (
        "This profile targets junior or early-career roles. Treat wording like "
        "experienced, own end-to-end, operate at scale, deep professional experience, "
        "and required specialist tools missing from the candidate context "
        "as significant stretch signals. Do not reject automatically: keep the role "
        "only when the job explicitly says junior, associate, graduate, entry-level, "
        "open to learning, or accepts academic/project experience, or when the "
        "candidate context shows directly comparable evidence."
    )


def _add_domain_mismatch_guidance(instructions, recipient_profile):
    profile_terms = " ".join(
        f"{spec['id'].replace('_', ' ')} {spec['label']}"
        for spec in build_profile_specs(recipient_profile)
    ).lower()
    examples = [
        example
        for _domain, pattern, example in DOMAIN_MISMATCH_PRESETS
        if pattern.search(profile_terms)
    ]
    instructions["domain_mismatch_examples"] = examples or [
        GENERIC_MISMATCH_EXAMPLE
    ]


def _build_pass_one_prompt(recipient_profile, jobs, description_chars):
    instructions = {
        "primary_source_of_truth": (
            "The target profiles are the main decision rule. "
            "A job must clearly fit at least one target profile to be kept."
        ),
        "fit_dimension_rule": (
            "Separate domain relevance, skill overlap, and realistic employability. "
            "A role can have strong thematic relevance but still be a weak application "
            "target when hireability is blocked by seniority, ownership scope, "
            "unsupported core tools, or specialist domain requirements."
        ),
        "hard_requirement_rule": (
            "Penalize hard requirements more heavily than rewarding related domains. "
            "Required independent ownership, required tools absent from the "
            "candidate context, and specialist domain experience should "
            "usually make a role weak unless the job text explicitly accepts learning "
            "or project/academic evidence."
        ),
        "semantic_hint_rule": (
            "semantic_fit_hint is a rough embedding retrieval signal, not calibrated "
            "probability or evidence of realistic fit. Use it only as weak context; "
            "base decisions on the job text, candidate context, and target profiles."
        ),
        "cv_usage": (
            "The CV summary is supporting context only. "
            "Use it to judge transferable evidence, not to override the target profiles."
        ),
        "employability_rule": (
            "Focus on realistic employability today. "
            "Do not keep a role unless this candidate could plausibly be hired for it now."
        ),
        "selection_rule": (
            "Keep roles that are plausibly relevant with concrete evidence. "
            "Reject obvious mismatches and roles where the match relies mainly "
            "on stretched tool overlap, seniority, or unsupported domain depth."
        ),
        "scope_rule": (
            "Reject roles whose scope, title, or description indicate seniority, "
            "independent ownership, management, strategy, consulting, or specialist "
            "domain expertise beyond the candidate's evidence."
        ),
        "title_rule": (
            "Be especially cautious with titles like manager, lead, senior, staff, "
            "principal, director, strategist, consultant, partner, or specialist."
        ),
        "specialism_rule": (
            "Reject roles that depend on niche domain depth, specialist tooling, or "
            "operational ownership not supported by the target profiles and candidate "
            "context."
        ),
        "comparison_rule": (
            "Judge each role on its own merits. "
            "If none are clearly good, return an empty list."
        ),
        "evidence_rule": (
            "supporting_evidence and mismatch_evidence must contain short exact or "
            "near-exact snippets from the provided job text."
        ),
        "profile_rule": (
            "matched_profile must be exactly one of the provided target profile labels."
        ),
        "level_preference": (
            "Prefer junior, graduate, grad, and entry-level roles. "
            "Be cautious with manager, lead, senior, and staff roles."
        ),
        "junior_claim_rule": (
            "Do not describe a role as junior, graduate, or early-career unless the "
            "title, requirements, or job wording explicitly supports that label."
        ),
        "student_programme_rule": (
            "Use candidate education_status when screening internships, placements, "
            "and student programmes. Reject roles only when the job text explicitly "
            "requires current-student status, current enrollment, returning to study, "
            "or a future graduation date that the candidate does not meet. Do not "
            "reject an internship merely because student status is unspecified; judge "
            "the rest of the role fit normally."
        ),
        "output_rule": (
            "Return every provided job exactly once, either in candidates or "
            "rejected_jobs. For why_apply and rejection_reason, write at most "
            "2 short simple sentences."
        ),
    }
    if recipient_profile.get("care_about_hard_eligibility", False):
        instructions["eligibility_rule"] = (
            "Reject roles with hard eligibility requirements the candidate is unlikely to meet. "
            "This includes SC clearance, DV clearance, security vetting, nationality or citizenship restrictions, "
            "and explicit continuous UK residency requirements such as 3 years, 5 years, or similar. "
            "Check the entire provided job description for eligibility restrictions. "
            "Use work_authorization_summary when provided. Do not keep these roles unless the candidate context"
            " directly confirms eligibility. If work_authorization_summary "
            "mentions time-limited authorization or a visa expiry, treat explicit no-sponsorship "
            "language as a significant mismatch for roles that appear to require work beyond "
            "that authorization window, but do not reject solely because sponsorship is unstated."
        )
    _add_salary_rule(instructions, recipient_profile)
    _add_junior_targeting_rule(instructions, recipient_profile)
    _add_domain_mismatch_guidance(instructions, recipient_profile)
    _add_communication_language_rule(instructions, recipient_profile)
    _add_extra_guidance(
        instructions,
        "extra_screening_guidance",
        recipient_profile.get("extra_screening_guidance"),
    )

    candidate_payload = {
        "instructions": instructions,
        "candidate": _build_candidate_context(recipient_profile),
        "jobs": [_build_job_payload(job, description_chars) for job in jobs],
    }
    return (
        "Screen these jobs for one candidate. "
        "Return only credible candidates as JSON matching the schema.\n\n"
        f"{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}"
    )


def _build_pass_two_prompt(recipient_profile, candidates, description_chars):
    candidate_cards = [
        {
            "url": candidate["url"],
            "company": normalize_text_whitespace(candidate.get("company", "")),
            "title": normalize_text_whitespace(candidate.get("title", "")),
            "location": normalize_text_whitespace(candidate.get("location", "")),
            "description_excerpt": _trim_description(
                candidate.get("description", ""),
                description_chars,
            ),
            "salary_upper_bound_gbp": candidate.get("salary_upper_bound_gbp"),
            "matched_profile": candidate.get("llm_matched_profile", ""),
            "batch_fit_score": candidate.get("llm_fit_score", 0),
            "semantic_fit_hint": _fit_hint(candidate),
            "why_apply": normalize_text_whitespace(candidate.get("why_apply", "")),
            "supporting_evidence": list(candidate.get("supporting_evidence", [])),
            "mismatch_evidence": list(candidate.get("mismatch_evidence", [])),
        }
        for candidate in candidates
    ]
    instructions = {
        "task": (
            "Compare these already-screened candidates globally and keep only the "
            "strongest final matches."
        ),
        "fit_dimension_rule": (
            "Separate domain relevance, skill overlap, and realistic employability. "
            "Do not keep a role mainly because it matches an interesting theme if "
            "the candidate is unlikely to be interviewed or hired now."
        ),
        "hard_requirement_rule": (
            "Penalize hard requirements more heavily than rewarding related domains. "
            "Required independent ownership, required tools absent from the "
            "candidate context, and specialist domain experience should "
            "usually make a role weaker than a less glamorous but more hireable match."
        ),
        "semantic_hint_rule": (
            "semantic_fit_hint is a rough embedding retrieval signal, not calibrated "
            "probability or evidence of realistic fit. Use it only as weak context; "
            "base decisions on the job text, candidate context, and target profiles."
        ),
        "employability_rule": (
            "Focus on realistic employability today. "
            "Drop roles that only look relevant because of tool overlap."
        ),
        "selection_rule": (
            "Keep roles that remain plausibly relevant with concrete evidence "
            "after comparison. Drop obvious mismatches and roles where the match "
            "relies mainly on stretched tool overlap, seniority, or unsupported "
            "domain depth."
        ),
        "scope_rule": (
            "Reject roles whose final case depends on stretched reasoning, domain-specific "
            "ownership, or seniority the candidate does not clearly have."
        ),
        "specialism_rule": (
            "Drop roles that depend on niche domain depth, specialist tooling, or "
            "operational ownership not supported by the target profiles and candidate "
            "context."
        ),
        "comparison_rule": (
            "Use the candidate profiles as the main rule. "
            "Jobs with weak evidence, notable mismatches, or stretched reasoning should be dropped."
        ),
        "junior_claim_rule": (
            "Do not describe a role as junior, graduate, or early-career unless the "
            "title, requirements, or job wording explicitly supports that label."
        ),
        "student_programme_rule": (
            "Use candidate education_status when comparing internships, placements, "
            "and student programmes. Drop roles only when the job text explicitly "
            "requires current-student status, current enrollment, returning to study, "
            "or a future graduation date that the candidate does not meet. Do not "
            "drop an internship merely because student status is unspecified; compare "
            "the rest of the role fit normally."
        ),
        "output_rule": (
            "Return every screened candidate exactly once, either in "
            "shortlisted_jobs or rejected_jobs. For why_apply and "
            "rejection_reason, write at most 1 short simple sentence."
        ),
    }
    if recipient_profile.get("care_about_hard_eligibility", False):
        instructions["eligibility_rule"] = (
            "Reject roles with hard eligibility requirements the candidate is unlikely to meet. "
            "This includes SC clearance, DV clearance, security vetting, nationality or citizenship restrictions, "
            "and explicit continuous UK residency requirements such as 3 years, 5 years, or similar. "
            "Check the entire provided job description for eligibility restrictions. "
            "Use work_authorization_summary when provided. "
            "Do not keep these roles unless the candidate context directly confirms eligibility. "
            "If work_authorization_summary mentions time-limited authorization or a visa expiry, "
            "treat explicit no-sponsorship language as a significant mismatch for roles that appear "
            "to require work beyond that authorization window, but do not reject solely because "
            "sponsorship is unstated."
        )
    _add_salary_rule(instructions, recipient_profile)
    _add_junior_targeting_rule(instructions, recipient_profile)
    _add_domain_mismatch_guidance(instructions, recipient_profile)
    _add_communication_language_rule(instructions, recipient_profile)
    _add_extra_guidance(
        instructions,
        "extra_final_ranking_guidance",
        recipient_profile.get("extra_final_ranking_guidance"),
    )

    payload = {
        "instructions": instructions,
        "candidate": _build_candidate_context(recipient_profile),
        "screened_candidates": candidate_cards,
    }
    return (
        "Finalize the shortlist for one candidate. "
        "These jobs already passed a first screening round. "
        "Now compare them against each other and keep only the genuinely strong matches.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _build_client(api_key=None):
    effective_api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
    if not effective_api_key:
        return None

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "Gemini reranking requires google-genai. Install dependencies from requirements.txt."
        ) from exc

    return genai.Client(api_key=effective_api_key)


def _extract_error_status_codes(error):
    candidates = [
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(error, "status", None),
    ]
    response = getattr(error, "response", None)
    if response is not None:
        candidates.append(getattr(response, "status_code", None))

    codes = set()
    for candidate in candidates:
        if isinstance(candidate, int):
            codes.add(candidate)
            continue
        if isinstance(candidate, str) and candidate.isdigit():
            codes.add(int(candidate))

    for match in re.finditer(r"\b(429|500|502|503|504)\b", str(error)):
        codes.add(int(match.group(1)))

    return codes


def _is_retryable_gemini_error(error):
    if _extract_error_status_codes(error) & RETRYABLE_GEMINI_STATUS_CODES:
        return True

    normalized_message = normalize_text_whitespace(str(error)).lower()
    return any(marker in normalized_message for marker in RETRYABLE_GEMINI_ERROR_MARKERS)


def _generate_json_response(client, model, prompt, schema, retry_deadline=None):
    retry_attempts = max(
        1,
        _safe_int_env(
            "JOB_SCRAPER_LLM_RETRY_ATTEMPTS",
            DEFAULT_GEMINI_RETRY_ATTEMPTS,
        ),
    )
    retry_base_seconds = max(
        0.0,
        _safe_float_env(
            "JOB_SCRAPER_LLM_RETRY_BASE_SECONDS",
            DEFAULT_GEMINI_RETRY_BASE_SECONDS,
        ),
    )

    for attempt_index in range(retry_attempts):
        try:
            with _GEMINI_CALL_LIMITER:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema": schema,
                    },
                )
            return json.loads(getattr(response, "text", "") or "{}")
        except Exception as exc:
            is_last_attempt = attempt_index == retry_attempts - 1
            if is_last_attempt or not _is_retryable_gemini_error(exc):
                raise

            retry_number = attempt_index + 1
            retry_delay = min(
                retry_base_seconds * (2**attempt_index),
                GEMINI_RETRY_MAX_DELAY_SECONDS,
            )
            remaining_retry_budget = None
            if retry_deadline is not None:
                remaining_retry_budget = retry_deadline - time.monotonic()
                if remaining_retry_budget <= 0:
                    raise
                retry_delay = min(retry_delay, remaining_retry_budget)

            remaining_budget_suffix = ""
            if remaining_retry_budget is not None:
                remaining_budget_suffix = (
                    f" Remaining retry budget {remaining_retry_budget:.1f}s."
                )
            print(
                "Warning: Gemini API call failed with a retryable error. "
                f"Retrying {retry_number}/{retry_attempts - 1} in {retry_delay:.1f}s. "
                f"{exc}.{remaining_budget_suffix}"
            )
            if retry_delay > 0:
                time.sleep(retry_delay)

    raise RuntimeError("Gemini API retry loop exited unexpectedly.")


def _normalize_string_list(values):
    if not isinstance(values, list):
        return []

    normalized = []
    for value in values[:DEFAULT_EVIDENCE_ITEMS]:
        cleaned = normalize_text_whitespace(value)
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _run_batch_screening(
    candidate_jobs,
    recipient_profile,
    client,
    model,
    batch_size,
    description_chars,
    retry_deadline,
):
    original_indexes = {
        job["url"]: index
        for index, job in enumerate(candidate_jobs)
        if job.get("url")
    }
    screened_candidates = []
    pass_one_rejections = {}
    seen_urls = set()

    for batch in _chunked(candidate_jobs, batch_size):
        batch_by_url = {
            job["url"]: job
            for job in batch
            if job.get("url")
        }
        handled_batch_urls = set()
        prompt = _build_pass_one_prompt(
            recipient_profile,
            batch,
            description_chars,
        )
        payload = _generate_json_response(
            client,
            model,
            prompt,
            PASS_ONE_JSON_SCHEMA,
            retry_deadline=retry_deadline,
        )
        valid_profiles = {
            spec["label"]
            for spec in build_profile_specs(recipient_profile)
        }
        for item in payload.get("candidates", []):
            job_url = normalize_text_whitespace(item.get("job_url", ""))
            if not job_url or job_url in seen_urls or job_url not in batch_by_url:
                continue

            matched_profile = normalize_text_whitespace(item.get("matched_profile", ""))
            if matched_profile not in valid_profiles:
                continue
            handled_batch_urls.add(job_url)

            try:
                fit_score = int(item.get("fit_score", 0))
            except (TypeError, ValueError):
                fit_score = 0
            fit_score = max(0, min(100, fit_score))
            why_apply = normalize_text_whitespace(item.get("why_apply", ""))
            supporting_evidence = _normalize_string_list(item.get("supporting_evidence"))
            mismatch_evidence = _normalize_string_list(item.get("mismatch_evidence"))

            original_job = batch_by_url[job_url]
            screened_candidates.append(
                {
                    **original_job,
                    "semantic_ranking_score": original_job.get("ranking_score"),
                    "llm_matched_profile": matched_profile,
                    "ranking_score": fit_score / 100.0,
                    "llm_fit_score": fit_score,
                    "gemini_pass1_fit_score": fit_score,
                    "why_apply": why_apply,
                    "supporting_evidence": supporting_evidence,
                    "mismatch_evidence": mismatch_evidence,
                    "_original_index": original_indexes.get(job_url, 10**9),
                }
            )
            seen_urls.add(job_url)

        for item in payload.get("rejected_jobs", []):
            job_url = normalize_text_whitespace(item.get("job_url", ""))
            if not job_url or job_url in handled_batch_urls or job_url not in batch_by_url:
                continue
            handled_batch_urls.add(job_url)
            pass_one_rejections[job_url] = {
                "job": batch_by_url[job_url],
                "reason": normalize_text_whitespace(
                    item.get("rejection_reason", "")
                ),
                "mismatch_evidence": _normalize_string_list(
                    item.get("mismatch_evidence")
                ),
            }

        for job_url, job in batch_by_url.items():
            if job_url in handled_batch_urls:
                continue
            pass_one_rejections[job_url] = {
                "job": job,
                "reason": "Gemini did not return this job as a candidate.",
                "mismatch_evidence": [],
            }

    screened_candidates.sort(
        key=lambda job: (
            -job.get("llm_fit_score", 0),
            job.get("_original_index", 10**9),
        )
    )
    return screened_candidates, pass_one_rejections


def _run_final_rerank(
    candidates,
    recipient_profile,
    client,
    model,
    retry_deadline,
    description_chars,
):
    if not candidates:
        return [], {}

    candidates_by_url = {
        candidate["url"]: candidate
        for candidate in candidates
        if candidate.get("url")
    }
    prompt = _build_pass_two_prompt(
        recipient_profile,
        candidates,
        description_chars,
    )
    payload = _generate_json_response(
        client,
        model,
        prompt,
        PASS_TWO_JSON_SCHEMA,
        retry_deadline=retry_deadline,
    )
    final_shortlist = []
    seen_urls = set()
    pass_two_rejections = {}

    for item in payload.get("shortlisted_jobs", []):
        job_url = normalize_text_whitespace(item.get("job_url", ""))
        if not job_url or job_url in seen_urls or job_url not in candidates_by_url:
            continue

        try:
            fit_score = int(item.get("fit_score", 0))
        except (TypeError, ValueError):
            fit_score = 0
        fit_score = max(0, min(100, fit_score))
        why_apply = normalize_text_whitespace(item.get("why_apply", ""))

        original_candidate = candidates_by_url[job_url]
        final_shortlist.append(
            {
                **original_candidate,
                "ranking_score": fit_score / 100.0,
                "llm_fit_score": fit_score,
                "final_llm_fit_score": fit_score,
                "why_apply": why_apply or original_candidate.get("why_apply", ""),
            }
        )
        seen_urls.add(job_url)

    for item in payload.get("rejected_jobs", []):
        job_url = normalize_text_whitespace(item.get("job_url", ""))
        if not job_url or job_url in seen_urls or job_url not in candidates_by_url:
            continue

        pass_two_rejections[job_url] = {
            "job": candidates_by_url[job_url],
            "reason": normalize_text_whitespace(
                item.get("rejection_reason", "")
            ),
            "mismatch_evidence": _normalize_string_list(
                item.get("mismatch_evidence")
            ),
        }
        seen_urls.add(job_url)

    for job_url, candidate in candidates_by_url.items():
        if job_url in seen_urls:
            continue
        pass_two_rejections[job_url] = {
            "job": candidate,
            "reason": "Gemini did not return this screened candidate in the final shortlist.",
            "mismatch_evidence": [],
        }

    final_shortlist.sort(
        key=lambda job: (
            -job.get("llm_fit_score", 0),
            job.get("_original_index", 10**9),
        )
    )
    return final_shortlist, pass_two_rejections


def _strip_internal_fields(jobs):
    return [
        {
            key: value
            for key, value in job.items()
            if not key.startswith("_")
        }
        for job in jobs
    ]


def _pass_one_rejection_audit_rows(
    pass_one_rejections,
    classification,
    seen_recorded,
    review_error=None,
    review_error_stage=None,
):
    rows = []
    for rejection in pass_one_rejections.values():
        rows.append(
            _base_gemini_audit_row(
                rejection["job"],
                classification,
                "gemini_pass1",
                seen_recorded=seen_recorded,
                reason=rejection.get("reason", ""),
                mismatch_evidence=rejection.get("mismatch_evidence") or [],
                review_error=review_error,
                review_error_stage=review_error_stage,
            )
        )
    return rows


def _successful_gemini_audit_rows(
    pass_one_rejections,
    screened_candidates,
    final_shortlist,
    pass_two_rejections,
):
    audit_rows = _pass_one_rejection_audit_rows(
        pass_one_rejections,
        "gemini_pass1_rejected_seen",
        seen_recorded=True,
    )
    final_by_url = {
        job["url"]: job
        for job in final_shortlist
        if job.get("url")
    }

    for candidate in screened_candidates:
        job_url = candidate.get("url", "")
        final_job = final_by_url.get(job_url)
        if final_job is not None:
            audit_rows.append(
                _base_gemini_audit_row(
                    final_job,
                    "gemini_pass2_approved_sent_seen",
                    "gemini_pass2",
                    seen_recorded=True,
                    sent=True,
                    reason=final_job.get("why_apply", ""),
                    supporting_evidence=final_job.get("supporting_evidence") or [],
                    mismatch_evidence=final_job.get("mismatch_evidence") or [],
                    metadata={"pass1_reason": candidate.get("why_apply", "")},
                )
            )
            continue

        rejection = pass_two_rejections.get(job_url, {})
        audit_rows.append(
            _base_gemini_audit_row(
                candidate,
                "gemini_pass1_approved_pass2_rejected_seen",
                "gemini_pass2",
                seen_recorded=True,
                reason=rejection.get("reason", ""),
                supporting_evidence=candidate.get("supporting_evidence") or [],
                mismatch_evidence=(
                    rejection.get("mismatch_evidence")
                    or candidate.get("mismatch_evidence")
                    or []
                ),
                metadata={"pass1_reason": candidate.get("why_apply", "")},
            )
        )

    return audit_rows


def _final_failure_audit_rows(
    pass_one_rejections,
    screened_candidates,
    review_error,
):
    audit_rows = _pass_one_rejection_audit_rows(
        pass_one_rejections,
        "gemini_pass1_rejected_seen",
        seen_recorded=True,
        review_error=review_error,
        review_error_stage="final_rerank",
    )
    for candidate in screened_candidates:
        audit_rows.append(
            _base_gemini_audit_row(
                candidate,
                "gemini_pass1_approved_final_failed_not_seen",
                "gemini_pass2",
                reason=candidate.get("why_apply", ""),
                supporting_evidence=candidate.get("supporting_evidence") or [],
                mismatch_evidence=candidate.get("mismatch_evidence") or [],
                review_error=review_error,
                review_error_stage="final_rerank",
            )
        )
    return audit_rows


def rerank_jobs_with_gemini(
    jobs,
    recipient_profile,
    client=None,
    model=None,
    top_n=None,
    batch_size=None,
    description_chars=None,
):
    if not jobs:
        return _build_result(
            [],
            [],
            "empty",
            llm_shortlisted_jobs=0,
            gemini_reviewed_jobs=0,
        )

    effective_top_n = get_llm_top_n(len(jobs), override=top_n)
    candidate_jobs = jobs[:effective_top_n]

    if client is None and not gemini_rerank_enabled():
        return _build_result(
            candidate_jobs,
            candidate_jobs,
            "semantic",
            llm_shortlisted_jobs=None,
            gemini_reviewed_jobs=None,
        )

    effective_batch_size = max(
        1,
        batch_size or _safe_int_env("JOB_SCRAPER_LLM_BATCH_SIZE", DEFAULT_BATCH_SIZE),
    )
    effective_description_chars = max(
        200,
        description_chars
        or _safe_int_env(
            "JOB_SCRAPER_LLM_DESCRIPTION_CHARS",
            DEFAULT_DESCRIPTION_CHARS,
        ),
    )
    effective_model = (
        model
        or os.getenv("JOB_SCRAPER_LLM_MODEL", "").strip()
        or DEFAULT_GEMINI_MODEL
    )
    retry_deadline = time.monotonic() + GEMINI_RETRY_TOTAL_WAIT_SECONDS

    try:
        client = client or _build_client()
    except RuntimeError as exc:
        error_message = str(exc)
        print(f"Warning: Gemini reranking unavailable, not sending digest. {error_message}")
        return _build_result(
            [],
            [],
            "gemini_failed",
            llm_shortlisted_jobs=0,
            gemini_reviewed_jobs=0,
            review_error=error_message,
            review_error_stage="client_setup",
            audit_rows=_gemini_failure_audit_rows(
                candidate_jobs,
                "gemini_client_setup_failed_not_seen",
                "client_setup",
                error_message,
                "client_setup",
            ),
        )

    if client is None:
        error_message = "Gemini API key is missing."
        return _build_result(
            [],
            [],
            "gemini_failed",
            llm_shortlisted_jobs=0,
            gemini_reviewed_jobs=0,
            review_error=error_message,
            review_error_stage="client_setup",
            audit_rows=_gemini_failure_audit_rows(
                candidate_jobs,
                "gemini_client_setup_failed_not_seen",
                "client_setup",
                error_message,
                "client_setup",
            ),
        )

    try:
        screened_candidates, pass_one_rejections = _run_batch_screening(
            candidate_jobs,
            recipient_profile,
            client,
            effective_model,
            effective_batch_size,
            effective_description_chars,
            retry_deadline,
        )
    except Exception as exc:
        error_message = str(exc)
        print(
            "Warning: Gemini batch screening failed, not sending digest. "
            f"{error_message}"
        )
        return _build_result(
            [],
            [],
            "gemini_failed",
            llm_shortlisted_jobs=0,
            gemini_reviewed_jobs=0,
            review_error=error_message,
            review_error_stage="batch_screening",
            audit_rows=_gemini_failure_audit_rows(
                candidate_jobs,
                "gemini_batch_failed_not_seen",
                "gemini_pass1",
                error_message,
                "batch_screening",
            ),
        )

    if not screened_candidates:
        audit_rows = _pass_one_rejection_audit_rows(
            pass_one_rejections,
            "gemini_pass1_rejected_seen",
            seen_recorded=True,
        )
        return _build_result(
            [],
            candidate_jobs,
            "gemini",
            llm_shortlisted_jobs=0,
            gemini_reviewed_jobs=len(candidate_jobs),
            audit_rows=audit_rows,
        )

    try:
        final_shortlist, pass_two_rejections = _run_final_rerank(
            screened_candidates,
            recipient_profile,
            client,
            effective_model,
            retry_deadline,
            effective_description_chars,
        )
    except Exception as exc:
        error_message = str(exc)
        print(
            "Warning: Gemini final reranking failed, not sending digest. "
            f"{error_message}"
        )
        return _build_result(
            [],
            [],
            "gemini_failed",
            llm_shortlisted_jobs=0,
            gemini_reviewed_jobs=0,
            review_error=error_message,
            review_error_stage="final_rerank",
            audit_rows=_final_failure_audit_rows(
                pass_one_rejections,
                screened_candidates,
                error_message,
            ),
        )

    audit_rows = _successful_gemini_audit_rows(
        pass_one_rejections,
        screened_candidates,
        final_shortlist,
        pass_two_rejections,
    )
    return _build_result(
        _strip_internal_fields(final_shortlist),
        candidate_jobs,
        "gemini",
        llm_shortlisted_jobs=len(final_shortlist),
        gemini_reviewed_jobs=len(candidate_jobs),
        audit_rows=audit_rows,
    )
