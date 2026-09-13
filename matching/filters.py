HARD_SENIORITY_TERMS = [
    "senior",
    "staff",
    "lead",
    "principal",
    "head",
    "director",
]

HARD_COMMERCIAL_TERMS = [
    "sales",
    "account executive",
    "business development",
    "customer success",
    "designer",
    "talent acquisition",
    "talent community",
    "recruiter",
    "marketing",
    "partnerships",
    "general counsel",
    "legal counsel",
]

# Match whole target-role names, not technical words in unrelated roles.
COMMERCIAL_EXCLUSION_TECH_ROLE_PATTERN = (
    r"(?:(?:junior|senior|staff|lead|principal|graduate|entry level|early career) )?"
    r"(?:swe|sde|ai ml(?: engineer(?:ing)?)?|"
    r"software development engineer|"
    r"(?:software|backend|frontend|full stack|fullstack|data|machine learning|ml|ai) "
    r"(?:engineer(?:ing)?|developer|development)|"
    r"data (?:science|scientist|analyst|analytics))"
    r"(?: (?:intern|internship|graduate|junior|senior))?"
)

HARD_ELIGIBILITY_TITLE_TERMS = []

AUTHORIZATION_MISMATCH_PATTERNS = [
    r"authorized to work in (?:the )?(?:us|usa|united states)\b",
    r"eligible to work in (?:the )?(?:us|usa|united states)\b",
    r"must be based in (?:the )?(?:us|usa|united states)\b",
    r"must reside in (?:the )?(?:us|usa|united states)\b",
    r"authorized to work in canada\b",
    r"eligible to work in canada\b",
]

ELIGIBILITY_REJECT_PATTERNS = [
    r"\bmust be planning on graduating in \d{4}\b",
    r"\bthis should be your final internship before graduating\b",
    r"\bwith a graduation date between\b",
    r"\bgraduation date between\b",
    r"\bmust be (?:currently )?enrolled\b",
    r"\bcurrently enrolled\b",
    r"\bcurrently pursuing.{0,80}\b(?:degree|b\.?s\.?|m\.?s\.?|bsc|msc|bachelor|master|phd)\b",
    r"\benrolled in (?:a |an |your )?(?:degree|university|college|school|course|program|programme)\b",
    r"\bpursuing (?:a |an |your )?(?:degree|bachelor|bachelors|master|masters|phd|b\.?s\.?|m\.?s\.?|bsc|msc)\b",
    r"\breturning to (?:a |an |your )?(?:degree|university|college|school|course|program|programme)\b",
    r"\breturn to (?:a |an |your )?(?:degree|university|college|school|course|program|programme)\b",
    r"\bstudents only\b",
    r"\bcurrent student\b",
]

QUALITATIVE_EXPERIENCE_REJECT_PATTERNS = [
    r"\bdeep experience\b",
    r"\bextensive experience\b",
]
