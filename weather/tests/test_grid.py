from __future__ import annotations

import unittest

from grid import grid_to_latitude_longitude, latitude_longitude_to_grid


class GridConversionTests(unittest.TestCase):
    def test_documented_coordinate_converts_to_expected_grid(self) -> None:
        grid = latitude_longitude_to_grid(37.488201, 126.929810)

        self.assertEqual((grid.nx, grid.ny), (59, 125))

    def test_documented_grid_converts_to_expected_coordinate(self) -> None:
        grid = grid_to_latitude_longitude(59, 125)

        self.assertAlmostEqual(grid.longitude, 126.929810, places=5)
        self.assertAlmostEqual(grid.latitude, 37.488201, places=5)

    def test_out_of_range_coordinate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            latitude_longitude_to_grid(0.0, 0.0)
