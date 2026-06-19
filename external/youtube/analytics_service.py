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


def find_worst_drop(
    analytics_rows: list,
    video_length: float,
    min_ratio: float = 0.05,  # 앞 5% 자연 이탈 제외
) -> dict:
    """
    상대적 낙폭 기준 최대 이탈 지점 1개 반환
    반환: {"ratio": float, "sec": float}
    """
    if not analytics_rows:
        return {"ratio": min_ratio, "sec": min_ratio * video_length}

    # 앞 5%: 영상 시작 직후 자연 이탈 구간 제외
    # 뒤 5%: 영상 종료 직전 자연 이탈 구간 제외
    filtered = [r for r in analytics_rows if min_ratio < r[0] < 0.95]
    worst_ratio, worst_drop = min_ratio, 0.0

    for i in range(1, len(filtered)):
        prev, curr = filtered[i - 1][1], filtered[i][1]
        if prev <= 0:
            continue
        # 절대 낙폭 대신 상대 낙폭 사용
        # 후반부는 유지율이 낮아 절대값이 작아도 실제론 심각한 이탈일 수 있음
        # 예) 80%→60% (상대 25%) vs 30%→10% (상대 67%) — 후자가 더 심각
        relative_drop = (prev - curr) / prev
        if relative_drop > worst_drop:
            worst_drop = relative_drop
            worst_ratio = filtered[i][0]

    return {"ratio": worst_ratio, "sec": worst_ratio * video_length}


def build_critical_section(worst_ratio: float, video_length: float) -> dict:
    """
    worst_ratio: find_worst_drop()["ratio"]
    반환: {"startTime": "MM:SS", "endTime": "MM:SS", "duration": int}
    """
    worst_sec = worst_ratio * video_length

    # 구간 크기: 영상 길이의 4%, 최소 10초 ~ 최대 300초
    focus_range = max(10, min(int(0.04 * video_length), 300))

    # 영상 경계를 넘지 않도록 클램핑
    start_sec = max(0.0, worst_sec - focus_range / 2)
    end_sec   = min(video_length, worst_sec + focus_range / 2)

    def fmt(sec: float) -> str:
        m, s = divmod(int(sec), 60)
        return f"{m:02d}:{s:02d}"

    return {
        "startTime": fmt(start_sec),
        "endTime":   fmt(end_sec),
        "duration":  int(end_sec - start_sec),
    }


VALID_NUM_TICKS = {4, 5, 10, 20, 25, 50, 100}


def build_retention_graph(
    analytics_rows: list,
    video_length: float,
    num_ticks: int = 10,  # 100의 약수여야 함
) -> list:
    """
    analytics_rows: 100개 고정 rows [elapsedVideoTimeRatio, audienceWatchRatio, ...]
    반환: [{"time": "1:24", "retentionRate": 85}, ...]
    """
    if not analytics_rows or num_ticks <= 0:
        return []

    if num_ticks not in VALID_NUM_TICKS:
        raise ValueError(f"num_ticks는 {VALID_NUM_TICKS} 중 하나여야 합니다: {num_ticks}")

    step = len(analytics_rows) // num_ticks

    # 첫 row 기준으로 정규화 → 영상 시작 시점을 100%로 간주
    # row[1]이 0이면 divide-by-zero 방지
    base = analytics_rows[0][1] if analytics_rows[0][1] > 0 else 1.0

    result = []
    for i in range(num_ticks):
        row = analytics_rows[i * step]
        time_sec = row[0] * video_length        # elapsedRatio → 실제 초
        m, s = divmod(int(time_sec), 60)
        result.append({
            "time":          f"{m}:{s:02d}",    # "1:24" 형식 (M:SS, 앞 0 없음)
            "retentionRate": min(100, round((row[1] / base) * 100)),  # 100 초과 방지
        })
    return result


def map_grade(score: int) -> str:
    """0~3: NEEDS_IMPROVEMENT / 4~6: NORMAL / 7~10: GOOD"""
    if score <= 3:
        return "NEEDS_IMPROVEMENT"
    if score <= 6:
        return "NORMAL"
    return "GOOD"
