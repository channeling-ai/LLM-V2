"""domain/report/service/report_service.py 단위 테스트

create_script_summary: 반환 타입 bool→list 변경, DB 쓰기 제거 검증.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from domain.report.service.report_service import ReportService


def _make_service():
    # ReportService 생성자가 DB/LLM 클라이언트를 직접 초기화하므로 patch로 차단
    with patch("domain.report.service.report_service.ContentChunkRepository"), \
         patch("domain.report.service.report_service.ReportRepository"), \
         patch("domain.report.service.report_service.TrendKeywordRepository"), \
         patch("domain.report.service.report_service.ChannelRepository"), \
         patch("domain.report.service.report_service.RagServiceImpl"):
        svc = ReportService()
    svc.rag_service = MagicMock()
    svc.content_chunk_repository = MagicMock()
    svc.report_repository = MagicMock()
    return svc


def _make_video(youtube_video_id="vid1"):
    v = MagicMock()
    v.youtube_video_id = youtube_video_id
    v.title = "Test"
    return v


class TestCreateScriptSummary:
    def setup_method(self):
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_raises_when_no_youtube_video_id(self):
        """youtube_video_id가 없으면 LLM 호출 전에 ValueError 발생"""
        video = _make_video(youtube_video_id=None)
        with pytest.raises(ValueError, match="YouTube 영상 ID가 없습니다"):
            await self.svc.create_script_summary(video, report_id=1)

    @pytest.mark.asyncio
    async def test_returns_list(self):
        """LLM 결과 그대로 list[dict] 반환 — bool이 아님"""
        video = _make_video()
        summary = [{"time": "0:00", "title": "인트로", "content": "내용"}]
        self.svc.rag_service.summarize_video = AsyncMock(return_value=summary)
        self.svc.content_chunk_repository.save_context = AsyncMock()

        result = await self.svc.create_script_summary(video, report_id=1, skip_vector_save=True)
        assert isinstance(result, list)
        assert result == summary

    @pytest.mark.asyncio
    async def test_vector_save_skipped_when_flag_true(self):
        """skip_vector_save=True → 벡터 DB 저장 호출 없음 (개발/테스트 환경 용도)"""
        video = _make_video()
        self.svc.rag_service.summarize_video = AsyncMock(
            return_value=[{"time": "0:00", "title": "A", "content": "B"}]
        )
        self.svc.content_chunk_repository.save_context = AsyncMock()

        await self.svc.create_script_summary(video, report_id=1, skip_vector_save=True)
        self.svc.content_chunk_repository.save_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_vector_save_called_when_flag_false(self):
        """skip_vector_save=False(기본값) → 벡터 DB 저장 1회 호출"""
        video = _make_video()
        summary = [{"time": "0:00", "title": "A", "content": "B"}]
        self.svc.rag_service.summarize_video = AsyncMock(return_value=summary)
        self.svc.content_chunk_repository.save_context = AsyncMock()

        await self.svc.create_script_summary(video, report_id=1, skip_vector_save=False)
        self.svc.content_chunk_repository.save_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_vector_save_not_called_when_empty_summary(self):
        """LLM이 빈 리스트를 반환하면 벡터 저장 생략 (저장할 내용 없음)"""
        video = _make_video()
        self.svc.rag_service.summarize_video = AsyncMock(return_value=[])
        self.svc.content_chunk_repository.save_context = AsyncMock()

        result = await self.svc.create_script_summary(video, report_id=1, skip_vector_save=False)
        assert result == []
        self.svc.content_chunk_repository.save_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_write_not_called(self):
        """PostgreSQL 저장(report_repository.save)이 이 서비스에서 호출되지 않음
        → DB 쓰기는 Spring이 Kafka 결과 메시지 수신 후 처리하는 방식으로 이관됨"""
        video = _make_video()
        self.svc.rag_service.summarize_video = AsyncMock(
            return_value=[{"time": "0:00", "title": "A", "content": "B"}]
        )
        self.svc.content_chunk_repository.save_context = AsyncMock()
        self.svc.report_repository.save = AsyncMock()

        await self.svc.create_script_summary(video, report_id=1)
        self.svc.report_repository.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_propagates_rag_exception(self):
        """LLM/RAG 서비스 예외는 try-catch 없이 그대로 상위로 전파"""
        video = _make_video()
        self.svc.rag_service.summarize_video = AsyncMock(side_effect=RuntimeError("LLM 오류"))

        with pytest.raises(RuntimeError, match="LLM 오류"):
            await self.svc.create_script_summary(video, report_id=1)
