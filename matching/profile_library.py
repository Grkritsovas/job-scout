import re


DEFAULT_SEMANTIC_PROFILES = [
    "swe",
    "data_science",
    "ai_ml_engineer",
]

SEMANTIC_PROFILE_LIBRARY = {
    "swe": {
        "label": "SWE",
        "text": (
            "Early-career software engineer profile. Builds practical software "
            "systems with a strong Python foundation and experience working across "
            "application logic, data processing, APIs, structured file parsing, "
            "and user-facing tools. Has built end-to-end project components "
            "including a document parser that converts unstructured PDFs into valid "
            "JSON, a semantic query system that translates English text into "
            "structured queries, a mobile rehabilitation application, and a "
            "cloud-backed analytics dashboard. Comfortable writing clean "
            "application code, handling data flow between components, integrating "
            "external services, and building tools that are reliable and "
            "understandable. Also has exposure to full-stack and product-style "
            "work through Flutter/Dart, Firebase, Streamlit, and backend data "
            "handling. Best aligned with junior software engineering roles, "
            "backend-leaning roles, and generalist engineering roles where strong "
            "problem solving, Python, and structured systems thinking matter more "
            "than a specific web framework."
        ),
    },
    "data_science": {
        "label": "Data Science",
        "text": (
            "Early-career data science profile with strong grounding in applied "
            "machine learning, data processing, feature engineering, model "
            "evaluation, and exploratory analysis. Experience includes music "
            "emotion recognition, music genre classification, explainable machine "
            "learning, and research-focused experimentation on real datasets. Has "
            "worked on dimensionality reduction, feature selection, baseline "
            "comparison, performance improvement, and interpretable modelling. "
            "Comfortable using Python, pandas, NumPy, scikit-learn, TensorFlow, "
            "and PyTorch for practical analysis and modelling work. Also has "
            "experience turning messy or unstructured inputs into analysable data "
            "through scraping, parsing, and batch processing. Best aligned with "
            "junior data science, applied analytics, research assistant, and "
            "modelling-focused roles where experimentation, structured reasoning, "
            "and data understanding are central."
        ),
    },
    "ai_ml_engineer": {
        "label": "AI/ML",
        "text": (
            "Early-career AI and machine learning engineer profile focused on "
            "building practical ML-enabled systems end to end. Experience spans "
            "data collection and processing, model training, evaluation, "
            "experimentation, and supporting tooling around machine learning "
            "workflows. Has built ML projects in audio and music domains, "
            "including genre classification and emotion prediction, and has worked "
            "on explainability, representation learning, and domain adaptation. "
            "Also built supporting systems such as a parser that combines rules "
            "and LLM inference to extract structured JSON from PDFs, and a "
            "semantic search/query tool that maps natural language into structured "
            "retrieval. Comfortable with Python ML tooling including TensorFlow, "
            "scikit-learn, PyTorch, pandas, and NumPy. Best aligned with junior ML "
            "engineer, applied AI, AI software, and ML systems roles that combine "
            "software implementation with data and model work."
        ),
    },
}

PROFILE_ID_ALIASES = {
    "aiml": "ai_ml_engineer",
    "ai_ml": "ai_ml_engineer",
    "ai_ml_engineer": "ai_ml_engineer",
    "ai_ml_engineering": "ai_ml_engineer",
    "data science": "data_science",
    "data_science": "data_science",
    "ds": "data_science",
    "software_engineering": "swe",
    "software_engineer": "swe",
    "swe": "swe",
}

def normalize_profile_id(value):
    normalized = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return PROFILE_ID_ALIASES.get(normalized, normalized)


def get_default_semantic_profile_ids():
    return list(DEFAULT_SEMANTIC_PROFILES)


def display_label(profile_id):
    if profile_id in SEMANTIC_PROFILE_LIBRARY:
        return SEMANTIC_PROFILE_LIBRARY[profile_id]["label"]

    return profile_id.replace("_", " ").title()


def fallback_profile_text(profile_id):
    label = display_label(profile_id)
    label_lower = label.lower()
    return (
        f"Early-career {label_lower} profile. Best aligned with junior and "
        f"entry-level {label_lower} roles. Focus on responsibilities, tooling, "
        f"and day-to-day work that match {label_lower} positions."
    )


def build_profile_specs(recipient_profile):
    configured_ids = recipient_profile.get(
        "semantic_profiles"
    ) or get_default_semantic_profile_ids()
    custom_texts = {
        normalize_profile_id(profile_id): text
        for profile_id, text in (
            recipient_profile.get("semantic_profile_texts") or {}
        ).items()
    }
    specs = []

    for raw_profile_id in configured_ids:
        profile_id = normalize_profile_id(raw_profile_id)

        if profile_id in custom_texts:
            specs.append(
                {
                    "id": profile_id,
                    "label": display_label(profile_id),
                    "text": custom_texts[profile_id],
                }
            )
            continue

        if profile_id not in SEMANTIC_PROFILE_LIBRARY:
            specs.append(
                {
                    "id": profile_id,
                    "label": display_label(profile_id),
                    "text": fallback_profile_text(profile_id),
                }
            )
            continue

        profile_entry = SEMANTIC_PROFILE_LIBRARY[profile_id]
        specs.append(
            {
                "id": profile_id,
                "label": profile_entry["label"],
                "text": profile_entry["text"],
            }
        )

    cv = str(recipient_profile.get("cv") or "").strip()
    if cv:
        for spec in specs:
            spec["cv"] = cv
    return specs
