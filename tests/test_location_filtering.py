import unittest

from shared.locations import (
    get_greece_location_decision,
    get_uk_location_decision,
    is_location_match,
    normalize_location_preset,
)
from utils import is_uk_location


class LocationFilteringTests(unittest.TestCase):
    def test_accepts_city_only_uk_locations_seen_in_job_boards(self):
        self.assertTrue(is_uk_location(["Bath"]))
        self.assertTrue(is_uk_location(["Aberdeen (GB)"]))
        self.assertTrue(is_uk_location(["Newcastle, UK"]))
        self.assertTrue(is_uk_location(["Stockton-on-Tees"]))
        self.assertTrue(is_uk_location(["West Midlands"]))
        self.assertTrue(is_uk_location(["Belfast"]))
        self.assertTrue(is_uk_location(["Belfast, Northern Ireland"]))

    def test_accepts_common_misspelled_uk_locations_seen_in_feed(self):
        self.assertTrue(is_uk_location(["Cardif (GB)"]))
        self.assertTrue(is_uk_location(["Bournemooth (GB)"]))
        self.assertTrue(is_uk_location(["Middlesborough"]))
        self.assertTrue(is_uk_location(["Shefield"]))

    def test_still_rejects_non_uk_locations(self):
        self.assertFalse(is_uk_location(["Berlin"]))
        self.assertFalse(is_uk_location(["Sydney, Australia"]))
        self.assertFalse(is_uk_location(["Remote (United States)"]))
        self.assertFalse(is_uk_location(["New York, NY"]))
        self.assertFalse(is_uk_location(["Newport Beach, CA"]))

    def test_location_decision_explains_match_or_rejection(self):
        accepted = get_uk_location_decision(["Newcastle, UK"])
        rejected = get_uk_location_decision(["Newport Beach, CA"])

        self.assertTrue(accepted["accepted"])
        self.assertEqual("country_level_uk", accepted["reason"])
        self.assertFalse(rejected["accepted"])
        self.assertEqual("foreign_region", rejected["reason"])
        self.assertEqual("us_state_code", rejected["matched_term"])

    def test_greece_preset_accepts_explicit_greek_locations(self):
        self.assertTrue(is_location_match(["Greece"], "Greece"))
        self.assertTrue(is_location_match(["Remote - Greece"], "Greece"))
        self.assertTrue(is_location_match(["Athens, Attica"], "Greece"))
        self.assertTrue(is_location_match(["Thessaloniki"], "Greece"))
        self.assertTrue(
            is_location_match(
                ["\u0398\u03b5\u03c3\u03c3\u03b1\u03bb\u03bf\u03bd\u03af\u03ba\u03b7"],
                "Greece",
            )
        )

    def test_greece_preset_rejects_ambiguous_or_foreign_remote_locations(self):
        self.assertFalse(is_location_match(["Remote"], "Greece"))
        self.assertFalse(is_location_match(["Remote - Europe"], "Greece"))
        self.assertFalse(is_location_match(["Athens, GA"], "Greece"))
        self.assertFalse(is_location_match(["London"], "Greece"))

    def test_greece_location_decision_explains_match(self):
        decision = get_greece_location_decision(["Remote - Greece"])

        self.assertTrue(decision["accepted"])
        self.assertEqual("country_level_greece", decision["reason"])

    def test_location_preset_normalization_is_limited_to_supported_values(self):
        self.assertEqual("UK", normalize_location_preset(""))
        self.assertEqual("UK", normalize_location_preset("United Kingdom"))
        self.assertEqual("Greece", normalize_location_preset("gr"))
        with self.assertRaisesRegex(ValueError, "Unsupported location preset"):
            normalize_location_preset("Spain")


if __name__ == "__main__":
    unittest.main()
