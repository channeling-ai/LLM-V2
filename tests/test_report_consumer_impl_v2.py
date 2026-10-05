"""domain/report/service/report_consumer_impl_v2.py 단위 테스트

handle_overview_v2 / handle_analysis_v2 의 Kafka 발행 흐름 검증.
핵심 불변식: 성공이든 실패든 항상 정확히 1개의 Kafka 메시지가 발행되어야 함.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def _make_consumer():
    # 생성자에서 DB/Kafka/외부 서비스를 초기화하므로 전부 patch
    with patch("domain.report.service.report_consumer_impl_v2.RagServiceImpl"), \
         patch("domain.report.service.report_consumer_impl_v2.VideoRepository"), \
         patch("domain.report.service.report_consumer_impl_v2.ReportRepository"), \
         patch("domain.report.service.report_consumer_impl_v2.ContentChunkRepository"), \
         patch("domain.report.service.report_consumer_impl_v2.ChannelRepository"), \
         patch("domain.report.service.report_consumer_impl_v2.CommentService"), \
         patch("domain.report.service.report_consumer_impl_v2.ReportService"), \
         patch("domain.report.service.report_consumer_impl_v2.TrendKeywordRepository"), \
         patch("domain.report.service.report_consumer_impl_v2.IdeaService"), \
         patch("domain.report.service.report_consumer_impl_v2.VideoService"), \
         patch("domain.report.service.report_consumer_impl_v2.RedisService"), \
         patch("domain.report.service.report_consumer_impl_v2.kafka_broker") as mock_broker:
        from domain.report.service.report_consumer_impl_v2 import ReportConsumerImplV2
        broker = MagicMock()
        consumer = ReportConsumerImplV2(broker)
        consumer._mock_broker = mock_broker
    return consumer


def _attach_mocks(consumer):
    """report/video 조회 성공 케이스용 공통 Mock — report.id=10"""
    report = MagicMock()
    report.id = 10
    video = MagicMock()
    video.youtube_video_id = "vid1"
    video.channel_id = 1

    consumer.report_repository = MagicMock()
    consumer.report_repository.find_by_id = AsyncMock(return_value=report)
    consumer.video_repository = MagicMock()
    consumer.video_repository.find_by_id = AsyncMock(return_value=video)

    return report, video


# 정상 overview 메시지 기본값
BASE_OVERVIEW_MSG = {
    "task_id": 1,
    "report_id": 10,
    "google_access_token": "token",
    "skip_vector_save": False,
    "start_date": None,
    "end_date": None,
    "previous_report_id": None,
}

# 테스트용 기본 comment_analysis dict (Kafka DTO CommentAnalysis 필드와 동일)
_BASE_COMMENT_ANALYSIS = {
    "positive_pct": 60, "negative_pct": 20, "neutral_pct": 10, "advice_pct": 10,
    "positive_count": 60, "negative_count": 20, "neutral_count": 10, "advice_count": 10,
    "total_comment_count": 100,
    "representative_comments": [],
    "category_summaries": {"positive": "", "negative": "", "neutral": "", "advice": ""},
}

# 테스트용 기본 metrics dict (Kafka DTO Metrics 필드와 동일)
_BASE_METRICS = {
    "view": 1000, "view_channel_avg": 500.0,
    "like_count": 50, "like_channel_avg": 30.0,
    "comment_count": 20, "comment_channel_avg": 10.0,
    "concept": 80.0, "seo": 75.0, "revisit": 5.0,
}


def _attach_overview_mocks(consumer, comment_analysis=None, metrics=None,
                            summary=None, overview_raw=None, seo_raw=None):
    """handle_overview_v2 정상 동작에 필요한 서비스 Mock 일괄 설정"""
    consumer.report_service = MagicMock()
    consumer.report_service.create_script_summary = AsyncMock(return_value=summary or [])
    consumer.comment_service = MagicMock()
    consumer.comment_service.analyze_comments = AsyncMock(
        return_value=comment_analysis or _BASE_COMMENT_ANALYSIS
    )
    consumer.video_service = MagicMock()
    consumer.video_service.analyze_metrics = AsyncMock(
        return_value=metrics or _BASE_METRICS
    )
    consumer.rag_service = MagicMock()
    consumer.rag_service.generate_overview_summary = AsyncMock(
        return_value=overview_raw or {"title": "", "content": ""}
    )
    consumer.rag_service.generate_seo_summary = AsyncMock(
        return_value=seo_raw or {"title": "", "content": ""}
    )


async def _run_overview(consumer, msg=None):
    """kafka_broker를 가로채서 발행된 메시지 목록을 반환"""
    published = []

    async def fake_publish(message, topic, key=None):
        published.append((message, topic))

    with patch("domain.report.service.report_consumer_impl_v2.kafka_broker") as mock_broker:
        mock_broker.publish = fake_publish
        await consumer.handle_overview_v2(msg or BASE_OVERVIEW_MSG)

    return published


# ────────────────────────────────────────────────────────────
# handle_overview_v2 — 성공/실패 Kafka 발행 흐름
# ────────────────────────────────────────────────────────────

class TestHandleOverviewV2:
    def setup_method(self):
        self.consumer = _make_consumer()

    @pytest.mark.asyncio
    async def test_success_publishes_is_success_true(self):
        """3개 병렬 프로세스(요약·댓글·수치) + LLM 요약 모두 성공 → is_success=True 발행"""
        _attach_mocks(self.consumer)
        _attach_overview_mocks(
            self.consumer,
            summary=[{"time": "0:00", "title": "A", "content": "B"}],
            overview_raw={"title": "요약제목", "content": "요약내용"},
            seo_raw={"title": "SEO제목", "content": "SEO내용"},
        )

        published = await _run_overview(self.consumer)

        assert len(published) == 1
        msg, topic = published[0]
        assert msg.is_success is True
        assert msg.report_id == 10
        assert msg.task_id == 1

    @pytest.mark.asyncio
    async def test_failure_publishes_is_success_false(self):
        """3개 병렬 프로세스 중 하나(create_script_summary)가 실패 → is_success=False 발행
        실패 메시지도 반드시 1개 발행되어야 Spring이 상태를 알 수 있음"""
        _attach_mocks(self.consumer)
        self.consumer.report_service = MagicMock()
        # 스크립트 요약 실패 시뮬레이션
        self.consumer.report_service.create_script_summary = AsyncMock(
            side_effect=RuntimeError("요약 실패")
        )
        self.consumer.comment_service = MagicMock()
        self.consumer.comment_service.analyze_comments = AsyncMock(return_value={})
        self.consumer.video_service = MagicMock()
        self.consumer.video_service.analyze_metrics = AsyncMock(return_value={})

        published = await _run_overview(self.consumer)

        assert len(published) == 1
        msg, _ = published[0]
        assert msg.is_success is False
        assert msg.report_id == BASE_OVERVIEW_MSG["report_id"]

    @pytest.mark.asyncio
    async def test_missing_report_raises_and_publishes_failure(self):
        """DB에 report가 없으면 ValueError → is_success=False 발행"""
        # report 조회 실패 케이스 (find_by_id가 None 반환)
        self.consumer.report_repository = MagicMock()
        self.consumer.report_repository.find_by_id = AsyncMock(return_value=None)

        published = await _run_overview(self.consumer)

        assert len(published) == 1
        assert published[0][0].is_success is False

    @pytest.mark.asyncio
    async def test_positive_pct_below_50_uses_negative_tag(self):
        """긍정 댓글 비율 < 50% → OverviewTag.NEGATIVE('부정') 태그 결정
        태그는 LLM이 아닌 규칙 기반: positive_pct >= 50 이면 긍정, 아니면 부정"""
        _attach_mocks(self.consumer)
        _attach_overview_mocks(
            self.consumer,
            comment_analysis={**_BASE_COMMENT_ANALYSIS, "positive_pct": 40},  # < 50
            metrics={**_BASE_METRICS, "seo": 65.0},
        )

        published = await _run_overview(self.consumer)

        assert published[0][0].result.overview_summary.tag == "부정"

    @pytest.mark.asyncio
    async def test_seo_below_70_uses_needs_optimization_tag(self):
        """SEO 점수 < 70 → SeoTag.NEEDS_OPTIMIZATION('최적화 필요') 태그 결정
        태그 기준: seo >= 70 이면 '최적화 원할', 아니면 '최적화 필요'"""
        _attach_mocks(self.consumer)
        _attach_overview_mocks(
            self.consumer,
            metrics={**_BASE_METRICS, "seo": 50.0},  # < 70
        )

        published = await _run_overview(self.consumer)

        assert published[0][0].result.seo_summary.tag == "최적화 필요"

    @pytest.mark.asyncio
    async def test_summary_generation_failure_still_publishes_success(self):
        """overview_summary / seo_summary LLM 호출 실패 → is_success=True로 발행 유지
        LLM 요약 실패는 에러 로깅 후 빈 title/content로 대체, 태그는 규칙 기반으로 유지"""
        _attach_mocks(self.consumer)
        _attach_overview_mocks(self.consumer)
        # LLM 요약 생성만 실패 시뮬레이션
        self.consumer.rag_service.generate_overview_summary = AsyncMock(
            side_effect=RuntimeError("LLM 타임아웃")
        )
        self.consumer.rag_service.generate_seo_summary = AsyncMock(
            side_effect=RuntimeError("LLM 타임아웃")
        )

        published = await _run_overview(self.consumer)

        assert len(published) == 1
        msg = published[0][0]
        assert msg.is_success is True
        # LLM 실패 → 빈 문자열 fallback
        assert msg.result.overview_summary.title == ""
        assert msg.result.overview_summary.content == ""
        assert msg.result.seo_summary.title == ""
        assert msg.result.seo_summary.content == ""


# ────────────────────────────────────────────────────────────
# handle_analysis_v2 — 시청자 이탈 분석 + 알고리즘 최적화 분석
# ────────────────────────────────────────────────────────────

class TestHandleAnalysisV2:
    def setup_method(self):
        self.consumer = _make_consumer()

    @pytest.mark.asyncio
    async def test_success_publishes_is_success_true(self):
        """시청자 이탈 분석 + 알고리즘 최적화 분석 모두 성공 → is_success=True 발행"""
        _attach_mocks(self.consumer)
        self.consumer.report_service = MagicMock()
        self.consumer.report_service.analyze_viewer_retention = AsyncMock(return_value=True)
        self.consumer.report_service.analyze_optimization = AsyncMock(return_value=True)

        published = []

        async def fake_publish(message, topic, key=None):
            published.append((message, topic))

        msg_input = {
            "task_id": 2, "report_id": 10,
            "google_access_token": "token",
            "skip_vector_save": False,
            "start_date": None, "end_date": None,
        }

        with patch("domain.report.service.report_consumer_impl_v2.kafka_broker") as mock_broker:
            mock_broker.publish = fake_publish
            await self.consumer.handle_analysis_v2(msg_input)

        assert len(published) == 1
        msg, _ = published[0]
        assert msg.is_success is True

    @pytest.mark.asyncio
    async def test_failure_publishes_is_success_false(self):
        """analyze_viewer_retention 실패 → analyze_optimization은 호출되지 않고 is_success=False 발행"""
        _attach_mocks(self.consumer)
        self.consumer.report_service = MagicMock()
        self.consumer.report_service.analyze_viewer_retention = AsyncMock(
            side_effect=RuntimeError("분석 실패")
        )
        self.consumer.report_service.analyze_optimization = AsyncMock()

        published = []

        async def fake_publish(message, topic, key=None):
            published.append((message, topic))

        msg_input = {
            "task_id": 2, "report_id": 10,
            "google_access_token": "token",
            "skip_vector_save": False,
        }

        with patch("domain.report.service.report_consumer_impl_v2.kafka_broker") as mock_broker:
            mock_broker.publish = fake_publish
            await self.consumer.handle_analysis_v2(msg_input)

        assert len(published) == 1
        assert published[0][0].is_success is False


# ────────────────────────────────────────────────────────────
# handle_recommend_v2 — 추천 리포트 (토큰 없이 생성, 유저 무관)
# ────────────────────────────────────────────────────────────

_BASE_VIDEO_DETAILS = {
    "title": "제목", "description": "설명",
    "viewCount": 1234, "likeCount": 56, "commentCount": 78,
}

BASE_RECOMMEND_MSG = {
    "recommend_report_id": 5,
    "user_id": 7,
    "youtube_video_id": "vid1",
}


class TestHandleRecommendV2:
    def setup_method(self):
        self.consumer = _make_consumer()

    def _attach_recommend_mocks(self, details=None):
        # 본문 조립은 RecommendGenerator에 위임되므로 generator가 든 참조를 갈아끼운다
        gen = self.consumer.recommend_generator
        gen.video_detail_service = MagicMock()
        gen.video_detail_service.get_video_details = AsyncMock(
            return_value=details if details is not None else _BASE_VIDEO_DETAILS
        )
        gen.report_service = MagicMock()
        gen.report_service.create_script_summary = AsyncMock(
            return_value=[{"time": "0:00", "title": "A", "content": "B"}]
        )
        gen.report_service.analyze_optimization = AsyncMock(
            return_value={"categoryList": [], "additionalSuggestions": []}
        )
        gen.comment_service = MagicMock()
        gen.comment_service.analyze_comments = AsyncMock(
            return_value=_BASE_COMMENT_ANALYSIS
        )
        gen.rag_service = MagicMock()
        gen.rag_service.generate_overview_summary = AsyncMock(
            return_value={"title": "제목", "content": "내용", "tag": "무시됨"}
        )

    async def _run(self, msg=None):
        published = []

        async def fake_publish(message, topic, key=None):
            published.append((message, topic))

        with patch("domain.report.service.report_consumer_impl_v2.kafka_broker") as mock_broker:
            mock_broker.publish = fake_publish
            await self.consumer.handle_recommend_v2(msg or BASE_RECOMMEND_MSG)

        return published

    @pytest.mark.asyncio
    async def test_success_publishes_result_with_public_metrics(self):
        """요약+댓글+지표+최적화 조립 성공 → is_success=True, 공개 지표만 포함(토큰 미사용)"""
        self._attach_recommend_mocks()

        published = await self._run()

        assert len(published) == 1
        msg, topic = published[0]
        assert topic == "recommend-report-result-v2"
        assert msg.is_success is True
        assert msg.recommend_report_id == 5
        assert msg.user_id == 7
        # 공개 지표는 video_detail에서 직접 — view/like/comment
        assert msg.result["metrics"] == {"view": 1234, "like_count": 56, "comment_count": 78}
        # 유저 토큰 필요한 필드 부재 (seo수치/revisit/retention 없음)
        assert "seo" not in msg.result["metrics"]
        assert "revisit" not in msg.result["metrics"]

    @pytest.mark.asyncio
    async def test_video_details_missing_publishes_failure(self):
        """영상 상세 조회 실패 → is_success=False 발행 (Spring이 FAILED 처리)"""
        self._attach_recommend_mocks(details={})

        published = await self._run()

        assert len(published) == 1
        msg, topic = published[0]
        assert topic == "recommend-report-result-v2"
        assert msg.is_success is False
        assert msg.recommend_report_id == 5

    @pytest.mark.asyncio
    async def test_publishes_overview_summary(self):
        """개요 요약도 결과에 포함해 발행 — tag는 positive_pct(60) 기준으로 '긍정'"""
        self._attach_recommend_mocks()

        published = await self._run()

        msg, _ = published[0]
        assert msg.result["overview_summary"] == {
            "title": "제목", "content": "내용", "tag": "긍정",
        }

    @pytest.mark.asyncio
    async def test_skip_vector_save_is_true(self):
        """추천 리포트는 유저 종속 벡터 저장 불필요 → skip_vector_save=True로 재사용 서비스 호출"""
        self._attach_recommend_mocks()

        await self._run()

        report_service = self.consumer.recommend_generator.report_service
        report_service.create_script_summary.assert_awaited_once()
        assert report_service.create_script_summary.await_args.kwargs["skip_vector_save"] is True
        report_service.analyze_optimization.assert_awaited_once()
        assert report_service.analyze_optimization.await_args.kwargs["skip_vector_save"] is True


# ────────────────────────────────────────────────────────────
# 결과 메시지 키 — 같은 report의 overview/analysis가 같은 파티션으로 가야 함
# (Spring이 두 결과를 한 Report 행에 병합하므로 동시 처리되면 lost update)
# ────────────────────────────────────────────────────────────

async def _run_capturing_keys(handler, msg):
    keys = []

    async def fake_publish(message, topic, key=None):
        keys.append((message.is_success, key))

    with patch("domain.report.service.report_consumer_impl_v2.kafka_broker") as mock_broker:
        mock_broker.publish = fake_publish
        await handler(msg)

    return keys


class TestReportResultMessageKey:
    def setup_method(self):
        self.consumer = _make_consumer()

    @pytest.mark.asyncio
    async def test_overview_success_keyed_by_report_id(self):
        _attach_mocks(self.consumer)
        _attach_overview_mocks(self.consumer)

        keys = await _run_capturing_keys(self.consumer.handle_overview_v2, BASE_OVERVIEW_MSG)

        assert keys == [(True, b"10")]

    @pytest.mark.asyncio
    async def test_overview_failure_keyed_by_report_id(self):
        self.consumer.report_repository = MagicMock()
        self.consumer.report_repository.find_by_id = AsyncMock(return_value=None)

        keys = await _run_capturing_keys(self.consumer.handle_overview_v2, BASE_OVERVIEW_MSG)

        assert keys == [(False, b"10")]

    @pytest.mark.asyncio
    async def test_analysis_success_keyed_by_report_id(self):
        _attach_mocks(self.consumer)
        self.consumer.report_service = MagicMock()
        self.consumer.report_service.analyze_viewer_retention = AsyncMock(return_value={
            "criticalSection": {"startTime": "0:10", "endTime": "0:20", "duration": 10},
            "retentionGraph": [], "causes": [],
            "improvements": [], "expectedEffect": "",
        })
        self.consumer.report_service.analyze_optimization = AsyncMock(
            return_value={"categoryList": [], "additionalSuggestions": []}
        )
        self.consumer.rag_service = MagicMock()
        self.consumer.rag_service.generate_analysis_summary = AsyncMock(
            return_value={"title": "", "content": ""}
        )

        keys = await _run_capturing_keys(
            self.consumer.handle_analysis_v2, {"task_id": 2, "report_id": 10}
        )

        assert keys == [(True, b"10")]

    @pytest.mark.asyncio
    async def test_analysis_failure_keyed_by_report_id(self):
        _attach_mocks(self.consumer)
        self.consumer.report_service = MagicMock()
        self.consumer.report_service.analyze_viewer_retention = AsyncMock(
            side_effect=RuntimeError("분석 실패")
        )

        keys = await _run_capturing_keys(
            self.consumer.handle_analysis_v2, {"task_id": 2, "report_id": 10}
        )

        assert keys == [(False, b"10")]

    @pytest.mark.asyncio
    async def test_recommend_result_has_no_key(self):
        """추천 결과는 리포트당 1건이라 병합 경합이 없어 키를 붙이지 않음"""
        self.consumer.recommend_generator = MagicMock()
        self.consumer.recommend_generator.generate = AsyncMock(side_effect=RuntimeError("x"))

        keys = await _run_capturing_keys(self.consumer.handle_recommend_v2, BASE_RECOMMEND_MSG)

        assert keys == [(False, None)]
