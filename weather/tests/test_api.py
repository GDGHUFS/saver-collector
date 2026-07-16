from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx

from api import (
    DailyRequestLimitError,
    FatalWeatherApiError,
    WeatherApiClient,
    build_request_url,
)
from grid import grid_to_latitude_longitude
from schedule import KST


class WeatherApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_forecast_follows_all_pages(self) -> None:
        issued_at = datetime(2026, 7, 16, 8, 0, tzinfo=KST)
        grid = grid_to_latitude_longitude(60, 127)

        def handler(request: httpx.Request) -> httpx.Response:
            query = parse_qs(request.url.query.decode())
            page_no = int(query["pageNo"][0])
            items = [
                self._item("TMP", "28", "0900"),
                self._item("SKY", "1", "0900"),
            ] if page_no == 1 else [self._item("TMP", "29", "1000")]
            return httpx.Response(
                200,
                json={
                    "response": {
                        "header": {
                            "resultCode": "00",
                            "resultMsg": "NORMAL_SERVICE",
                        },
                        "body": {
                            "items": {"item": items},
                            "pageNo": page_no,
                            "numOfRows": 2,
                            "totalCount": 3,
                        },
                    }
                },
            )

        settings = SimpleNamespace(
            api_key="encoded%2Bkey%3D",
            base_url="http://example.test/weather",
            requests_per_second=100000.0,
            max_attempts=1,
            retry_base_delay=0.001,
            num_of_rows=2,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetched = await WeatherApiClient(client, settings).fetch_forecast(
                grid,
                issued_at,
            )

        self.assertEqual(fetched.page_count, 2)
        self.assertEqual(fetched.total_count, 3)
        self.assertEqual(len(fetched.values), 3)

    async def test_daily_request_limit_stops_before_http_call(self) -> None:
        issued_at = datetime(2026, 7, 16, 8, 0, tzinfo=KST)
        grid = grid_to_latitude_longitude(60, 127)
        http_called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal http_called
            http_called = True
            return httpx.Response(500)

        async def reject_request() -> bool:
            return False

        settings = SimpleNamespace(
            api_key="encoded%2Bkey%3D",
            base_url="http://example.test/weather",
            requests_per_second=100000.0,
            max_attempts=1,
            retry_base_delay=0.001,
            num_of_rows=1000,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api_client = WeatherApiClient(
                client,
                settings,
                reserve_request=reject_request,
            )
            with self.assertRaises(DailyRequestLimitError):
                await api_client.fetch_forecast(grid, issued_at)

        self.assertFalse(http_called)

    async def test_fatal_api_error_stops_following_grid_before_http(self) -> None:
        issued_at = datetime(2026, 7, 16, 8, 0, tzinfo=KST)
        grid = grid_to_latitude_longitude(60, 127)
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(
                200,
                json={
                    "response": {
                        "header": {
                            "resultCode": "22",
                            "resultMsg": "LIMITED_NUMBER_OF_REQUESTS",
                        },
                        "body": {},
                    }
                },
            )

        settings = SimpleNamespace(
            api_key="encoded%2Bkey%3D",
            base_url="http://example.test/weather",
            requests_per_second=100000.0,
            max_attempts=1,
            retry_base_delay=0.001,
            num_of_rows=1000,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api_client = WeatherApiClient(client, settings)
            with self.assertRaises(FatalWeatherApiError):
                await api_client.fetch_forecast(grid, issued_at)
            with self.assertRaises(FatalWeatherApiError):
                await api_client.fetch_forecast(grid, issued_at)

        self.assertEqual(request_count, 1)

    def test_encoded_api_key_is_not_encoded_again(self) -> None:
        issued_at = datetime(2026, 7, 16, 8, 0, tzinfo=KST)
        url = build_request_url(
            base_url="http://example.test/weather",
            api_key="encoded%2Bkey%3D",
            issued_at=issued_at,
            grid=grid_to_latitude_longitude(60, 127),
            page_no=1,
            num_of_rows=1000,
        )

        self.assertIn("serviceKey=encoded%2Bkey%3D", url)
        self.assertNotIn("%252B", url)

    @staticmethod
    def _item(category: str, value: str, forecast_time: str) -> dict:
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
