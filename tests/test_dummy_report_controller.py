"""domain/report/controller/dummy_report_controller.py 단위 테스트

체험용 더미 리포트 엔드포인트의 계약 검증:
BE가 파싱하는 4개 blob + cost 필드가 동기 응답에 들어있는지.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_VIDEO_DETAILS = {
    "title": "제목", "description": "설명",
    "viewCount": 1234, "likeCount": 56, "commentCount": 78,
    "categoryId": "22",
    "publishedAt": "2026-01-02T03:04:05Z",
    "channelTitle": "채널",
    "thumbnails": {
        "default": {"url": "https://d"},
        "medium": {"url": "https://m"},
        "high": {"url": "https://h"},
    },
}


def _patch_video_meta(details=None):
    """컨트롤러가 영상 메타용으로 따로 호출하는 서비스 — 테스트에서 실제 API를 타지 않게 막는다."""
    from domain.report.controller import dummy_report_controller as ctrl

    stub = MagicMock()
    stub.get_video_details = AsyncMock(
        return_value=details if details is not None else _VIDEO_DETAILS
    )
    return patch.object(ctrl, "video_detail_service", stub)

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
        report_service=MagicMock(), comment_service=MagicMock(),
        video_detail_service=MagicMock(), rag_service=MagicMock(),
    )
    gen.rag_service.generate_overview_summary = AsyncMock(
        return_value={"title": "진정성 있는 콘텐츠", "content": "댓글 반응이 좋아요.", "tag": "무시됨"}
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

    with patch.object(ctrl, "recommend_generator", _generator_with_mocks()), _patch_video_meta():
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    assert res["isSuccess"] is True
    result = res["result"]
    assert set(result) >= {"summary", "comment_analysis", "metrics", "algorithm_optimization",
                           "overview_summary", "video", "cost"}
    assert result["metrics"] == {"view": 1234, "like_count": 56, "comment_count": 78}
    # Step 1에서는 비용 미집계 — 0으로 내려보내고 BE는 무시한다
    assert result["cost"] == {"input_tokens": 0, "output_tokens": 0, "usd": 0.0}


@pytest.mark.asyncio
async def test_video_details_missing_raises():
    """영상 상세 조회 실패는 그대로 전파 → FastAPI 500 → BE가 502로 변환, 캐시하지 않음"""
    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest

    with patch.object(ctrl, "recommend_generator", _generator_with_mocks(details={})), _patch_video_meta():
        with pytest.raises(ValueError):
            await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))


@pytest.mark.asyncio
async def test_video_meta_matches_be_contract():
    """BE 계약 — DummyReportResDTO.VideoInfo가 읽는 snake_case 키와 값 규칙"""
    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest

    with patch.object(ctrl, "recommend_generator", _generator_with_mocks()), _patch_video_meta():
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    assert res["result"]["video"] == {
        "video_title": "제목",
        "video_thumbnail_url": "https://h",   # high > medium > default
        "video_type": "LONG",                  # categoryId 22 → 롱폼
        "video_created_date": "2026-01-02T03:04:05",  # Z 제거, Spring LocalDateTime용
        "channel_name": "채널",
    }


@pytest.mark.asyncio
async def test_shorts_category_is_shorts():
    """롱폼/숏폼은 재생시간이 아니라 카테고리 42 기준 (일반 리포트와 동일 규칙)"""
    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest

    shorts = {**_VIDEO_DETAILS, "categoryId": "42"}
    with patch.object(ctrl, "recommend_generator", _generator_with_mocks()), _patch_video_meta(shorts):
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    assert res["result"]["video"]["video_type"] == "SHORTS"


@pytest.mark.asyncio
async def test_video_meta_failure_does_not_break_report():
    """메타 조회가 실패해도 리포트 본문은 그대로 나가야 한다 (BE는 video=null로 처리)"""
    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest

    stub = MagicMock()
    stub.get_video_details = AsyncMock(side_effect=RuntimeError("quota exceeded"))

    with patch.object(ctrl, "recommend_generator", _generator_with_mocks()), \
            patch.object(ctrl, "video_detail_service", stub):
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    assert res["isSuccess"] is True
    assert res["result"]["video"]["video_title"] is None
    assert res["result"]["summary"]  # 본문은 유지


@pytest.mark.asyncio
async def test_overview_summary_tag_follows_positive_pct_not_llm():
    """일반 리포트와 동일 규칙 — tag는 LLM 응답이 아니라 positive_pct(>=50)로 결정한다"""
    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest

    gen = _generator_with_mocks()
    # 긍정 25% → LLM이 뭐라 하든 '부정'
    with patch.object(ctrl, "recommend_generator", gen), _patch_video_meta():
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    summary = res["result"]["overview_summary"]
    assert summary["title"] == "진정성 있는 콘텐츠"
    assert summary["tag"] == "부정"

    positive = {**_COMMENT_ANALYSIS, "positive_pct": 60.0}
    gen.comment_service.analyze_comments = AsyncMock(return_value=positive)
    with patch.object(ctrl, "recommend_generator", gen), _patch_video_meta():
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    assert res["result"]["overview_summary"]["tag"] == "긍정"


@pytest.mark.asyncio
async def test_overview_summary_failure_does_not_break_report():
    """요약 LLM 호출이 실패해도 리포트 본문은 그대로 나가야 한다 (빈 요약으로 대체)"""
    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest

    gen = _generator_with_mocks()
    gen.rag_service.generate_overview_summary = AsyncMock(side_effect=RuntimeError("LLM down"))

    with patch.object(ctrl, "recommend_generator", gen), _patch_video_meta():
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    assert res["isSuccess"] is True
    assert res["result"]["overview_summary"] == {"title": "", "content": "", "tag": "부정"}
    assert res["result"]["summary"]  # 본문은 유지


@pytest.mark.asyncio
async def test_blank_video_id_raises():
    from domain.report.service.recommend_generator import RecommendGenerator

    gen = RecommendGenerator(
        report_service=MagicMock(), comment_service=MagicMock(),
        video_detail_service=MagicMock(), rag_service=MagicMock(),
    )
    with pytest.raises(ValueError):
        await gen.generate("")
