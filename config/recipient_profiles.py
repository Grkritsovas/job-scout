import os
import re

from matching.hard_filters import DEFAULT_MAX_YEARS_EXPERIENCE
from matching.profile_library import (
    DEFAULT_SEMANTIC_PROFILES,
    display_label,
    normalize_profile_id,
)
from matching.ranking import (
    DEFAULT_JUNIOR_BOOST_MULTIPLIER,
    DEFAULT_JUNIOR_BOOST_TERMS,
    DEFAULT_MIN_PROFILE_SCORE,
    DEFAULT_SALARY_PENALTY_MAX,
)
from shared.locations import DEFAULT_LOCATION_PRESET, normalize_location_preset


def _slugify(value):
    normalized = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return normalized or "recipient"


def _normalize_text(value):
    return str(value or "").strip()


def _normalize_text_list(values):
    if not values:
        return []

    if isinstance(values, str):
        values = [values]

    normalized = []
    for value in values:
        text = _normalize_text(value)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _to_float(value, default_value):
    if value is None or value == "":
        return float(default_value)
    return float(value)


def _to_optional_float(value):
    if value is None or value == "":
        return None
    return float(value)


def _to_optional_int(value):
    if value is None or value == "":
        return None
    return int(value)


def _reject_unknown_keys(mapping, allowed_keys, context):
    if not isinstance(mapping, dict):
        return

    unknown_keys = sorted(set(mapping) - set(allowed_keys))
    if not unknown_keys:
        return

    field_path = f"{context}.{unknown_keys[0]}"
    hint = ""
    if unknown_keys[0] == "education_status" and context != "candidate":
        hint = " Use candidate.education_status for graduation/student context."
    raise RuntimeError(f"Unknown recipient profile field '{field_path}'.{hint}")


def _canonical_target_role(entry):
    if isinstance(entry, str):
        profile_id = normalize_profile_id(entry)
        return {
            "id": profile_id,
            "name": display_label(profile_id),
        }

    if not isinstance(entry, dict):
        raise RuntimeError(
            "Each candidate.target_roles entry must be a string or object."
        )

    _reject_unknown_keys(
        entry,
        {"id", "profile_id", "name", "match_text", "text", "profile_text"},
        "candidate.target_roles[]",
    )

    raw_id = entry.get("id") or entry.get("profile_id") or entry.get("name")
    if not _normalize_text(raw_id):
        raise RuntimeError(
            "Each candidate.target_roles object must include id, profile_id, or name."
        )

    profile_id = normalize_profile_id(raw_id)
    role = {
        "id": profile_id,
        "name": _normalize_text(entry.get("name")) or display_label(profile_id),
    }
    match_text = _normalize_text(
        entry.get("match_text") or entry.get("text") or entry.get("profile_text")
    )
    if match_text:
        role["match_text"] = match_text
    return role


def _canonical_target_roles(candidate_config):
    raw_roles = candidate_config.get("target_roles") or DEFAULT_SEMANTIC_PROFILES
    roles = []
    seen_ids = set()

    for raw_role in raw_roles:
        role = _canonical_target_role(raw_role)
        if role["id"] in seen_ids:
            continue
        seen_ids.add(role["id"])
        roles.append(role)

    return roles


