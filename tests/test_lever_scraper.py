import unittest
from unittest.mock import Mock, patch

from scrapers.lever_scraper import (
    DEFAULT_LEVER_API_HOST,
    EU_LEVER_API_HOST,
    collect_site_jobs,
    fetch_lever_jobs,
    get_job_locations,
    get_primary_location,
    is_flexible_location,
    load_sites,
    normalize_lever_target,
)
from utils import is_uk_location


class LeverScraperTests(unittest.TestCase):
    def test_primary_location_is_used_for_non_flexible_roles(self):
        job = {
            "categories": {
                "location": "New York, NY",
                "allLocations": ["New York, NY", "London, United Kingdom"],
            }
        }

        primary_location = get_primary_location(job)
        locations = get_job_locations(job)

        self.assertEqual("New York, NY", primary_location)
        self.assertFalse(is_flexible_location(primary_location))
        self.assertFalse(is_uk_location([primary_location]))
        self.assertTrue(is_uk_location(locations))

    def test_remote_primary_location_can_fall_back_to_all_locations(self):
        job = {
            "categories": {
                "location": "Remote",
                "allLocations": ["United Kingdom"],
            }
        }

        primary_location = get_primary_location(job)
        locations = get_job_locations(job)

        self.assertTrue(is_flexible_location(primary_location))
        self.assertTrue(is_uk_location(locations))

    def test_normalize_lever_target_from_slug_defaults_to_standard_api(self):
        self.assertEqual(
            {
                "site": "palantir",
                "preferred_api_host": DEFAULT_LEVER_API_HOST,
            },
            normalize_lever_target("palantir"),
        )

    def test_normalize_lever_target_from_eu_url_prefers_eu_api(self):
        self.assertEqual(
            {
                "site": "cirrus",
                "preferred_api_host": EU_LEVER_API_HOST,
            },
            normalize_lever_target("https://jobs.eu.lever.co/cirrus?location=London"),
        )

    def test_load_sites_dedupes_by_site_but_preserves_preferred_host(self):
        self.assertEqual(
            [
                {
                    "site": "cirrus",
                    "preferred_api_host": EU_LEVER_API_HOST,
                }
            ],
            load_sites(
                [
                    "https://jobs.eu.lever.co/cirrus?location=London",
                    "cirrus",
                ]
            ),
        )

    @patch("scrapers.lever_scraper.fetch_job_description_details")
    @patch("scrapers.lever_scraper.fetch_lever_jobs")
    def test_collect_site_jobs_accepts_greece_location_preset(
        self,
        mock_fetch_lever_jobs,
        mock_fetch_job_description_details,
    ):
        mock_fetch_lever_jobs.return_value = [
            {
                "id": "job-gr",
                "text": "Marketing Assistant",
                "hostedUrl": "https://jobs.eu.lever.co/example/job-gr",
                "categories": {
                    "location": "Remote - Greece",
                    "allLocations": ["Greece"],
                },
            }
        ]
        mock_fetch_job_description_details.return_value = {
            "description": "Support campaigns.",
            "status": "visible_text",
            "looks_like_html": False,
        }

        jobs = collect_site_jobs(
            {
                "site": "example",
                "preferred_api_host": EU_LEVER_API_HOST,
            },
            set(),
            location_presets=["Greece"],
        )

        self.assertEqual(1, len(jobs))
        self.assertEqual("Remote - Greece, Greece", jobs[0]["location"])

    @patch("scrapers.lever_scraper.requests.get")
    def test_fetch_lever_jobs_falls_back_to_eu_api_after_standard_404(self, mock_get):
        response_404 = Mock()
        response_404.raise_for_status.side_effect = __import__("requests").HTTPError(
            "404 Client Error"
        )
        response_404.json.return_value = {"ok": False, "error": "Document not found"}

        response_200 = Mock()
        response_200.raise_for_status.return_value = None
        response_200.json.return_value = [{"text": "Software Engineer"}]

        response_empty = Mock()
        response_empty.raise_for_status.return_value = None
        response_empty.json.return_value = []

        def fake_get(url, headers=None, timeout=None):
            if url.startswith(
                "https://api.lever.co/v0/postings/cirrus?mode=json&skip=0&limit=100"
            ):
                return response_404
            if url.startswith(
                "https://api.eu.lever.co/v0/postings/cirrus?mode=json&skip=0&limit=100"
            ):
                return response_200
            if url.startswith(
                "https://api.eu.lever.co/v0/postings/cirrus?mode=json&skip=100&limit=100"
            ):
                return response_empty
            raise AssertionError(url)

        mock_get.side_effect = fake_get

        jobs = fetch_lever_jobs("cirrus", DEFAULT_LEVER_API_HOST)

        self.assertEqual([{"text": "Software Engineer"}], jobs)


if __name__ == "__main__":
    unittest.main()
