"""domain/report/controller/dummy_report_controller.py 단위 테스트

체험용 더미 리포트 엔드포인트의 계약 검증:
BE가 파싱하는 4개 blob + cost 필드가 동기 응답에 들어있는지.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_VIDEO_DETAILS = {
    "title": "제목", "description": "설명",
    "viewCount": 1234, "likeCount": 56, "commentCount": 78,
}

_COMMENT_ANALYSIS = {
    "positive_pct": 25.0, "negative_pct": 25.0, "neutral_pct": 25.0, "advice_pct": 25.0,
    "positive_count": 1, "negative_count": 1, "neutral_count": 1, "advice_count": 1,
    "total_comment_count": 100,
    "representative_comments": [
        {"category": "positive", "content": "좋아요", "author": "a",
         "published_at": "2026-01-01T00:00:00Z", "like_count": 3}
    ],
    "category_summaries": {"positive": "", "negative": "", "neutral": "", "advice": ""},
}


def _generator_with_mocks(details=None):
    from domain.report.service.recommend_generator import RecommendGenerator

    gen = RecommendGenerator(
        report_service=MagicMock(), comment_service=MagicMock(), video_detail_service=MagicMock()
    )
    gen.video_detail_service.get_video_details = AsyncMock(
        return_value=details if details is not None else _VIDEO_DETAILS
    )
    gen.report_service.create_script_summary = AsyncMock(
        return_value=[{"time": "0:00", "title": "A", "content": "B"}]
    )
    gen.report_service.analyze_optimization = AsyncMock(
        return_value={"categoryList": [], "additionalSuggestions": []}
    )
    gen.comment_service.analyze_comments = AsyncMock(return_value=_COMMENT_ANALYSIS)
    return gen


@pytest.mark.asyncio
async def test_returns_four_blobs_and_cost():
    """BE 계약 — result에 4개 blob + cost가 모두 있어야 한다"""
    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest

    with patch.object(ctrl, "recommend_generator", _generator_with_mocks()):
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    assert res["isSuccess"] is True
    result = res["result"]
    assert set(result) >= {"summary", "comment_analysis", "metrics", "algorithm_optimization", "cost"}
    assert result["metrics"] == {"view": 1234, "like_count": 56, "comment_count": 78}
    # Step 1에서는 비용 미집계 — 0으로 내려보내고 BE는 무시한다
    assert result["cost"] == {"input_tokens": 0, "output_tokens": 0, "usd": 0.0}


@pytest.mark.asyncio
async def test_video_details_missing_raises():
    """영상 상세 조회 실패는 그대로 전파 → FastAPI 500 → BE가 502로 변환, 캐시하지 않음"""
    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest

    with patch.object(ctrl, "recommend_generator", _generator_with_mocks(details={})):
        with pytest.raises(ValueError):
            await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))


@pytest.mark.asyncio
async def test_blank_video_id_raises():
    from domain.report.service.recommend_generator import RecommendGenerator

    gen = RecommendGenerator(
        report_service=MagicMock(), comment_service=MagicMock(), video_detail_service=MagicMock()
    )
    with pytest.raises(ValueError):
        await gen.generate("")
