import logging
from typing import Dict, Optional

from fastapi import APIRouter

from domain.report.dto.dummy_report_dto import Cost, DummyReportRequest, VideoInfo
from domain.report.service.recommend_generator import RecommendGenerator
from external.youtube.video_detail_service import VideoDetailService
from response.api_response import ApiResponse
from response.code.status.success_status import SuccessStatus

router = APIRouter(tags=["dummy-report"])

logger = logging.getLogger(__name__)

recommend_generator = RecommendGenerator()
video_detail_service = VideoDetailService()

# 일반 리포트와 동일한 롱폼/숏폼 규칙: 카테고리 42(Shorts)만 숏폼, 나머지는 전부 롱폼
SHORTS_CATEGORY_ID = "42"


@router.post("/dummy-report")
async def create_dummy_report(req: DummyReportRequest):
    """
    체험용 더미 리포트 생성 — 추천 리포트와 동일한 본문을 동기(blocking)로 조립해 즉시 반환한다.
    Kafka를 쓰지 않는 이유는 Spring이 동기 응답을 기다리기 때문(설계 문서 참고).
    저장은 하지 않는다 — 캐싱은 Spring 책임.
    """
    result = await recommend_generator.generate(req.youtube_video_id)

    payload = result.model_dump(by_alias=True)
    payload["video"] = (await _build_video_info(req.youtube_video_id)).model_dump()
    payload["cost"] = Cost().model_dump()

    return ApiResponse.on_success(SuccessStatus._OK, payload)


async def _build_video_info(youtube_video_id: str) -> VideoInfo:
    """
    체험 화면에 띄울 영상 메타. get_video_details는 Redis 5분 캐시라
    직전 generate()가 이미 채워둔 값을 재사용한다 (캐시 장애 시에만 API 1회 추가).
    메타 실패가 리포트 본문을 날리면 안 되므로 예외는 삼키고 빈 값으로 둔다.
    """
    try:
        details = await video_detail_service.get_video_details(youtube_video_id)
    except Exception:
        logger.warning("더미 리포트 영상 메타 조회 실패 - videoId: %s", youtube_video_id, exc_info=True)
        return VideoInfo()

    if not details:
        return VideoInfo()

    return VideoInfo(
        video_title=details.get("title"),
        video_thumbnail_url=_pick_thumbnail(details.get("thumbnails", {})),
        video_type="SHORTS" if details.get("categoryId") == SHORTS_CATEGORY_ID else "LONG",
        video_created_date=_to_local_datetime(details.get("publishedAt")),
        channel_name=details.get("channelTitle"),
    )


def _pick_thumbnail(thumbnails: Dict) -> Optional[str]:
    """Spring의 YoutubeApiKeyUtil.thumb()과 동일한 우선순위."""
    for quality in ("high", "medium", "default"):
        url = thumbnails.get(quality, {}).get("url")
        if url:
            return url
    return None


def _to_local_datetime(published_at: Optional[str]) -> Optional[str]:
    """
    YouTube의 RFC3339(...Z)를 Spring LocalDateTime이 읽는 형식으로 맞춘다.
    Spring은 OffsetDateTime.parse(iso).toLocalDateTime()으로 오프셋을 버리므로,
    여기서도 UTC 벽시계를 그대로 두고 오프셋 표기만 제거해 같은 값이 되게 한다.
    """
    if not published_at:
        return None
    return published_at.removesuffix("Z")
