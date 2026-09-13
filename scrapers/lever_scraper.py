from urllib.parse import urlparse

import requests

from config.target_config import load_lever_targets
from shared.company_names import normalize_company_name
from shared.descriptions import HEADERS, fetch_job_description_details
from shared.job_urls import sanitize_job_url
from shared.locations import format_locations, is_location_match


LEVER_API_URL = "https://{api_host}/v0/postings/{site}?mode=json&skip={skip}&limit={limit}"
PAGE_SIZE = 100
DEFAULT_LEVER_API_HOST = "api.lever.co"
EU_LEVER_API_HOST = "api.eu.lever.co"


def normalize_lever_target(value):
    cleaned = value.strip()
    if "lever.co" not in cleaned:
        site = cleaned.strip("/").split("/")[-1]
        return {
            "site": site,
            "preferred_api_host": DEFAULT_LEVER_API_HOST,
        }

    parsed = urlparse(cleaned)
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return {
            "site": "",
            "preferred_api_host": DEFAULT_LEVER_API_HOST,
        }

    preferred_api_host = (
        EU_LEVER_API_HOST
        if (parsed.hostname or "").lower() == "jobs.eu.lever.co"
        else DEFAULT_LEVER_API_HOST
    )
    return {
        "site": path_parts[0],
        "preferred_api_host": preferred_api_host,
    }


def normalize_lever_site(value):
    return normalize_lever_target(value)["site"]


def load_sites(sites=None):
    if sites is None:
        sites = load_lever_targets()

    deduped_sites = {}
    for value in sites:
        normalized = normalize_lever_target(value)
        site = normalized["site"]
        if site and site not in deduped_sites:
            deduped_sites[site] = normalized

    return list(deduped_sites.values())


def _lever_api_hosts(preferred_api_host):
    if preferred_api_host == EU_LEVER_API_HOST:
        return [EU_LEVER_API_HOST, DEFAULT_LEVER_API_HOST]
    return [DEFAULT_LEVER_API_HOST, EU_LEVER_API_HOST]


def fetch_lever_jobs(site, preferred_api_host=DEFAULT_LEVER_API_HOST):
    failures = []

    for api_host in _lever_api_hosts(preferred_api_host):
        jobs = []
        skip = 0

        while True:
            url = LEVER_API_URL.format(
                api_host=api_host,
                site=site,
                skip=skip,
                limit=PAGE_SIZE,
            )
            try:
                response = requests.get(url, headers=HEADERS, timeout=20)
                response.raise_for_status()
                batch = response.json()
            except requests.RequestException as exc:
                failures.append((api_host, exc))
                break

            if not batch:
                return jobs

            jobs.extend(batch)
            if len(batch) < PAGE_SIZE:
                return jobs

            skip += PAGE_SIZE

    if failures:
        failure_messages = "; ".join(
            f"{api_host}: {exc}" for api_host, exc in failures
        )
        print(f"Failed to fetch Lever jobs for {site}: {failure_messages}")
    return []


def get_job_locations(job):
    categories = job.get("categories") or {}
    locations = [categories.get("location", "")]

    for value in categories.get("allLocations") or []:
        if isinstance(value, str):
            locations.append(value)

    return locations


def get_primary_location(job):
    categories = job.get("categories") or {}
    return (categories.get("location") or "").strip()


def is_flexible_location(value):
    normalized = (value or "").lower()
    return any(
        marker in normalized
        for marker in ["remote", "hybrid", "multiple", "various", "nationwide"]
    )


def get_job_url(job, site):
    return sanitize_job_url(
        job.get("hostedUrl")
        or job.get("applyUrl")
        or (
            f"https://jobs.lever.co/{site}/{job.get('id')}"
            if job.get("id")
            else ""
        ),
        source="lever",
        target_value=site,
    )


def collect_site_jobs(target, seen_urls, diagnostics=None, location_presets=None):
    site = target["site"]
    jobs = fetch_lever_jobs(site, target["preferred_api_host"])
    company_name = normalize_company_name(site)
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
        title = job.get("text", "")
        url = get_job_url(job, site)
        locations = get_job_locations(job)
        primary_location = get_primary_location(job)

        if primary_location and not is_flexible_location(primary_location):
            if not is_location_match([primary_location], location_presets):
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
                    "lever",
                    site,
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
                "source": "lever",
                "target_value": site,
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
        diagnostics.record_target_summary("lever", site, counts)

    return matches


def collect_jobs(seen_urls, sites=None, diagnostics=None, location_presets=None):
    matches = []
    for target in load_sites(sites):
        matches.extend(
            collect_site_jobs(
                target,
                seen_urls,
                diagnostics,
                location_presets=location_presets,
            )
        )
    return matches
