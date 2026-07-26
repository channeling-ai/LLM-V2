"""콘텐츠 효율 불균형 탐지 — CONTENT_EFFICIENCY suggestion 카드 입력.

YouTube Analytics(`dimensions=video`)로 영상별 조회수·구독전환수를 받아, 저장된
`video_category`(§AI_CONTEXT_INSIGHT_SPEC.md 시나리오2)와 조인해 카테고리별로 집계한다.
"조회수를 제일 많이 끄는 카테고리"와 "구독전환을 제일 많이 만드는 카테고리"가 다르고
그 격차가 유의미할 때만 "불균형"으로 판단한다.

- subscribersGained는 views와 같은 CORE 리포트라 viral_detector와 동일하게 비YPP도 가능
  (2026-07-20 channel_id=1 실제 API 호출로 검증 완료).
- 카테고리는 버킷화(브이로그류/튜토리얼류 등)하지 않고 YouTube 원본 대분류를 그대로 비교한다
  — 하드코딩되는 매핑이 없어 더 일반적이다(버킷화는 PM 결정 대기, 별도 이슈로 남김).
"""

import logging
from datetime import date, timedelta
from typing import Optional

import httpx

from core.enums.video_category import VideoCategory

logger = logging.getLogger(__name__)

ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
FINALIZE_LAG = 3                 # YouTube 지표 확정(T-3), 다른 탐지기와 동일 기준
WINDOW_DAYS = 180                # 구조적 진단이라 역주행(28일)보다 긴 누적 창
MIN_TOTAL_VIEWS = 100            # 창 전체 조회수 하한 (engagement·viral과 동일 기준선)
MIN_TOTAL_SUBS_GAINED = 1        # 구독전환이 0이면 비교 자체가 무의미
MIN_VIDEOS_PER_CATEGORY = 2      # 영상 1개로 카테고리 대표하지 않도록
MIN_CATEGORIES = 2               # 비교 대상 카테고리 최소 2개
SHARE_GAP_THRESHOLD = 0.15       # view_share/sub_share 격차 하한(15%p) — 이하면 노이즈로 간주
MAX_RESULTS = 200

_CATEGORY_LABELS = {
    VideoCategory.FILM_AND_ANIMATION: "영화/애니메이션",
    VideoCategory.AUTOS_AND_VEHICLES: "자동차",
    VideoCategory.MUSIC: "음악",
    VideoCategory.PETS_AND_ANIMALS: "동물",
    VideoCategory.SPORTS: "스포츠",
    VideoCategory.TRAVEL_AND_EVENTS: "여행/이벤트",
    VideoCategory.GAMING: "게임",
    VideoCategory.VIDEOBLOGGING: "브이로그",
    VideoCategory.PEOPLE_AND_BLOGS: "일상/블로그",
    VideoCategory.COMEDY: "코미디",
    VideoCategory.ENTERTAINMENT: "엔터테인먼트",
    VideoCategory.NEWS_AND_POLITICS: "뉴스/정치",
    VideoCategory.HOWTO_AND_STYLE: "하우투/스타일",
    VideoCategory.EDUCATION: "교육/튜토리얼",
    VideoCategory.SCIENCE_AND_TECHNOLOGY: "과학기술",
}


def _category_label(cat: VideoCategory) -> str:
    return _CATEGORY_LABELS.get(cat, cat.name)


