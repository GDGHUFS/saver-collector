import os
import asyncio
import httpx
import dotenv
from pathlib import Path

dotenv.load_dotenv(Path(__file__).resolve().parents[1].joinpath(".env"))

anniversary_api_key = os.getenv("ANNIVERSARY_API_KEY")
if anniversary_api_key is None:
    raise Exception("ANNIVERSARY_API_KEY is not set")

async def fetch_anniversary_data():
    """
    예시 응답
    {'response': {'header': {'resultCode': '00', 'resultMsg': 'NORMAL SERVICE.'}, 'body': {'items': {'item': [{'dateKind': '01', 'dateName': '전국동시지방선거', 'isHoliday': 'Y', 'locdate': 20260603, 'seq': 1}, {'dateKind': '01', 'dateName': '현충일', 'isHoliday': 'Y', 'locdate': 20260606, 'seq': 2}]}, 'numOfRows': 10, 'pageNo': 1, 'totalCount': 2}}}
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getHoliDeInfo?solYear=2026&solMonth=06&_type=json&ServiceKey={anniversary_api_key}")
        response.raise_for_status()
        print(response.json())

asyncio.run(fetch_anniversary_data())