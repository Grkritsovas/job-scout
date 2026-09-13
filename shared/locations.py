import re


DEFAULT_LOCATION_PRESET = "UK"
LOCATION_PRESET_ALIASES = {
    "gb": "UK",
    "greece": "Greece",
    "gr": "Greece",
    "uk": "UK",
    "united kingdom": "UK",
}

UK_LOCATION_TERMS = {
    "aberdeen",
    "bath",
    "basingstoke",
    "belfast",
    "blackburn",
    "blackpool",
    "birmingham",
    "bournemooth",
    "bournemouth",
    "bristol",
    "cambridge",
    "cardif",
    "cardiff",
    "cheltenham",
    "coventry",
    "crawley",
    "crawly",
    "darlington",
    "devon",
    "doncaster",
    "dorchester",
    "dumfries",
    "edinburgh",
    "edingburgh",
    "exeter",
    "falkirk",
    "farnborough",
    "farnham",
    "galashiels",
    "glasgow",
    "guildford",
    "harrow",
    "hinckley",
    "horsham",
    "hull",
    "inverness",
    "isle of wight",
    "kent",
    "kilmarnock",
    "kingston upon thames",
    "lancashire",
    "lancaster",
    "leeds",
    "leicester",
    "london",
    "maidstone",
    "manchester",
    "middlesborough",
    "middlesbrough",
    "newcastle",
    "newport",
    "northern ireland",
    "oldham",
    "oxford",
    "oxfordshire",
    "perth",
    "plymouth",
    "portsmouth",
    "reading",
    "redhill",
    "scotland",
    "sheffield",
    "shefield",
    "slough",
    "somerset",
    "southampton",
    "stockport",
    "stockton-on-tees",
    "surrey",
    "swindon",
    "taunton",
    "teesside",
    "torquay",
    "truro",
    "warwick",
    "west midlands",
    "weybridge",
    "woking",
    "york",
}

BAD_LOCATION_KEYWORDS = [
    "hop",
    "warehouse",
    "trading estate",
    "rider",
    "delivery",
    "store",
    "kitchen",
    "site",
]

COUNTRY_LEVEL_UK_PATTERNS = [
    r"\buk\b",
    r"united kingdom",
    r"\bgb\b",
    r"remote\s*\(uk\)",
    r"\bengland\b",
    r"\bscotland\b",
    r"\bnorthern ireland\b",
]

COUNTRY_LEVEL_GREECE_PATTERNS = [
    r"\bgreece\b",
    r"\bgr\b",
    "\u03b5\u03bb\u03bb\u03ac\u03b4\u03b1",
    "\u03b5\u03bb\u03bb\u03ac\u03c2",
]

GREECE_LOCATION_TERMS = {
    "athens",
    "attica",
    "crete",
    "heraklion",
    "patras",
    "thessaloniki",
    "\u03b1\u03b8\u03ae\u03bd\u03b1",
    "\u03b8\u03b5\u03c3\u03c3\u03b1\u03bb\u03bf\u03bd\u03af\u03ba\u03b7",
}

FOREIGN_LOCATION_KEYWORDS = [
    "united states",
    "usa",
    "canada",
    "australia",
    "ukraine",
    "brazil",
    "mexico",
    "new york",
    "serbia",
    "germany",
    "romania",
    "cyprus",
    "switzerland",
    "portugal",
    "lithuania",
    "czech republic",
    "poland",
    "spain",
    "france",
    "italy",
    "ireland",
    "belgrade",
    "berlin",
    "sydney",
    "new south wales",
]

US_STATE_CODES = {
    "ak",
    "al",
    "ar",
    "az",
    "ca",
    "co",
    "ct",
    "dc",
    "de",
    "fl",
    "ga",
    "hi",
    "ia",
    "id",
    "il",
    "in",
    "ks",
    "ky",
    "la",
    "ma",
    "md",
    "me",
    "mi",
    "mn",
    "mo",
    "ms",
    "mt",
    "nc",
    "nd",
    "ne",
    "nh",
    "nj",
    "nm",
    "nv",
    "ny",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "va",
    "vt",
    "wa",
    "wi",
    "wv",
    "wy",
}


def _contains_location_term(location_text, location_term):
    pattern = (
        r"(?<![a-z])"
        + re.escape(location_term).replace(r"\ ", r"\s+")
        + r"(?![a-z])"
    )
    return re.search(pattern, location_text) is not None