async def _fetch_video_views_and_subs(access_token: str, start: date, end: date) -> dict[str, tuple[int, int]]:
    """윈도우의 영상별 (views, subscribersGained) {youtube_video_id: (views, subs)}. 실패 시 빈 dict."""
    url = (f"{ANALYTICS_URL}?ids=channel==MINE&startDate={start}&endDate={end}"
           f"&metrics=views,subscribersGained&dimensions=video&sort=-views&maxResults={MAX_RESULTS}")
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    timeout = httpx.Timeout(connect=30.0, read=60.0, write=30.0, pool=30.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        logger.warning("[Dashboard] 콘텐츠효율 조회수/구독전환 수집 예외 - %r", e)
        return {}

    if resp.status_code != 200:
        logger.warning("[Dashboard] 콘텐츠효율 조회수/구독전환 수집 실패 %s: %.200s", resp.status_code, resp.text)
        return {}

    out: dict[str, tuple[int, int]] = {}
    for row in resp.json().get("rows") or []:
        vid = str(row[0])
        views = int(row[1]) if len(row) > 1 and isinstance(row[1], (int, float)) else 0
        subs = int(row[2]) if len(row) > 2 and isinstance(row[2], (int, float)) else 0
        out[vid] = (views, subs)
    return out


def _upload_date(v) -> Optional[date]:
    ud = getattr(v, "upload_date", None)
    if ud is None:
        return None
    return ud.date() if hasattr(ud, "date") else ud


async def detect_content_imbalance(access_token: str, videos: list, today_kst: date) -> Optional[dict]:
    """콘텐츠 효율 불균형 후보를 반환. 없거나 판단 불가면 None.

    반환 dict: {view_leader: {category, label, views, view_share},
                sub_leader: {category, label, subs, sub_share}}
    """
    end = today_kst - timedelta(days=FINALIZE_LAG)
    start = end - timedelta(days=WINDOW_DAYS - 1)
    metrics = await _fetch_video_views_and_subs(access_token, start, end)
    if not metrics:
        logger.info("[Dashboard] 콘텐츠효율 - Analytics 응답 없음 → 카드 skip")
        return None

    # 카테고리별 집계
    agg: dict[VideoCategory, dict] = {}
    for v in videos:
        yid = getattr(v, "youtube_video_id", None)
        cat = getattr(v, "video_category", None)
        if not yid or cat is None:
            continue
        views, subs = metrics.get(yid, (0, 0))
        if views <= 0 and subs <= 0:
            continue
        bucket = agg.setdefault(cat, {"views": 0, "subs": 0, "count": 0})
        bucket["views"] += views
        bucket["subs"] += subs
        bucket["count"] += 1

    total_views = sum(b["views"] for b in agg.values())
    total_subs = sum(b["subs"] for b in agg.values())

    if total_views < MIN_TOTAL_VIEWS:
        logger.info("[Dashboard] 콘텐츠효율 - 창(%d일) 총 조회수 %d < %d → 카드 skip",
                    WINDOW_DAYS, total_views, MIN_TOTAL_VIEWS)
        return None
    if total_subs < MIN_TOTAL_SUBS_GAINED:
        logger.info("[Dashboard] 콘텐츠효율 - 창(%d일) 총 구독전환 %d < %d → 카드 skip",
                    WINDOW_DAYS, total_subs, MIN_TOTAL_SUBS_GAINED)
        return None

    # 표본 부족 카테고리 제외
    categories = {cat: b for cat, b in agg.items() if b["count"] >= MIN_VIDEOS_PER_CATEGORY}
    if len(categories) < MIN_CATEGORIES:
        logger.info("[Dashboard] 콘텐츠효율 - 비교 가능 카테고리 %d개(%d개 필요, 영상 %d개 미만 카테고리 제외) → 카드 skip",
                    len(categories), MIN_CATEGORIES, MIN_VIDEOS_PER_CATEGORY)
        return None

    shares = {
        cat: {
            "views": b["views"],
            "subs": b["subs"],
            "count": b["count"],
            "view_share": b["views"] / total_views if total_views else 0.0,
            "sub_share": b["subs"] / total_subs if total_subs else 0.0,
        }
        for cat, b in categories.items()
    }

    view_leader_cat = max(shares, key=lambda c: shares[c]["view_share"])
    sub_leader_cat = max(shares, key=lambda c: shares[c]["sub_share"])

    if view_leader_cat == sub_leader_cat:
        logger.info("[Dashboard] 콘텐츠효율 - 조회수/구독전환 견인 카테고리 동일(%s) → 불균형 아님, 카드 skip",
                    _category_label(view_leader_cat))
        return None

    view_leader = shares[view_leader_cat]
    sub_leader = shares[sub_leader_cat]
    gap_view = view_leader["view_share"] - view_leader["sub_share"]
    gap_sub = sub_leader["sub_share"] - sub_leader["view_share"]

    if gap_view < SHARE_GAP_THRESHOLD or gap_sub < SHARE_GAP_THRESHOLD:
        logger.info(
            "[Dashboard] 콘텐츠효율 - 격차 미미(조회수쪽 %.1f%%p, 구독전환쪽 %.1f%%p, 기준 %.0f%%p) → 카드 skip",
            gap_view * 100, gap_sub * 100, SHARE_GAP_THRESHOLD * 100,
        )
        return None

    logger.info(
        "[Dashboard] 콘텐츠효율 불균형 감지 - 조회수견인=%s(%.0f%%) 구독전환견인=%s(%.0f%%)",
        _category_label(view_leader_cat), view_leader["view_share"] * 100,
        _category_label(sub_leader_cat), sub_leader["sub_share"] * 100,
    )
    return {
        "view_leader": {
            "category": view_leader_cat, "label": _category_label(view_leader_cat),
            "views": view_leader["views"], "view_share": view_leader["view_share"],
            "sub_share": view_leader["sub_share"],
        },
        "sub_leader": {
            "category": sub_leader_cat, "label": _category_label(sub_leader_cat),
            "subs": sub_leader["subs"], "sub_share": sub_leader["sub_share"],
            "view_share": sub_leader["view_share"],
        },
    }
