from datetime import date
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException

app = FastAPI()

async def get_youtube_analytics_data(
    access_token: str,
    video_id: str,
    metrics: str,
    dimensions=None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    import logging
    logger = logging.getLogger(__name__)

    _start = start_date or "2000-01-01"
    _end = end_date or str(date.today())

    url = (
        "https://youtubeanalytics.googleapis.com/v2/reports"
        "?ids=channel==MINE"
        f"&startDate={_start}"
        f"&endDate={_end}"
        f"&metrics={metrics}"
        f"&filters=video=={video_id}"
    )

    if dimensions:
        url += f"&dimensions={dimensions}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    timeout = httpx.Timeout(connect=30.0, read=60.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)

    if response.status_code == 429:
        logger.error("YouTube Analytics API 요청 한도 초과 (429 Too Many Requests)")
        raise HTTPException(
            status_code=429,
            detail="YouTube Analytics API 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
        )
    elif response.status_code == 401:
        logger.error("YouTube Analytics API 인증 실패 (401 Unauthorized) - 토큰이 만료되었거나 권한이 없습니다.")
        raise HTTPException(
            status_code=401,
            detail="Google Access Token이 유효하지 않습니다. 토큰을 갱신해주세요."
        )
    elif response.status_code == 403:
        logger.error("YouTube Analytics API 권한 부족 (403 Forbidden)")
        error_data = response.json() if response.text else {}
        if "error" in error_data:
            error_reason = error_data.get("error", {}).get("errors", [{}])[0].get("reason", "unknown")
            if error_reason == "quotaExceeded":
                logger.error("YouTube Analytics API 일일 할당량 초과")
                raise HTTPException(
                    status_code=403,
                    detail="YouTube Analytics API 일일 할당량을 초과했습니다."
                )
        raise HTTPException(
            status_code=403,
            detail=f"YouTube Analytics API 접근 권한이 없습니다: {response.text}"
        )
    elif response.status_code != 200:
        logger.error(f"YouTube Analytics API 오류 ({response.status_code}): {response.text}")
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Failed to fetch data: {response.text}"
        )

    return response.json()


def find_max_drop_time(analytics_rows, video_length_sec=60):
        # 종료 구간 제외 (예: elapsedRatio >= 0.95)
    filtered_rows = [row for row in analytics_rows if row[0] < 0.95]

    max_drop = 0
    drop_point = 0.0

    for i in range(1, len(filtered_rows)):
        prev_ratio = filtered_rows[i - 1][1]  # audienceWatchRatio
        curr_ratio = filtered_rows[i][1]
        drop = prev_ratio - curr_ratio

        if drop > max_drop:
            max_drop = drop
            drop_point = filtered_rows[i][0]  # elapsedVideoTimeRatio

    return drop_point
