from urllib.parse import parse_qs, quote, unquote, urlparse

import requests

from config.target_config import load_ashby_targets
from shared.company_names import normalize_company_name
from shared.descriptions import HEADERS, fetch_job_description_details
from shared.job_urls import sanitize_job_url
from shared.locations import format_locations, is_location_match


def normalize_ashby_target(value):
    cleaned = (value or "").strip()
    if not cleaned:
        return {"company": "", "location_ids": set(), "label": ""}

    if "ashbyhq.com" not in cleaned:
        company = cleaned.lower()
        return {"company": company, "location_ids": set(), "label": company}

    parsed = urlparse(cleaned)
    path_parts = [part for part in parsed.path.split("/") if part]
    company = unquote(path_parts[0]).lower() if path_parts else ""
    query_params = parse_qs(parsed.query)
    location_ids = {
        location_id.strip()
        for location_id in query_params.get("locationId", [])
        if location_id.strip()
    }
    return {
        "company": company,
        "location_ids": location_ids,
        "label": cleaned,
    }


def load_targets(companies=None):
    if companies is None:
        companies = load_ashby_targets()

    deduped_targets = {}
    for company in companies:
        normalized = normalize_ashby_target(company)
        key = (
            normalized["company"],
            tuple(sorted(normalized["location_ids"])),
        )
        if normalized["company"] and key not in deduped_targets:
            deduped_targets[key] = normalized

    return list(deduped_targets.values())


def fetch_ashby_jobs(company):
    payload = {
        "operationName": "GetPublicJobListings",
        "variables": {
            "organizationHostedJobsPageName": company,
        },
        "query": """
            query GetPublicJobListings($organizationHostedJobsPageName: String!) {
                jobBoardWithTeams(
                    organizationHostedJobsPageName: $organizationHostedJobsPageName
                ) {
                    jobPostings {
                        id
                        title
                        locationName
                        locationId
                        secondaryLocations {
                            locationName
                            locationId
                        }
                    }
                }
            }
        """,
    }

    try:
        response = requests.post(
            "https://jobs.ashbyhq.com/api/non-user-graphql",
            json=payload,
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"Failed to fetch Ashby jobs for {company}: {exc}")
        return []

    job_board = data.get("data", {}).get("jobBoardWithTeams")
    if not job_board:
        print(f"No Ashby job board found for {company}: {data}")
        return []

    return job_board.get("jobPostings", [])


def get_job_locations(job):
    secondary_locations = [
        location.get("locationName", "")
        for location in job.get("secondaryLocations") or []
    ]
    return [job.get("locationName", ""), *secondary_locations]


def get_job_location_ids(job):
    secondary_location_ids = [
        location.get("locationId", "")
        for location in job.get("secondaryLocations") or []
    ]
    return {location_id for location_id in [job.get("locationId", ""), *secondary_location_ids] if location_id}


def collect_company_jobs(
    target,
    seen_urls,
    diagnostics=None,
    location_presets=None,
):
    company = target["company"]
    location_ids = target["location_ids"]
    target_label = target["label"] or company
    jobs = fetch_ashby_jobs(company)
    matches = []
    company_name = normalize_company_name(company)
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
        job_id = job.get("id")
        quoted_company = quote(company, safe="")
        url = (
            sanitize_job_url(
                f"https://jobs.ashbyhq.com/{quoted_company}/{job_id}",
                source="ashby",
                target_value=company,
            )
            if job_id
            else ""
        )

        locations = get_job_locations(job)
        if location_ids:
            if not (get_job_location_ids(job) & location_ids):
                continue
        elif not is_location_match(locations, location_presets):
            continue
        counts["location_jobs"] += 1

        if not url:
            continue
        counts["url_ok_jobs"] += 1

        if url in seen_urls:
            continue
        counts["new_jobs"] += 1

        description_info = fetch_job_description_details(url)
        description = description_info["description"]
        if not description:
            continue
        counts["description_ok_jobs"] += 1
        if description_info["looks_like_html"]:
            counts["html_like_descriptions"] += 1
            if diagnostics is not None:
                diagnostics.record_description_fallback(
                    "ashby",
                    company,
                    title.strip(),
                    url,
                    description_info["status"],
                    description_info["looks_like_html"],
                )

        matches.append(
            {
                "company": company_name,
                "title": title.strip(),
                "url": url,
                "description": description,
                "locations": locations,
                "location": format_locations(locations),
                "source": "ashby",
                "target_value": target_label,
                "description_status": description_info["status"],
                "description_looks_like_html": description_info["looks_like_html"],
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
        diagnostics.record_target_summary("ashby", target_label, counts)

    return matches


def collect_jobs(seen_urls, companies=None, diagnostics=None, location_presets=None):
    matches = []
    for target in load_targets(companies):
        matches.extend(
            collect_company_jobs(
                target,
                seen_urls,
                diagnostics,
                location_presets=location_presets,
            )
        )
    return matches