def normalize_grouped_profile(profile, index=0, sender_email=""):
    if not isinstance(profile, dict):
        raise RuntimeError("Each recipient profile must be a JSON object.")

    _reject_unknown_keys(
        profile,
        {
            "id",
            "enabled",
            "delivery",
            "email",
            "candidate",
            "job_preferences",
            "eligibility",
            "matching",
            "llm_review",
        },
        "profile",
    )

    delivery_config = (
        profile.get("delivery") if isinstance(profile.get("delivery"), dict) else {}
    )
    recipient_id = _slugify(
        profile.get("id")
        or delivery_config.get("email")
        or profile.get("email")
        or f"recipient_{index + 1}"
    )
    candidate_config = profile.get("candidate") or {}
    preferences_config = profile.get("job_preferences") or {}
    seniority_config = preferences_config.get("target_seniority") or {}
    salary_config = preferences_config.get("salary") or {}
    eligibility_config = profile.get("eligibility") or {}
    matching_config = profile.get("matching") or {}
    llm_review_config = profile.get("llm_review") or {}

    _reject_unknown_keys(delivery_config, {"email", "language"}, "delivery")
    _reject_unknown_keys(
        candidate_config,
        {"summary", "education_status", "target_roles"},
        "candidate",
    )
    _reject_unknown_keys(
        preferences_config,
        {"location", "target_seniority", "salary"},
        "job_preferences",
    )
    _reject_unknown_keys(
        seniority_config,
        {"max_explicit_years", "boost_multiplier", "boost_title_terms"},
        "job_preferences.target_seniority",
    )
    _reject_unknown_keys(
        salary_config,
        {"preferred_max_gbp", "hard_cap_gbp", "penalty_strength"},
        "job_preferences.salary",
    )
    _reject_unknown_keys(
        eligibility_config,
        {
            "needs_sponsorship",
            "work_authorization_summary",
            "check_hard_eligibility",
            "use_sponsor_lookup",
        },
        "eligibility",
    )
    _reject_unknown_keys(matching_config, {"semantic_threshold"}, "matching")
    _reject_unknown_keys(
        llm_review_config,
        {"extra_screening_guidance", "extra_final_ranking_guidance"},
        "llm_review",
    )

    grouped_profile = {
        "id": recipient_id,
        "enabled": bool(profile.get("enabled", True)),
        "delivery": {
            "email": _normalize_text(
                delivery_config.get("email") or profile.get("email")
            )
            or _normalize_text(sender_email),
            "language": _normalize_text(delivery_config.get("language")),
        },
        "candidate": {
            "summary": _normalize_text(candidate_config.get("summary")),
            "education_status": _normalize_text(
                candidate_config.get("education_status")
            ),
            "target_roles": _canonical_target_roles(candidate_config),
        },
        "job_preferences": {
            "location": normalize_location_preset(
                preferences_config.get("location") or DEFAULT_LOCATION_PRESET
            ),
            "target_seniority": {
                "max_explicit_years": _to_optional_int(
                    seniority_config.get("max_explicit_years")
                ),
                "boost_multiplier": _to_float(
                    seniority_config.get("boost_multiplier"),
                    DEFAULT_JUNIOR_BOOST_MULTIPLIER,
                ),
                "boost_title_terms": _normalize_text_list(
                    seniority_config.get("boost_title_terms")
                    or list(DEFAULT_JUNIOR_BOOST_TERMS)
                ),
            },
            "salary": {
                "preferred_max_gbp": _to_optional_float(
                    salary_config.get("preferred_max_gbp")
                ),
                "hard_cap_gbp": _to_optional_float(salary_config.get("hard_cap_gbp")),
                "penalty_strength": _to_float(
                    salary_config.get("penalty_strength"),
                    DEFAULT_SALARY_PENALTY_MAX,
                ),
            },
        },
        "eligibility": {
            "needs_sponsorship": bool(
                eligibility_config.get("needs_sponsorship", False)
            ),
            "work_authorization_summary": _normalize_text(
                eligibility_config.get("work_authorization_summary")
            ),
            "check_hard_eligibility": bool(
                eligibility_config.get("check_hard_eligibility", False)
            ),
            "use_sponsor_lookup": bool(
                eligibility_config.get("use_sponsor_lookup", False)
            ),
        },
        "matching": {
            "semantic_threshold": _to_float(
                matching_config.get("semantic_threshold"),
                DEFAULT_MIN_PROFILE_SCORE,
            ),
        },
        "llm_review": {
            "extra_screening_guidance": _normalize_text_list(
                llm_review_config.get("extra_screening_guidance")
            ),
            "extra_final_ranking_guidance": _normalize_text_list(
                llm_review_config.get("extra_final_ranking_guidance")
            ),
        },
    }

    if (
        grouped_profile["job_preferences"]["target_seniority"]["max_explicit_years"]
        is None
    ):
        grouped_profile["job_preferences"]["target_seniority"][
            "max_explicit_years"
        ] = DEFAULT_MAX_YEARS_EXPERIENCE

    if not grouped_profile["delivery"]["email"]:
        raise RuntimeError(f"Recipient profile '{recipient_id}' is missing delivery.email.")

    return grouped_profile


