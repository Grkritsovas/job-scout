import json

import requests
from bs4 import BeautifulSoup

from config.target_config import load_nextjs_targets
from shared.company_names import get_company_name_from_url
from shared.descriptions import HEADERS, fetch_job_description_details
from shared.job_urls import normalize_seed_url, sanitize_job_url
from shared.locations import format_locations, is_location_match


def load_urls(urls=None):
    if urls is not None:
        return list(
            dict.fromkeys(
                normalized_url
                for normalized_url in (normalize_seed_url(url) for url in urls)
                if normalized_url
            )
        )

    return list(
        dict.fromkeys(
            normalized_url
            for normalized_url in (
                normalize_seed_url(url) for url in load_nextjs_targets()
            )
            if normalized_url
        )
    )


def fetch_nextjs_data(url):
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    script = soup.find("script", {"id": "__NEXT_DATA__"})

    if not script or not script.string:
        raise ValueError(f"No __NEXT_DATA__ block found for {url}")

    return json.loads(script.string)


def extract_jobs(data):
    page_props = data.get("props", {}).get("pageProps", {})
    return page_props.get("jobPostings", [])


def get_job_url(job):
    return (
        job.get("applyUrl")
        or job.get("url")
        or job.get("applyLink")
        or job.get("externalLink")
        or ""
    )


def get_job_locations(job):
    return [
        job.get("location", ""),
        job.get("locationName", ""),
        job.get("jobLocation", ""),
    ]


def collect_url_jobs(url, seen_urls, diagnostics=None, location_presets=None):
    counts = {
        "fetched_jobs": 0,
        "location_jobs": 0,
        "url_ok_jobs": 0,
        "new_jobs": 0,
        "description_ok_jobs": 0,
        "html_like_descriptions": 0,
        "usable_jobs": 0,
        "reason": "no_jobs",
        "sample_title": "",
    }
    company_name = get_company_name_from_url(url)
    matches = []

    try:
        data = fetch_nextjs_data(url)
        jobs = extract_jobs(data)
        counts["fetched_jobs"] = len(jobs)
    except Exception as exc:
        counts["reason"] = f"fetch_failed:{exc.__class__.__name__}"
        if diagnostics is not None:
            diagnostics.record_target_summary("nextjs", url, counts)
        return matches

    for job in jobs:
        title = job.get("title", "")
        job_url = sanitize_job_url(
            get_job_url(job),
            source="nextjs",
            target_value=url,
        )
        locations = get_job_locations(job)
        if any(locations) and not is_location_match(locations, location_presets):
            continue
        counts["location_jobs"] += 1

        if not job_url:
            continue
        counts["url_ok_jobs"] += 1

        if job_url in seen_urls:
            continue
        counts["new_jobs"] += 1

        description_info = fetch_job_description_details(job_url)
        description = description_info["description"]
        if not description:
            continue
        counts["description_ok_jobs"] += 1
        if description_info["looks_like_html"]:
            counts["html_like_descriptions"] += 1
            if diagnostics is not None:
                diagnostics.record_description_fallback(
                    "nextjs",
                    url,
                    title.strip(),
                    job_url,
                    description_info["status"],
                    description_info["looks_like_html"],
                )

        matches.append(
            {
                "company": company_name,
                "title": title.strip(),
                "url": job_url,
                "description": description,
                "locations": locations,
                "location": format_locations(locations),
                "source": "nextjs",
                "target_value": url,
                "description_status": description_info["status"],
                "description_looks_like_html": description_info["looks_like_html"],
            }
        )
        seen_urls.add(job_url)
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
        diagnostics.record_target_summary("nextjs", url, counts)

    return matches


def collect_jobs(seen_urls, urls=None, diagnostics=None, location_presets=None):
    matches = []
    for url in load_urls(urls):
        matches.extend(
            collect_url_jobs(
                url,
                seen_urls,
                diagnostics,
                location_presets=location_presets,
            )
        )
    return matches
