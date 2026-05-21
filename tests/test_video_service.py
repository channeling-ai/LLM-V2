"""domain/video/service/video_service.py 단위 테스트

외부 의존성(Repository, RagService, AnalyticsService)은 모두 Mock 처리.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from domain.video.service.video_service import VideoService


def _make_service():
    # 생성자 내부에서 DB/외부 서비스를 초기화하므로 patch로 막은 뒤 직접 교체
    with patch("domain.video.service.video_service.VideoRepository"), \
         patch("domain.video.service.video_service.ContentChunkRepository"), \
         patch("domain.video.service.video_service.VideoDetailService"), \
         patch("domain.video.service.video_service.RagServiceImpl"):
        svc = VideoService()
    svc.video_repository = MagicMock()
    svc.content_chunk_repository = MagicMock()
    svc.youtube_video_detail_service = MagicMock()
    svc.rag_service = MagicMock()
    return svc


def _make_video(view=1000, like_count=50, comment_count=20, channel_id=1, youtube_video_id="vid1"):
    # id=99 고정 → _get_channel_averages 테스트에서 "자기 자신 제외" 확인 시 활용
    v = MagicMock()
    v.id = 99
    v.view = view
    v.like_count = like_count
    v.comment_count = comment_count
    v.channel_id = channel_id
    v.youtube_video_id = youtube_video_id
    v.title = "Test Video"
    v.description = "Test desc"
    return v


# ────────────────────────────────────────────────────────────
# _calculate_seo_numeric
# 수치 기반 SEO 점수 계산 (0~50점)
#   - 시청지속률(avg_view_duration / total_seconds) × 30점
#   - 참여율((likes + shares + subs) / views) × 20점
# analytics rows 구조: [views, avg_view_duration, likes, shares, subscribers_gained]
# ────────────────────────────────────────────────────────────

class TestCalculateSeoNumeric:
    def setup_method(self):
        self.svc = _make_service()

    def _call(self, rows, duration="PT600S"):
        # duration은 ISO 8601 형식 (PT600S = 600초)
        analytics_data = {"rows": rows}
        video_detail = {"duration": duration}
        return self.svc._calculate_seo_numeric(analytics_data, video_detail)

    def test_perfect_watch_ratio_and_engagement(self):
        """시청지속률 100% + 참여율 100% → 최고점 50점"""
        # avg_view_duration=600초 / total=600초 → watch_ratio=1.0 → 30점
        # likes=100 / views=100 → engagement=1.0 → 20점
        score = self._call([[100, 600, 100, 0, 0]])
        assert score == 50.0

    def test_zero_views_returns_zero(self):
        """경계값: 조회수 0 → engagement 분모가 0이 되므로 ZeroDivision 없이 0 반환해야 함"""
        score = self._call([[0, 0, 0, 0, 0]])
        assert score == 0.0

    def test_zero_duration_watch_ratio_is_zero(self):
        """경계값: 영상 길이 0(PT0S) → watch_ratio=0, engagement만 점수에 반영됨
        (길이 0인 영상은 분석 불가 케이스지만 engagement 점수는 그대로 계산되는 현재 동작 검증)"""
        # views=100, likes=10 → engagement=0.1 → 0.1×20=2.0점
        score = self._call([[100, 60, 10, 0, 0]], duration="PT0S")
        assert score == pytest.approx(2.0)

    def test_empty_rows_returns_zero(self):
        """YouTube Analytics API 응답에 rows가 없는 경우 → 0점"""
        score = self._call([])
        assert score == 0.0

    def test_watch_ratio_capped_at_1(self):
        """avg_view_duration이 total_seconds를 초과해도 watch_ratio는 1.0 상한 유지"""
        # avg=700초 > total=600초 → watch_ratio=min(700/600, 1.0)=1.0 → 30점
        # engagement=0 → 최종 30점
        score = self._call([[100, 700, 0, 0, 0]])
        assert score == 30.0

    def test_partial_scores(self):
        """시청지속률 50% + 참여율 50% → 각각 절반 점수"""
        # avg=300/600=50% → 0.5×30=15점
        # engagement=50/100=50% → 0.5×20=10점
        score = self._call([[100, 300, 50, 0, 0]])
        assert score == 25.0

    def test_invalid_duration_falls_back(self):
        """isodate 파싱 불가능한 duration 문자열 → 예외 없이 float 반환 (내부 fallback 동작)"""
        score = self._call([[100, 1, 0, 0, 0]], duration="INVALID")
        assert isinstance(score, float)


# ────────────────────────────────────────────────────────────
# _calculate_revisit
# 재방문률 = (좋아요 + 공유 + 구독증가) / 조회수 × 100
# ────────────────────────────────────────────────────────────

class TestCalculateRevisit:
    def setup_method(self):
        self.svc = _make_service()

    def _call(self, view, like_count, rows):
        video = _make_video(view=view, like_count=like_count)
        return self.svc._calculate_revisit(video, {"rows": rows})

    def test_basic_revisit(self):
        """정상 케이스: (좋아요 50 + 공유 10 + 구독 5) / 조회 1000 × 100 = 6.5%"""
        result = self._call(1000, 50, [[1000, 300, 50, 10, 5]])
        assert result == 6.5

    def test_zero_view_returns_zero(self):
        """경계값: 조회수 0 → ZeroDivision 없이 0 반환해야 함"""
        result = self._call(0, 50, [[0, 0, 0, 0, 0]])
        assert result == 0.0

    def test_no_rows(self):
        """YouTube Analytics rows 없음 → shares=0, subs=0으로 처리 → like_count만 반영"""
        # like=10 / view=100 × 100 = 10.0%
        result = self._call(100, 10, [])
        assert result == 10.0

    def test_row_missing_shares_and_subs(self):
        """row 배열이 짧아 index 3(shares), 4(subs)가 없는 경우 → 0으로 처리"""
        result = self._call(100, 20, [[100]])
        assert result == 20.0


# ────────────────────────────────────────────────────────────
# _get_channel_averages
# 채널 내 다른 영상들의 조회수·좋아요·댓글 평균 계산 (현재 영상 제외)
# ────────────────────────────────────────────────────────────

class TestGetChannelAverages:
    def setup_method(self):
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_single_video_channel_returns_zero(self):
        """채널에 현재 영상만 존재 → 비교 대상 없으므로 모두 0.0 반환"""
        video = _make_video()
        # id가 같으면 "자기 자신"으로 간주해 평균 계산에서 제외됨
        same_video = MagicMock()
        same_video.id = 99
        self.svc.video_repository.find_by_channel_id = AsyncMock(return_value=[same_video])

        result = await self.svc._get_channel_averages(video)
        assert result == {"view_avg": 0.0, "like_avg": 0.0, "comment_avg": 0.0}

    @pytest.mark.asyncio
    async def test_multiple_videos_average(self):
        """다른 영상 2개 → 각 지표의 산술 평균"""
        video = _make_video(view=100)
        other1 = MagicMock(id=1, view=200, like_count=20, comment_count=10)
        other2 = MagicMock(id=2, view=400, like_count=40, comment_count=30)
        self.svc.video_repository.find_by_channel_id = AsyncMock(
            return_value=[video, other1, other2]
        )

        result = await self.svc._get_channel_averages(video)
        assert result["view_avg"] == 300.0    # (200+400)/2
        assert result["like_avg"] == 30.0     # (20+40)/2
        assert result["comment_avg"] == 20.0  # (10+30)/2

    @pytest.mark.asyncio
    async def test_current_video_excluded_from_average(self):
        """현재 영상(id=99, view=9999)이 평균에서 제외되는지 확인"""
        video = _make_video(view=9999)
        other = MagicMock(id=1, view=100, like_count=10, comment_count=5)
        self.svc.video_repository.find_by_channel_id = AsyncMock(
            return_value=[video, other]
        )

        result = await self.svc._get_channel_averages(video)
        # 9999가 포함되었다면 (9999+100)/2=5049.5 → 100이면 제외된 것
        assert result["view_avg"] == 100.0


# ────────────────────────────────────────────────────────────
# _analyze_concept
# 채널 일관성 점수 (0~100): 현재 영상과 채널 내 다른 영상들의 코사인 유사도 평균 × 100
# ────────────────────────────────────────────────────────────

class TestAnalyzeConcept:
    def setup_method(self):
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_no_other_videos_returns_100(self):
        """채널 내 다른 영상이 없으면 비교 불가 → 100점(최고점) 반환"""
        video = _make_video()
        # id=99 = 자기 자신이므로 others 리스트가 비어 있게 됨
        self.svc.video_repository.find_by_channel_id = AsyncMock(return_value=[video])

        result = await self.svc._analyze_concept(video)
        assert result == 100.0

    @pytest.mark.asyncio
    async def test_perfect_similarity_returns_100(self):
        """동일한 임베딩 벡터 → 코사인 유사도 1.0 → 100점"""
        import numpy as np
        video = _make_video()
        other = MagicMock(id=1, title="T", description="D")

        self.svc.video_repository.find_by_channel_id = AsyncMock(
            return_value=[video, other]
        )
        # 같은 벡터를 반환하면 dot/(norm*norm) = 1.0
        embedding = np.array([1.0, 0.0, 0.0])
        self.svc.content_chunk_repository.generate_embedding = AsyncMock(return_value=embedding)

        result = await self.svc._analyze_concept(video)
        assert result == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_zero_norm_embedding_returns_zero_similarity(self):
        """제로 벡터(영벡터) → norm=0이므로 유사도 0 처리 (ZeroDivision 방지)"""
        import numpy as np
        video = _make_video()
        other = MagicMock(id=1, title="T", description="D")

        self.svc.video_repository.find_by_channel_id = AsyncMock(
            return_value=[video, other]
        )
        self.svc.content_chunk_repository.generate_embedding = AsyncMock(
            return_value=np.array([0.0, 0.0, 0.0])
        )

        result = await self.svc._analyze_concept(video)
        assert result == 0.0


# ────────────────────────────────────────────────────────────
# analyze_metrics (공개 메서드 통합 흐름)
# 내부 private 메서드들을 Mock으로 교체해 반환 구조만 검증
# ────────────────────────────────────────────────────────────

class TestAnalyzeMetrics:
    def setup_method(self):
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self):
        """Kafka DTO(Metrics)에 필요한 모든 키가 반환 dict에 포함되는지 확인"""
        video = _make_video()
        analytics_data = {"rows": [[1000, 300, 50, 10, 5]]}

        # _gather_base_data: (analytics_data, concept_score) 튜플 반환
        self.svc._gather_base_data = AsyncMock(return_value=(analytics_data, 80.0))
        self.svc.youtube_video_detail_service.get_video_details = AsyncMock(
            return_value={"duration": "PT600S", "title": "T", "description": "D", "tags": []}
        )
        self.svc._get_channel_averages = AsyncMock(
            return_value={"view_avg": 500.0, "like_avg": 30.0, "comment_avg": 10.0}
        )
        # SEO 정성 점수 (0~50점)
        self.svc.rag_service.evaluate_seo_qualitative = AsyncMock(return_value={"score": 30})

        result = await self.svc.analyze_metrics(video, report_id=1, access_token="token")

        required_keys = {"view", "view_channel_avg", "like_count", "like_channel_avg",
                         "comment_count", "comment_channel_avg", "concept", "seo", "revisit"}
        assert required_keys.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_date_params_passed_to_gather(self):
        """start_date / end_date 가 _gather_base_data(= Analytics API 호출)까지 전달되는지 확인"""
        video = _make_video()
        captured = {}

        async def fake_gather(v, token, start_date, end_date):
            captured["start_date"] = start_date
            captured["end_date"] = end_date
            return ({"rows": [[100, 60, 10, 0, 0]]}, 50.0)

        self.svc._gather_base_data = fake_gather
        self.svc.youtube_video_detail_service.get_video_details = AsyncMock(
            return_value={"duration": "PT600S", "title": "T", "description": "", "tags": []}
        )
        self.svc._get_channel_averages = AsyncMock(
            return_value={"view_avg": 0.0, "like_avg": 0.0, "comment_avg": 0.0}
        )
        self.svc.rag_service.evaluate_seo_qualitative = AsyncMock(return_value={"score": 0})

        await self.svc.analyze_metrics(
            video, report_id=1, access_token="tk",
            start_date="2024-01-01", end_date="2024-03-31"
        )

        assert captured["start_date"] == "2024-01-01"
        assert captured["end_date"] == "2024-03-31"
