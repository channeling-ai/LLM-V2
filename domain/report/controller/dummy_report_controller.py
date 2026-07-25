import logging

from fastapi import APIRouter

from domain.report.dto.dummy_report_dto import Cost, DummyReportRequest
from domain.report.service.recommend_generator import RecommendGenerator
from response.api_response import ApiResponse
from response.code.status.success_status import SuccessStatus

router = APIRouter(tags=["dummy-report"])

logger = logging.getLogger(__name__)

recommend_generator = RecommendGenerator()


@router.post("/dummy-report")
async def create_dummy_report(req: DummyReportRequest):
    """
    체험용 더미 리포트 생성 — 추천 리포트와 동일한 본문을 동기(blocking)로 조립해 즉시 반환한다.
    Kafka를 쓰지 않는 이유는 Spring이 동기 응답을 기다리기 때문(설계 문서 참고).
    저장은 하지 않는다 — 캐싱은 Spring 책임.
    """
    result = await recommend_generator.generate(req.youtube_video_id)

    payload = result.model_dump(by_alias=True)
    payload["cost"] = Cost().model_dump()

    return ApiResponse.on_success(SuccessStatus._OK, payload)
