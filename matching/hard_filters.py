import re

from matching.filters import (
    AUTHORIZATION_MISMATCH_PATTERNS,
    ELIGIBILITY_REJECT_PATTERNS,
    HARD_COMMERCIAL_TERMS,
    HARD_ELIGIBILITY_TITLE_TERMS,
    HARD_SENIORITY_TERMS,
    QUALITATIVE_EXPERIENCE_REJECT_PATTERNS,
    RECIPIENT_AWARE_COMMERCIAL_TERMS,
)
from shared.locations import DEFAULT_LOCATION_PRESET, is_location_match


DEFAULT_MAX_YEARS_EXPERIENCE = 1
APPLICANT_SECTION_HEADER_PATTERN = re.compile(
    r"\bfor\s+(?P<region>united states|us|usa|canada|united kingdom|uk)\s+applicants?\s*:",
    flags=re.IGNORECASE,
)
UK_APPLICANT_SECTION_REGIONS = {"united kingdom", "uk"}
NON_UK_AUTHORIZATION_SECTION_REGIONS = {
    "united states",
    "us",
    "usa",
    "canada",
}

EXPERIENCE_PATTERNS = [
    re.compile(r"\b(\d+)\+\s*(?:years?|yrs?|yoe)\b", flags=re.IGNORECASE),
    re.compile(r"\bat least\s+(\d+)\s*(?:years?|yrs?|yoe)\b", flags=re.IGNORECASE),
    re.compile(
        r"\bminimum of\s+(\d+)\s*(?:years?|yrs?|yoe)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(r"\bminimum\s+(\d+)\s*(?:years?|yrs?|yoe)\b", flags=re.IGNORECASE),
    re.compile(
        r"\b(\d+)\s*[-\u2013\u2014]\s*(\d+)\s*(?:years?|yrs?|yoe)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d+)\s*to\s*(\d+)\s*(?:years?|yrs?|yoe)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d+)\s*(?:years?|yrs?|yoe)\s+(?:of\s+)?experience\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d+)\s*[-\u2013\u2014]\s*(\d+)\s*(?:years?|yrs?|yoe)\s+"
        r"(?:of\s+)?(?:[a-z]+\s+){0,6}experience\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d+)\s*(?:years?|yrs?|yoe)\s+(?:of\s+)?"
        r"(?:[a-z]+\s+){0,6}experience\b",
        flags=re.IGNORECASE,
    ),
]


def _term_pattern(term):
    escaped = re.escape(term.strip().lower())
    escaped = escaped.replace(r"\ ", r"[\s-]+")
    escaped = escaped.replace(r"\-", r"[\s-]+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", flags=re.IGNORECASE)


def title_has_hard_reject_term(title, reject_terms):
    normalized_title = (title or "").lower()
    return any(
        _term_pattern(term).search(normalized_title)
        for term in reject_terms
        if str(term).strip()
    )


def _profile_id_like(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _recipient_target_role_ids(recipient_profile):
    if not recipient_profile:
        return []

    role_ids = [
        _profile_id_like(profile_id)
        for profile_id in recipient_profile.get("semantic_profiles", [])
    ]

    candidate_config = recipient_profile.get("candidate") or {}
    for role in candidate_config.get("target_roles") or []:
        if isinstance(role, str):
            role_ids.append(_profile_id_like(role))
            continue
        if isinstance(role, dict):
            role_ids.append(
                _profile_id_like(
                    role.get("id") or role.get("profile_id") or role.get("name")
                )
            )

    return [role_id for role_id in role_ids if role_id]


def _recipient_targets_term(recipient_profile, term):
    term_id = _profile_id_like(term)
    return any(
        term_id in role_id
        for role_id in _recipient_target_role_ids(recipient_profile)
    )


def get_commercial_reject_terms(recipient_profile=None):
    if not recipient_profile:
        return list(HARD_COMMERCIAL_TERMS)

    return [
        term
        for term in HARD_COMMERCIAL_TERMS
        if term not in RECIPIENT_AWARE_COMMERCIAL_TERMS
        or not _recipient_targets_term(recipient_profile, term)
    ]


def has_authorization_mismatch(description):
    normalized_description = _strip_non_uk_applicant_authorization_sections(
        description or ""
    ).lower()
    return any(
        re.search(pattern, normalized_description, flags=re.IGNORECASE)
        for pattern in AUTHORIZATION_MISMATCH_PATTERNS
    )


def _strip_non_uk_applicant_authorization_sections(description):
    section_headers = list(APPLICANT_SECTION_HEADER_PATTERN.finditer(description))
    if not section_headers:
        return description

    has_uk_section = any(
        header.group("region").lower() in UK_APPLICANT_SECTION_REGIONS
        for header in section_headers
    )
    if not has_uk_section:
        return description

    retained_parts = []
    cursor = 0
    for index, header in enumerate(section_headers):
        region = header.group("region").lower()
        next_start = (
            section_headers[index + 1].start()
            if index + 1 < len(section_headers)
            else len(description)
        )
        if region in NON_UK_AUTHORIZATION_SECTION_REGIONS:
            retained_parts.append(description[cursor : header.start()])
            cursor = next_start

    retained_parts.append(description[cursor:])
    return "".join(retained_parts)


def has_eligibility_mismatch(description):
    normalized_description = (description or "").lower()
    return any(
        re.search(pattern, normalized_description, flags=re.IGNORECASE)
        for pattern in ELIGIBILITY_REJECT_PATTERNS
    )


def has_qualitative_experience_mismatch(description):
    normalized_description = (description or "").lower()
    return any(
        re.search(pattern, normalized_description, flags=re.IGNORECASE)
        for pattern in QUALITATIVE_EXPERIENCE_REJECT_PATTERNS
    )


def extract_required_experience_years(description):
    if not description:
        return []

    required_years = []
    for pattern in EXPERIENCE_PATTERNS:
        for match in pattern.finditer(description):
            groups = [group for group in match.groups() if group]
            if not groups:
                continue
            required_years.append(max(int(group) for group in groups))

    return required_years


def passes_experience_filter(
    description,
    max_years_experience=DEFAULT_MAX_YEARS_EXPERIENCE,
):
    if not description:
        return False

    if max_years_experience is None:
        return True

    if has_qualitative_experience_mismatch(description):
        return False

    return not any(
        years_required > max_years_experience
        for years_required in extract_required_experience_years(description)
    )


def get_hard_filter_reason(
    job,
    max_years_experience=DEFAULT_MAX_YEARS_EXPERIENCE,
    recipient_profile=None,
):
    title = job.get("title", "")
    description = job.get("description", "")
    locations = job.get("locations") or [job.get("location", "")]
    location_preset = DEFAULT_LOCATION_PRESET
    if recipient_profile:
        location_preset = recipient_profile.get("location_preset") or (
            recipient_profile.get("job_preferences") or {}
        ).get("location") or DEFAULT_LOCATION_PRESET

    if title_has_hard_reject_term(title, HARD_SENIORITY_TERMS):
        return "title_seniority"

    if title_has_hard_reject_term(
        title,
        get_commercial_reject_terms(recipient_profile),
    ):
        return "title_commercial"

    if title_has_hard_reject_term(title, HARD_ELIGIBILITY_TITLE_TERMS):
        return "title_eligibility"

    if not is_location_match(locations, location_preset):
        return "location"

    if has_authorization_mismatch(description):
        return "authorization"

    if has_eligibility_mismatch(description):
        return "eligibility"

    if not passes_experience_filter(description, max_years_experience):
        return "experience"

    return None


def passes_hard_filters(
    job,
    max_years_experience=DEFAULT_MAX_YEARS_EXPERIENCE,
    recipient_profile=None,
):
    return get_hard_filter_reason(
        job,
        max_years_experience,
        recipient_profile=recipient_profile,
    ) is None
