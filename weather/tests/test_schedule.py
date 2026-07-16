from __future__ import annotations

import unittest
from datetime import datetime

from schedule import KST, latest_available_issue, parse_issue_datetime


class ScheduleTests(unittest.TestCase):
    def test_before_publication_delay_uses_previous_selected_issue(self) -> None:
        now = datetime(2026, 7, 16, 8, 9, tzinfo=KST)

        issue = latest_available_issue(now, (2, 8, 14, 20), 10)

        self.assertEqual(issue, datetime(2026, 7, 16, 2, 0, tzinfo=KST))

    def test_after_publication_delay_uses_current_selected_issue(self) -> None:
        now = datetime(2026, 7, 16, 8, 10, tzinfo=KST)

        issue = latest_available_issue(now, (2, 8, 14, 20), 10)

        self.assertEqual(issue, datetime(2026, 7, 16, 8, 0, tzinfo=KST))

    def test_early_morning_uses_previous_day(self) -> None:
        now = datetime(2026, 7, 16, 1, 0, tzinfo=KST)

        issue = latest_available_issue(now, (2, 8, 14, 20), 10)

        self.assertEqual(issue, datetime(2026, 7, 15, 20, 0, tzinfo=KST))

    def test_manual_issue_requires_official_hour(self) -> None:
        with self.assertRaises(ValueError):
            parse_issue_datetime("202607160900")
