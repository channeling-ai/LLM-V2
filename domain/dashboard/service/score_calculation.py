"""윈도우 롤링 SUM → 점수 조립 (Spring `ScoreCalculationService` 포팅).

수집기가 가져온 윈도우 전체(118일) 일별 수치를 날짜→수치 맵으로 만든 뒤
current/previous/baseline 윈도우를 SUM 한다. DB 캐시 없이 전부 메모리에서 합산한다.

윈도우는 지표 확정 경계인 anchor = today-3(FINALIZE_LAG)을 기준점으로 잡는다.
수집기가 today-3까지만 데이터를 주므로, 윈도우도 거기서 끝나야 current가 온전한 28일이 된다
(today 기준으로 잡으면 최근 3일이 비어 current가 25일이 되고 delta가 과소 계산됨).

윈도우 (anchor = today-3, KST 고정; 근거 SCORE_FORMULA_DEV.md §C):
  current  = [anchor-27, anchor]    # = [today-30, today-3]   온전한 28일
  previous = [anchor-55, anchor-28] # = [today-58, today-31]  current 직전 28일 (delta 비교용)
  baseline = [anchor-117, anchor-28]# = [today-120, today-31] current 직전 90일 (중첩 제거)
"""

import logging
from datetime import date, timedelta
from typing import Optional

from domain.dashboard.service.score_formulas import WindowSum, calculate_all

logger = logging.getLogger(__name__)

CURRENT_DAYS = 28
BASELINE_DEPTH = 117
FINALIZE_LAG = 3      # 지표 확정 지연 → 윈도우 기준점 anchor=today-3 (raw_metrics_collector와 일치)


def _num(v) -> float:
    return v if isinstance(v, (int, float)) else 0


def _get(m: dict, snake: str, camel: str):
    """DB(camelCase) / 수집기(snake_case) 양쪽 키를 지원."""
    v = m.get(snake)
    return v if v is not None else m.get(camel)


def _normalize_day(m: dict) -> dict:
    return {
        "subscribers_gained": _num(_get(m, "subscribers_gained", "subscribersGained")),
        "subscribers_lost": _num(_get(m, "subscribers_lost", "subscribersLost")),
        "views": _num(_get(m, "views", "views")),
        "average_view_percentage": _num(_get(m, "average_view_percentage", "averageViewPercentage")),
        "likes": _num(_get(m, "likes", "likes")),
        "comments": _num(_get(m, "comments", "comments")),
        "shares": _num(_get(m, "shares", "shares")),
        "upload_count": _num(_get(m, "upload_count", "uploadCount")),
        # 비YPP면 None 그대로 유지 (0으로 깔지 않음)
        "browse_and_suggested_views": _get(m, "browse_and_suggested_views", "browseAndSuggestedViews"),
        "non_subscriber_views": _get(m, "non_subscriber_views", "nonSubscriberViews"),
        "ypp": bool(_get(m, "ypp", "ypp")),
    }


def build_day_map(rows: list[dict]) -> dict[date, dict]:
    """수집한 일별 행(snake_case)을 날짜→정규화수치 맵으로 변환."""
    return {date.fromisoformat(r["dashboard_date"]): _normalize_day(r) for r in rows}


def _window_sum(day_map: dict[date, dict], start: date, end: date) -> WindowSum:
    days = [day_map[d] for d in day_map if start <= d <= end]
    ypp = any(d["ypp"] for d in days)

    browse: Optional[int] = (
        int(sum((d["browse_and_suggested_views"] or 0) for d in days)) if ypp else None
    )
    non_sub: Optional[int] = (
        int(sum((d["non_subscriber_views"] or 0) for d in days)) if ypp else None
    )

    return WindowSum(
        day_count=len(days),
        subscribers_gained=int(sum(d["subscribers_gained"] for d in days)),
        subscribers_lost=int(sum(d["subscribers_lost"] for d in days)),
        views=int(sum(d["views"] for d in days)),
        avp_times_views=float(sum(d["average_view_percentage"] * d["views"] for d in days)),
        likes=int(sum(d["likes"] for d in days)),
        comments=int(sum(d["comments"] for d in days)),
        shares=int(sum(d["shares"] for d in days)),
        upload_count=int(sum(d["upload_count"] for d in days)),
        ypp=ypp,
        browse_and_suggested_views=browse,
        non_subscriber_views=non_sub,
    )


def calculate_scores(day_map: dict[date, dict], today: date) -> dict[str, dict[str, Optional[int]]]:
    """6개 지표 score/delta(12개)를 {지표: {"score":..., "delta":...}}로 반환."""
    anchor = today - timedelta(days=FINALIZE_LAG)               # today-3 (지표 확정 경계)
    cur_start = anchor - timedelta(days=CURRENT_DAYS - 1)       # anchor-27
    current = _window_sum(day_map, cur_start, anchor)
    previous = _window_sum(
        day_map, anchor - timedelta(days=2 * CURRENT_DAYS - 1), cur_start - timedelta(days=1)
    )  # [anchor-55, anchor-28]
    baseline = _window_sum(
        day_map, anchor - timedelta(days=BASELINE_DEPTH), anchor - timedelta(days=CURRENT_DAYS)
    )  # [anchor-117, anchor-28]

    logger.info(
        "[Dashboard] 윈도우 SUM - current(%d일 views=%d subs=%+d) / previous(%d일 views=%d) / baseline(%d일 views=%d) ypp=%s",
        current.day_count, current.views, current.subscribers_gained - current.subscribers_lost,
        previous.day_count, previous.views,
        baseline.day_count, baseline.views, current.ypp,
    )

    scores = calculate_all(current, previous, baseline)
    return scores


def calculate_subscriber_delta(day_map: dict[date, dict], today: date) -> Optional[int]:
    """current 윈도우(=[today-30, today-3], 28일)의 구독자 순증감(gained-lost) 합산.

    "한 달 전 대비 구독자 변화량"으로 대시보드에 노출한다. 추가 API 없이
    수집기가 이미 가져온 일별 gained/lost를 SUM 하며, 점수 윈도우와 동일 기준을 쓴다.
    데이터 부족(윈도우에 수집일 0) → None (score_formulas의 day_count<=0 기준과 동일).
    무활동(데이터는 있으나 순증감 0)은 0으로 구분된다.
    """
    anchor = today - timedelta(days=FINALIZE_LAG)          # today-3 (지표 확정 경계)
    cur_start = anchor - timedelta(days=CURRENT_DAYS - 1)  # anchor-27
    current = _window_sum(day_map, cur_start, anchor)
    if current.day_count <= 0:
        return None
    return int(current.subscribers_gained - current.subscribers_lost)