def prepare_recipient_profile_db_rows(grouped_profiles, sender_email=None):
    if not isinstance(grouped_profiles, list):
        raise RuntimeError("Recipient profiles config must be a JSON array.")

    grouped = [
        normalize_grouped_profile(profile, index, sender_email or "")
        for index, profile in enumerate(grouped_profiles)
    ]
    recipient_ids = [profile["id"] for profile in grouped]
    if len(recipient_ids) != len(set(recipient_ids)):
        raise RuntimeError("Recipient profile ids must be unique.")

    return [
        {
            "recipient_id": profile["id"],
            "email": profile["delivery"]["email"],
            "enabled": bool(profile.get("enabled", True)),
            "config": profile,
        }
        for profile in grouped
    ]


def _to_runtime_profile(grouped_profile):
    target_roles = grouped_profile["candidate"]["target_roles"]
    semantic_profiles = [role["id"] for role in target_roles]
    semantic_profile_texts = {
        role["id"]: role["match_text"]
        for role in target_roles
        if _normalize_text(role.get("match_text"))
    }
    seniority_config = grouped_profile["job_preferences"]["target_seniority"]
    salary_config = grouped_profile["job_preferences"]["salary"]
    eligibility_config = grouped_profile["eligibility"]
    matching_config = grouped_profile["matching"]
    llm_review_config = grouped_profile["llm_review"]

    return {
        "id": grouped_profile["id"],
        "enabled": bool(grouped_profile.get("enabled", True)),
        "email": grouped_profile["delivery"]["email"],
        "communication_language": _normalize_text(
            grouped_profile["delivery"].get("language")
        ),
        "location_preset": normalize_location_preset(
            grouped_profile["job_preferences"].get("location")
        ),
        "semantic_profiles": semantic_profiles,
        "semantic_profile_texts": semantic_profile_texts,
        "cv_summary": _normalize_text(grouped_profile["candidate"].get("summary")),
        "education_status": _normalize_text(
            grouped_profile["candidate"].get("education_status")
        ),
        "min_top_score": float(matching_config["semantic_threshold"]),
        "max_years_experience": _to_optional_int(
            seniority_config.get("max_explicit_years")
        ),
        "junior_boost_multiplier": float(seniority_config["boost_multiplier"]),
        "junior_boost_terms": _normalize_text_list(
            seniority_config.get("boost_title_terms")
        ),
        "preferred_salary_max_gbp": _to_optional_float(
            salary_config.get("preferred_max_gbp")
        ),
        "salary_hard_cap_gbp": _to_optional_float(
            salary_config.get("hard_cap_gbp")
        ),
        "salary_penalty_max": float(salary_config["penalty_strength"]),
        "care_about_sponsorship": bool(eligibility_config["needs_sponsorship"]),
        "work_authorization_summary": _normalize_text(
            eligibility_config.get("work_authorization_summary")
        ),
        "care_about_hard_eligibility": bool(
            eligibility_config["check_hard_eligibility"]
        ),
        "use_sponsor_lookup": bool(eligibility_config["use_sponsor_lookup"]),
        "extra_screening_guidance": _normalize_text_list(
            llm_review_config.get("extra_screening_guidance")
        ),
        "extra_final_ranking_guidance": _normalize_text_list(
            llm_review_config.get("extra_final_ranking_guidance")
        ),
    }


def load_recipient_profiles(storage=None):
    if storage is None:
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is required to load recipient profiles from the database."
            )
        from storage import create_storage

        storage = create_storage(database_url)
        storage.ensure_schema()

    configured = storage.load_recipient_profile_configs(enabled_only=True)
    if not configured:
        raise RuntimeError(
            "No enabled recipient profiles were found in app_config.recipient_profiles. "
            "Load profiles into the database before running the scraper."
        )

    runtime_profiles = [
        _to_runtime_profile(
            normalize_grouped_profile(
                profile,
                index=index,
                sender_email=os.getenv("JOB_SCRAPER_EMAIL", ""),
            )
        )
        for index, profile in enumerate(configured)
    ]
    recipient_ids = [profile["id"] for profile in runtime_profiles]
    if len(recipient_ids) != len(set(recipient_ids)):
        raise RuntimeError("Recipient profile ids must be unique.")
    return runtime_profiles