def _decision(accepted, reason, location="", matched_term=""):
    return {
        "accepted": accepted,
        "reason": reason,
        "location": location,
        "matched_term": matched_term,
    }


def _contains_us_state_code(location_text):
    state_pattern = "|".join(sorted(US_STATE_CODES))
    return bool(
        re.search(
            rf"(?:^|[,\s(/-])(?:{state_pattern})(?:$|[,\s)/-])",
            location_text,
        )
    )


def get_uk_location_decision(locations):
    if isinstance(locations, str):
        locations = [locations]

    fallback_rejection = _decision(False, "no_match")

    for location in locations:
        if not location:
            continue

        normalized = location.lower()

        bad_keyword = next(
            (keyword for keyword in BAD_LOCATION_KEYWORDS if keyword in normalized),
            "",
        )
        if bad_keyword:
            fallback_rejection = _decision(
                False,
                "bad_keyword",
                location,
                bad_keyword,
            )
            continue

        country_pattern = next(
            (
                pattern
                for pattern in COUNTRY_LEVEL_UK_PATTERNS
                if re.search(pattern, normalized)
            ),
            "",
        )
        if country_pattern:
            return _decision(True, "country_level_uk", location, country_pattern)

        foreign_keyword = next(
            (
                keyword
                for keyword in FOREIGN_LOCATION_KEYWORDS
                if keyword in normalized
            ),
            "",
        )
        if foreign_keyword:
            fallback_rejection = _decision(
                False,
                "foreign_keyword",
                location,
                foreign_keyword,
            )
            continue

        if _contains_us_state_code(normalized):
            fallback_rejection = _decision(
                False,
                "foreign_region",
                location,
                "us_state_code",
            )
            continue

        for location_term in sorted(UK_LOCATION_TERMS):
            if _contains_location_term(normalized, location_term):
                return _decision(
                    True,
                    "uk_location_term",
                    location,
                    location_term,
                )

        fallback_rejection = _decision(False, "no_match", location)

    return fallback_rejection


def is_uk_location(locations):
    return get_uk_location_decision(locations)["accepted"]


def get_greece_location_decision(locations):
    if isinstance(locations, str):
        locations = [locations]

    fallback_rejection = _decision(False, "no_match")

    for location in locations:
        if not location:
            continue

        normalized = location.lower()
        country_pattern = next(
            (
                pattern
                for pattern in COUNTRY_LEVEL_GREECE_PATTERNS
                if re.search(pattern, normalized)
            ),
            "",
        )
        if country_pattern:
            return _decision(True, "country_level_greece", location, country_pattern)

        foreign_keyword = next(
            (
                keyword
                for keyword in FOREIGN_LOCATION_KEYWORDS
                if keyword in normalized
            ),
            "",
        )
        if foreign_keyword:
            fallback_rejection = _decision(
                False,
                "foreign_keyword",
                location,
                foreign_keyword,
            )
            continue

        if _contains_us_state_code(normalized):
            fallback_rejection = _decision(
                False,
                "foreign_region",
                location,
                "us_state_code",
            )
            continue

        for location_term in sorted(GREECE_LOCATION_TERMS):
            if _contains_location_term(normalized, location_term):
                return _decision(
                    True,
                    "greece_location_term",
                    location,
                    location_term,
                )

        fallback_rejection = _decision(False, "no_match", location)

    return fallback_rejection


def normalize_location_preset(value):
    normalized = " ".join(str(value or DEFAULT_LOCATION_PRESET).lower().split())
    preset = LOCATION_PRESET_ALIASES.get(normalized)
    if preset:
        return preset

    supported = ", ".join(sorted(set(LOCATION_PRESET_ALIASES.values())))
    raise ValueError(
        f"Unsupported location preset '{value}'. Supported values: {supported}."
    )


def get_location_decision(locations, location_preset=DEFAULT_LOCATION_PRESET):
    preset = normalize_location_preset(location_preset)
    if preset == "Greece":
        return get_greece_location_decision(locations)
    return get_uk_location_decision(locations)


def is_location_match(locations, location_presets=None):
    presets = location_presets or [DEFAULT_LOCATION_PRESET]
    if isinstance(presets, str):
        presets = [presets]
    return any(
        get_location_decision(locations, preset)["accepted"]
        for preset in presets
    )


def dedupe_keep_order(values):
    return list(dict.fromkeys(value for value in values if value))


def format_locations(locations):
    unique_locations = dedupe_keep_order(locations)
    return ", ".join(unique_locations)
