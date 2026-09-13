import unittest
from unittest.mock import patch

from scrapers.nextjs_scraper import collect_url_jobs


class NextJsScraperTests(unittest.TestCase):
    @patch("scrapers.nextjs_scraper.fetch_job_description_details")
    @patch("scrapers.nextjs_scraper.fetch_nextjs_data")
    def test_collect_url_jobs_accepts_greece_location_preset(
        self,
        mock_fetch_nextjs_data,
        mock_fetch_job_description_details,
    ):
        mock_fetch_nextjs_data.return_value = {
            "props": {
                "pageProps": {
                    "jobPostings": [
                        {
                            "title": "Marketing Assistant",
                            "applyUrl": "https://careers.example.com/jobs/123",
                            "locationName": "Thessaloniki, Greece",
                        }
                    ]
                }
            }
        }
        mock_fetch_job_description_details.return_value = {
            "description": "Support campaigns.",
            "status": "visible_text",
            "looks_like_html": False,
        }

        jobs = collect_url_jobs(
            "https://careers.example.com/jobs",
            set(),
            location_presets=["Greece"],
        )

        self.assertEqual(1, len(jobs))
        self.assertEqual("Thessaloniki, Greece", jobs[0]["location"])


if __name__ == "__main__":
    unittest.main()
