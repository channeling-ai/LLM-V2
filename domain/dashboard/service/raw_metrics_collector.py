"""대시보드 raw_metrics 수집기 (Spring `YoutubeUtil`+`RawMetricsCollector` 포팅).

채널 단위 YouTube Analytics 범위 호출(dimensions=day)로 **윈도우 전체(118일)를 매번 통째로** 가져온다.
범위 API는 기간 크기와 무관하게 호출 수가 ~3회(CORE/BROWSE/SUBSCRIBER)로 동일해, DB 캐시·gap-fill의
실익이 작아 슬림화했다. raw_metrics는 어디에도 저장하지 않고 점수 계산 입력으로만 메모리에서 쓴다.

- 비YPP(비수익화) 채널: browse/trafficSource·isSubscriber dimension이 400 "Unknown identifier" →
  해당 지표를 **None**(0 아님)으로 두고 ypp=False 표시 (`score_formulas`가 N/A 처리).
- 모든 날짜는 KST 기준. to=today-3 (T-3 지표 확정), from=max(today-120, join_date).
  (점수 윈도우가 anchor=today-3 기준이라 baseline 하한 today-120까지 필요 → score_calculation과 일치)
- upload_count는 Analytics에 없으므로 호출부(consumer)가 video 테이블에서 계산해 주입한다.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
FINALIZE_LAG = 3      # YouTube 지표 확정(T-3)
BACKFILL_DEPTH = 148  # baseline 하한: 그래프 최원거리 앵커(today-28-3)-117 = today-148
                       # (score_calculation.GRAPH_OFFSETS 최댓값 28을 커버. 범위 API는 기간
                       #  길이와 무관하게 호출 수가 고정이라, 깊이만 늘려도 API 호출 증가 없음 —
                       #  같은 day_map에서 앵커만 바꿔 그래프 소급 포인트까지 함께 계산한다)

_CORE_METRICS = "subscribersGained,subscribersLost,views,averageViewPercentage,likes,comments,shares"


def _is_ypp_only_error(status: int, body: str) -> bool:
    """impressions/trafficSourceType/isSubscriber 등 YPP 전용 요청 시 400 + Unknown identifier."""
    return status == 400 and "Unknown identifier" in body


async def _get(access_token: str, url: str) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    timeout = httpx.Timeout(connect=30.0, read=60.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        # ids=channel==MINE 의 '=='가 인코딩되지 않도록 URL을 직접 구성 (analytics_service.py와 동일 방식)
        return await client.get(url, headers=headers)


def _to_long(v) -> int:
    return int(v) if isinstance(v, (int, float)) else 0


def _to_float(v) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


async def _fetch_core_range(access_token: str, start: date, end: date) -> dict[date, list]:
    url = (f"{ANALYTICS_URL}?ids=channel==MINE&startDate={start}&endDate={end}"
           f"&metrics={_CORE_METRICS}&dimensions=day")
    resp = await _get(access_token, url)
    if resp.status_code != 200:
        raise RuntimeError(f"CORE_METRICS_RANGE {resp.status_code}: {resp.text}")
    rows = resp.json().get("rows") or []
    out: dict[date, list] = {}
    for row in rows:
        out[date.fromisoformat(str(row[0]))] = row
    return out


async def _fetch_browse_range(access_token: str, start: date, end: date) -> Optional[dict[date, int]]:
    """탐색(BROWSE_FEATURES)+추천(SUGGESTED_VIDEO) 유입 조회수 합산. 비YPP → None."""
    url = (f"{ANALYTICS_URL}?ids=channel==MINE&startDate={start}&endDate={end}"
           f"&metrics=views&dimensions=day,trafficSourceType")
    resp = await _get(access_token, url)
    if resp.status_code != 200:
        if _is_ypp_only_error(resp.status_code, resp.text):
            logger.warning("[Dashboard] BROWSE_TRAFFIC 비YPP 채널 - None 처리")
            return None
        raise RuntimeError(f"BROWSE_TRAFFIC_RANGE {resp.status_code}: {resp.text}")
    out: dict[date, int] = {}
    for row in resp.json().get("rows") or []:
        d = date.fromisoformat(str(row[0]))
        src = str(row[1])
        if src in ("BROWSE_FEATURES", "SUGGESTED_VIDEO"):
            out[d] = out.get(d, 0) + _to_long(row[2])
    return out


async def _fetch_subscriber_range(access_token: str, start: date, end: date) -> Optional[dict[date, int]]:
    """비구독자(isSubscriber=false) 조회수. 비YPP → None."""
    url = (f"{ANALYTICS_URL}?ids=channel==MINE&startDate={start}&endDate={end}"
           f"&metrics=views&dimensions=day,isSubscriber")
    resp = await _get(access_token, url)
    if resp.status_code != 200:
        if _is_ypp_only_error(resp.status_code, resp.text):
            logger.warning("[Dashboard] SUBSCRIBER_VIEW 비YPP 채널 - None 처리")
            return None
        raise RuntimeError(f"SUBSCRIBER_VIEW_RANGE {resp.status_code}: {resp.text}")
    out: dict[date, int] = {}
    for row in resp.json().get("rows") or []:
        d = date.fromisoformat(str(row[0]))
        if str(row[1]) == "false":
            out[d] = _to_long(row[2])
    return out


def compute_window_range(join_date: date, today_kst: date) -> tuple[date, date]:
    """수집할 [from, to] 구간 계산. from=max(today-117, join), to=today-3."""
    to_date = today_kst - timedelta(days=FINALIZE_LAG)
    from_date = max(today_kst - timedelta(days=BACKFILL_DEPTH), join_date)
    return from_date, to_date


async def collect_window(
    access_token: str,
    join_date: date,
    today_kst: date,
    upload_counts_by_date: Optional[dict[date, int]] = None,
) -> list[dict]:
    """윈도우 전체(최대 118일)의 일별 raw_metrics 행 리스트 반환 (snake_case dict).

    무활동 날도 0으로 채워 윈도우 일수(day_count)에 포함시킨다.
    """
    from_date, to_date = compute_window_range(join_date, today_kst)
    if from_date > to_date:
        logger.info("[Dashboard] 수집 구간 없음 - from: %s > to: %s", from_date, to_date)
        return []

    span = (to_date - from_date).days + 1
    logger.info("[Dashboard] 윈도우 수집 시작 - %s ~ %s (%d일)", from_date, to_date, span)
    upload_counts = upload_counts_by_date or {}

    core = await _fetch_core_range(access_token, from_date, to_date)
    logger.info("[Dashboard]   ├─ CORE_METRICS: 활동일 %d/%d", len(core), span)
    browse = await _fetch_browse_range(access_token, from_date, to_date)
    logger.info("[Dashboard]   ├─ BROWSE_TRAFFIC: %s", "비YPP(None)" if browse is None else f"{len(browse)}일")
    subscriber = await _fetch_subscriber_range(access_token, from_date, to_date)
    logger.info("[Dashboard]   └─ SUBSCRIBER_VIEW: %s", "비YPP(None)" if subscriber is None else f"{len(subscriber)}일")
    ypp = browse is not None and subscriber is not None

    rows: list[dict] = []
    d = from_date
    while d <= to_date:
        c = core.get(d)
        rows.append({
            "dashboard_date": d.isoformat(),
            "subscribers_gained": _to_long(c[1]) if c else 0,
            "subscribers_lost": _to_long(c[2]) if c else 0,
            "views": _to_long(c[3]) if c else 0,
            "average_view_percentage": _to_float(c[4]) if c else 0.0,
            "browse_and_suggested_views": (browse.get(d, 0) if ypp else None),
            "likes": _to_long(c[5]) if c else 0,
            "comments": _to_long(c[6]) if c else 0,
            "shares": _to_long(c[7]) if c else 0,
            "non_subscriber_views": (subscriber.get(d, 0) if ypp else None),
            "upload_count": upload_counts.get(d, 0),
            "ypp": ypp,
        })
        d += timedelta(days=1)

    logger.info("[Dashboard] 윈도우 수집 완료 - %d일치, ypp=%s", len(rows), ypp)
    return rows
