import unittest
from unittest.mock import patch

from scrapers.ashby_scraper import collect_company_jobs, normalize_ashby_target


class AshbyScraperTests(unittest.TestCase):
    def test_normalize_ashby_target_from_slug(self):
        self.assertEqual(
            {
                "company": "elevenlabs",
                "location_ids": set(),
                "label": "elevenlabs",
            },
            normalize_ashby_target("elevenlabs"),
        )

    def test_normalize_ashby_target_from_filtered_url(self):
        self.assertEqual(
            {
                "company": "elevenlabs",
                "location_ids": {"b3bb71bc-8a73-4ba3-ba86-cb13a0777d4d"},
                "label": "https://jobs.ashbyhq.com/elevenlabs?locationId=b3bb71bc-8a73-4ba3-ba86-cb13a0777d4d",
            },
            normalize_ashby_target(
                "https://jobs.ashbyhq.com/elevenlabs?locationId=b3bb71bc-8a73-4ba3-ba86-cb13a0777d4d"
            ),
        )

    def test_normalize_ashby_target_decodes_encoded_company_name(self):
        self.assertEqual(
            {
                "company": "it labs",
                "location_ids": set(),
                "label": "https://jobs.ashbyhq.com/it%20labs",
            },
            normalize_ashby_target("https://jobs.ashbyhq.com/it%20labs"),
        )

    @patch("scrapers.ashby_scraper.fetch_job_description_details")
    @patch("scrapers.ashby_scraper.fetch_ashby_jobs")
    def test_collect_company_jobs_url_encodes_company_name(
        self,
        mock_fetch_ashby_jobs,
        mock_fetch_job_description_details,
    ):
        mock_fetch_ashby_jobs.return_value = [
            {
                "id": "job-1",
                "title": "Software Engineer",
                "locationName": "London",
                "locationId": "london-id",
                "secondaryLocations": [],
            }
        ]
        mock_fetch_job_description_details.return_value = {
            "description": "Build things.",
            "status": "visible_text",
            "looks_like_html": False,
        }

        jobs = collect_company_jobs(
            {
                "company": "it labs",
                "location_ids": set(),
                "label": "https://jobs.ashbyhq.com/it%20labs",
            },
            set(),
        )

        self.assertEqual(1, len(jobs))
        self.assertEqual("https://jobs.ashbyhq.com/it%20labs/job-1", jobs[0]["url"])

    @patch("scrapers.ashby_scraper.fetch_job_description_details")
    @patch("scrapers.ashby_scraper.fetch_ashby_jobs")
    def test_collect_company_jobs_can_filter_by_exact_location_id(
        self,
        mock_fetch_ashby_jobs,
        mock_fetch_job_description_details,
    ):
        mock_fetch_ashby_jobs.return_value = [
            {
                "id": "job-1",
                "title": "Software Engineer",
                "locationName": "United Kingdom",
                "locationId": "uk-id",
                "secondaryLocations": [],
            },
            {
                "id": "job-2",
                "title": "Product Designer",
                "locationName": "London",
                "locationId": "london-id",
                "secondaryLocations": [],
            },
        ]
        mock_fetch_job_description_details.return_value = {
            "description": "Build things.",
            "status": "visible_text",
            "looks_like_html": False,
        }

        jobs = collect_company_jobs(
            {
                "company": "elevenlabs",
                "location_ids": {"uk-id"},
                "label": "https://jobs.ashbyhq.com/elevenlabs?locationId=uk-id",
            },
            set(),
        )

        self.assertEqual(1, len(jobs))
        self.assertEqual("Software Engineer", jobs[0]["title"])

    @patch("scrapers.ashby_scraper.fetch_job_description_details")
    @patch("scrapers.ashby_scraper.fetch_ashby_jobs")
    def test_collect_company_jobs_accepts_greece_location_preset(
        self,
        mock_fetch_ashby_jobs,
        mock_fetch_job_description_details,
    ):
        mock_fetch_ashby_jobs.return_value = [
            {
                "id": "job-gr",
                "title": "Marketing Coordinator",
                "locationName": "Remote - Greece",
                "locationId": "greece-id",
                "secondaryLocations": [],
            }
        ]
        mock_fetch_job_description_details.return_value = {
            "description": "Support campaigns.",
            "status": "visible_text",
            "looks_like_html": False,
        }

        jobs = collect_company_jobs(
            {
                "company": "example",
                "location_ids": set(),
                "label": "example",
            },
            set(),
            location_presets=["Greece"],
        )

        self.assertEqual(1, len(jobs))
        self.assertEqual("Remote - Greece", jobs[0]["location"])


if __name__ == "__main__":
    unittest.main()
