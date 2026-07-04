"""역주행(재유입) 영상 탐지 — VIRAL_VIDEO suggestion 카드 입력.

YouTube Analytics(`dimensions=video`)로 최근 윈도우의 영상별 조회수를 받아,
'오래 전 업로드됐는데 최근 다시 조회가 몰리는' 영상을 찾는다.

역주행 점수 = (최근 일평균 조회수) / (생애 일평균 조회수).
오래된 영상은 보통 최근 조회가 생애 평균보다 훨씬 낮으므로, 이 비율이 1을 넘으면
'다시 주목받는' 강한 신호다. `dimensions=video`+`metrics=views`는 채널 소유자라면
비YPP(비수익화) 채널도 사용 가능 — trafficSource/isSubscriber 같은 YPP 전용 dimension이 아니다.

- 날짜는 KST 기준. 최근 윈도우 = [today-3-27, today-3] (T-3 지표 확정 반영).
- 생애 일평균은 video 테이블의 누적 조회수(`view`) / 업로드 후 경과일로 근사한다.
- Analytics 호출 실패/빈 응답이면 빈 리스트 → 카드 자연 skip (점수·다른 카드 영향 없음).
"""

import logging
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
FINALIZE_LAG = 3            # YouTube 지표 확정(T-3)
RECENT_WINDOW_DAYS = 28     # 최근 조회 윈도우
MIN_AGE_DAYS = 60           # 이보다 오래된 영상만 (역주행 = 옛날 영상)
MIN_RECENT_VIEWS = 100      # 최근 조회 노이즈 컷 (신뢰도 부족 영상 제외)
MIN_RATIO = 1.5             # 최근 일평균 / 생애 일평균 하한
MAX_RESULTS = 200           # Analytics 영상 행 상한


async def _fetch_recent_video_views(access_token: str, start: date, end: date) -> dict[str, int]:
    """최근 윈도우의 영상별 조회수 {youtube_video_id: views}. 실패 시 빈 dict."""
    url = (f"{ANALYTICS_URL}?ids=channel==MINE&startDate={start}&endDate={end}"
           f"&metrics=views&dimensions=video&sort=-views&maxResults={MAX_RESULTS}")
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    timeout = httpx.Timeout(connect=30.0, read=60.0, write=30.0, pool=30.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        logger.warning("[Dashboard] 역주행 조회수 수집 예외 - %r", e)
        return {}

    if resp.status_code != 200:
        logger.warning("[Dashboard] 역주행 조회수 수집 실패 %s: %.200s", resp.status_code, resp.text)
        return {}

    out: dict[str, int] = {}
    for row in resp.json().get("rows") or []:
        views = row[1] if len(row) > 1 else 0
        out[str(row[0])] = int(views) if isinstance(views, (int, float)) else 0
    return out


def _upload_date(v) -> Optional[date]:
    ud = getattr(v, "upload_date", None)
    if ud is None:
        return None
    return ud.date() if hasattr(ud, "date") else ud


async def detect_resurgent_videos(access_token: str, videos: list, today_kst: date) -> list[dict]:
    """역주행 후보를 비율(ratio) 내림차순으로 반환. 후보 없으면 [].

    각 후보 dict: {video, title, recent_views, total_views, age_days, ratio}.
    """
    end = today_kst - timedelta(days=FINALIZE_LAG)
    start = end - timedelta(days=RECENT_WINDOW_DAYS - 1)
    recent_views = await _fetch_recent_video_views(access_token, start, end)
    if not recent_views:
        return []

    candidates: list[dict] = []
    for v in videos:
        yid = getattr(v, "youtube_video_id", None)
        if not yid:
            continue
        recent = recent_views.get(yid, 0)
        if recent < MIN_RECENT_VIEWS:
            continue
        upload = _upload_date(v)
        if upload is None:
            continue
        age_days = (today_kst - upload).days
        if age_days < MIN_AGE_DAYS:
            continue  # 최근 영상은 '역주행'이 아니라 정상 신작 흐름
        total = getattr(v, "view", 0) or 0
        if total <= 0:
            continue

        lifetime_rate = total / age_days          # 생애 일평균 조회수
        recent_rate = recent / RECENT_WINDOW_DAYS  # 최근 일평균 조회수
        if lifetime_rate <= 0:
            continue
        ratio = recent_rate / lifetime_rate
        if ratio < MIN_RATIO:
            continue

        candidates.append({
            "video": v,
            "title": getattr(v, "title", "") or "",
            "recent_views": recent,
            "total_views": total,
            "age_days": age_days,
            "ratio": round(ratio, 1),
        })

    candidates.sort(key=lambda c: c["ratio"], reverse=True)
    if candidates:
        top = candidates[0]
        logger.info("[Dashboard] 역주행 후보 %d개 - top='%s' (age=%d일, 최근28일 %d뷰, 생애평균 대비 %.1f배)",
                    len(candidates), top["title"], top["age_days"], top["recent_views"], top["ratio"])
    else:
        logger.info("[Dashboard] 역주행 후보 없음 (조건: %d일+ 업로드 & 최근 %d뷰+ & %.1f배+)",
                    MIN_AGE_DAYS, MIN_RECENT_VIEWS, MIN_RATIO)
    return candidates
