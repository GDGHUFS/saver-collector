from __future__ import annotations

import unittest
from pathlib import Path

from locations import load_location_dataset


WEATHER_DIR = Path(__file__).resolve().parents[1]
LOCATIONS_PATH = next(WEATHER_DIR.glob("*격자_위경도*.xlsx"))


class LocationDatasetTests(unittest.TestCase):
    def test_provided_workbook_is_normalized(self) -> None:
        dataset = load_location_dataset(LOCATIONS_PATH)

        self.assertEqual(len(dataset.locations), 3838)
        self.assertEqual(len(dataset.grid_points), 1632)
        self.assertEqual(
            sum(location.longitude is None for location in dataset.locations),
            2,
        )
        self.assertEqual(len({item.administrative_code for item in dataset.locations}), 3838)
