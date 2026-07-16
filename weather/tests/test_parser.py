from __future__ import annotations

import unittest

from parser import parse_forecast_page


def _item(category: str, value: object, forecast_time: str = "0900") -> dict:
    return {
        "baseDate": "20260716",
        "baseTime": "0800",
        "fcstDate": "20260716",
        "fcstTime": forecast_time,
        "category": category,
        "fcstValue": value,
        "nx": 60,
        "ny": 127,
    }


class ForecastParserTests(unittest.TestCase):
    def test_valid_values_and_mixed_precipitation_text_are_preserved(self) -> None:
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                "body": {
                    "items": {
                        "item": [
                            _item("TMP", 28),
                            _item("PCP", "강수없음"),
                            _item("SKY", "3"),
                        ]
                    },
                    "pageNo": 1,
                    "numOfRows": 1000,
                    "totalCount": 3,
                },
            }
        }

        parsed = parse_forecast_page(payload)

        self.assertEqual([value.value for value in parsed.values], ["28", "강수없음", "3"])
        self.assertEqual(parsed.skipped_items, 0)

    def test_missing_and_invalid_enumeration_values_are_skipped(self) -> None:
        payload = {
            "response": {
                "header": {"resultCode": 0, "resultMsg": "NORMAL_SERVICE"},
                "body": {
                    "items": {"item": [_item("TMP", 999), _item("SKY", 2)]},
                    "pageNo": 1,
                    "numOfRows": 1000,
                    "totalCount": 2,
                },
            }
        }

        parsed = parse_forecast_page(payload)

        self.assertEqual(parsed.values, ())
        self.assertEqual(parsed.skipped_items, 2)

    def test_single_item_object_is_normalized(self) -> None:
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                "body": {
                    "items": {"item": _item("POP", "60")},
                    "pageNo": 1,
                    "numOfRows": 1,
                    "totalCount": 1,
                },
            }
        }

        parsed = parse_forecast_page(payload)

        self.assertEqual(len(parsed.values), 1)
        self.assertEqual(parsed.values[0].category, "POP")

    def test_error_response_does_not_require_body_items(self) -> None:
        payload = {
            "response": {
                "header": {"resultCode": "22", "resultMsg": "LIMITED"},
                "body": {},
            }
        }

        parsed = parse_forecast_page(payload)

        self.assertEqual(parsed.result_code, "22")
        self.assertEqual(parsed.values, ())
