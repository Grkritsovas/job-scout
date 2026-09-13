import html
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from config.target_config import load_greenhouse_targets
from shared.company_names import normalize_company_name
from shared.descriptions import HEADERS, get_visible_text
from shared.job_urls import sanitize_job_url
from shared.locations import format_locations, is_location_match


GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
GREENHOUSE_FETCH_ALL_TOKENS = {"ritual"}


def normalize_board_token(value):
    cleaned = value.strip()
    if "greenhouse.io" not in cleaned:
        return cleaned.strip("/").split("/")[-1]

    parsed = urlparse(cleaned)
    query_params = parse_qs(parsed.query)
    board_token = (query_params.get("for") or [""])[0].strip()
    if board_token:
        return board_token

    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return ""

    return path_parts[0]


def load_board_tokens(board_tokens=None):
    if board_tokens is None:
        board_tokens = load_greenhouse_targets()

    return list(
        dict.fromkeys(
            normalized
            for normalized in (normalize_board_token(value) for value in board_tokens)
            if normalized
        )
    )


def fetch_greenhouse_jobs(board_token):
    url = GREENHOUSE_API_URL.format(board_token=board_token)

    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"Failed to fetch Greenhouse jobs for {board_token}: {exc}")
        return []

    return data.get("jobs", [])


def get_greenhouse_locations(job):
    locations = [job.get("location", {}).get("name", "")]

    for office in job.get("offices") or []:
        office_location = office.get("location", "")
        if office_location:
            locations.append(office_location)

    return locations


def get_greenhouse_description(job):
    content = html.unescape(job.get("content", ""))
    if not content:
        return {
            "description": "",
            "status": "missing_content",
            "looks_like_html": False,
        }

    return {
        "description": get_visible_text(content),
        "status": "job_content",
        "looks_like_html": False,
    }


def get_greenhouse_job_url(job):
    raw_url = (job.get("absolute_url") or "").strip()
    if not raw_url:
        return ""

    if raw_url.startswith("/"):
        return urljoin("https://boards.greenhouse.io", raw_url)

    return raw_url


def collect_board_jobs(
    board_token,
    seen_urls,
    diagnostics=None,
    location_presets=None,
):
    jobs = fetch_greenhouse_jobs(board_token)
    company_name = normalize_company_name(board_token)
    matches = []
    counts = {
        "fetched_jobs": len(jobs),
        "location_jobs": 0,
        "url_ok_jobs": 0,
        "new_jobs": 0,
        "description_ok_jobs": 0,
        "html_like_descriptions": 0,
        "usable_jobs": 0,
        "reason": "no_jobs",
        "sample_title": "",
    }

    for job in jobs:
        title = job.get("title", "")
        raw_url = get_greenhouse_job_url(job)
        url = sanitize_job_url(
            raw_url,
            source="greenhouse",
            target_value=board_token,
        )
        locations = get_greenhouse_locations(job)
        location_candidates = [*locations, title]

        if (
            board_token.lower() not in GREENHOUSE_FETCH_ALL_TOKENS
            and not is_location_match(location_candidates, location_presets)
        ):
            continue
        counts["location_jobs"] += 1

        if not url:
            if diagnostics is not None:
                diagnostics.record_url_rejection(
                    "greenhouse",
                    board_token,
                    title.strip(),
                    raw_url,
                )
            continue
        counts["url_ok_jobs"] += 1

        if url in seen_urls:
            continue
        counts["new_jobs"] += 1

        description_info = get_greenhouse_description(job)
        description = description_info["description"]
        if not description:
            continue
        counts["description_ok_jobs"] += 1

        matches.append(
            {
                "company": company_name,
                "title": title.strip(),
                "url": url,
                "description": description,
                "locations": locations,
                "location": format_locations(locations),
                "source": "greenhouse",
                "target_value": board_token,
                "description_status": description_info["status"],
                "description_looks_like_html": False,
            }
        )
        seen_urls.add(url)
        counts["usable_jobs"] += 1
        if not counts["sample_title"]:
            counts["sample_title"] = title.strip()

    if counts["fetched_jobs"] and not counts["location_jobs"]:
        counts["reason"] = "no_matching_location_jobs"
    elif counts["location_jobs"] and not counts["url_ok_jobs"]:
        counts["reason"] = "no_valid_urls"
    elif counts["url_ok_jobs"] and not counts["new_jobs"]:
        counts["reason"] = "already_seen_or_duplicate"
    elif counts["new_jobs"] and not counts["description_ok_jobs"]:
        counts["reason"] = "description_fetch_failed"
    elif counts["description_ok_jobs"] and not counts["usable_jobs"]:
        counts["reason"] = "no_usable_jobs"
    elif counts["usable_jobs"]:
        counts["reason"] = "ok"

    if diagnostics is not None:
        diagnostics.record_target_summary("greenhouse", board_token, counts)

    return matches


def collect_jobs(
    seen_urls,
    board_tokens=None,
    diagnostics=None,
    location_presets=None,
):
    matches = []
    for board_token in load_board_tokens(board_tokens):
        matches.extend(
            collect_board_jobs(
                board_token,
                seen_urls,
                diagnostics,
                location_presets=location_presets,
            )
        )
    return matches
