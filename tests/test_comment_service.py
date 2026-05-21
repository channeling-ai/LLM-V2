"""domain/comment/service/comment_service.py 단위 테스트

외부 의존성(YouTube API, RagService)은 모두 Mock 처리.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from collections import defaultdict

from domain.comment.service.comment_service import CommentService


def _make_service():
    """외부 의존성 Mock 처리된 CommentService 인스턴스"""
    with patch("domain.comment.service.comment_service.RagServiceImpl"), \
         patch("domain.comment.service.comment_service.YoutubeCommentService"):
        svc = CommentService()
    svc.rag_service = MagicMock()
    svc.youtube_comment_service = MagicMock()
    return svc


def _make_comment(content: str, category: str = "positive", like_count: int = 0) -> dict:
    return {
        "content": content,
        "author": "user_a",
        "published_at": "2024-01-01T00:00:00Z",
        "like_count": like_count,
    }


# ────────────────────────────────────────────────────────────
# _build_result
# 수집된 샘플 댓글 counts / total_sampled 기반으로
# 실제 총 댓글 수(total_comment_count)에 맞춰 추정 count와 pct를 계산
# ────────────────────────────────────────────────────────────

class TestBuildResult:
    def setup_method(self):
        self.svc = _make_service()

    def _call(self, total_comment_count, counts, total_sampled, rep=None, summaries=None):
        return self.svc._build_result(
            total_comment_count=total_comment_count,
            counts=counts,
            total_sampled=total_sampled,
            representative_comments=rep or [],
            category_summaries=summaries or {"positive": "", "negative": "", "neutral": "", "advice": ""},
        )

    def test_basic_ratio(self):
        """샘플 20개 중 긍정 10개 → pct=50%, 전체 100개 기준 count=50"""
        result = self._call(
            total_comment_count=100,
            counts={"positive": 10, "negative": 5, "neutral": 3, "advice": 2},
            total_sampled=20,
        )
        assert result["positive_pct"] == 50.0
        assert result["negative_pct"] == 25.0
        assert result["positive_count"] == 50   # 100 * 10/20

    def test_total_comment_count_preserved(self):
        """total_comment_count는 YouTube stats에서 가져온 실제 수치 — 변경 없이 그대로 반환"""
        result = self._call(
            total_comment_count=999,
            counts={"positive": 1},
            total_sampled=1,
        )
        assert result["total_comment_count"] == 999

    def test_zero_total_sampled_returns_zero_pcts(self):
        """경계값: 수집된 댓글 0개(total_sampled=0) → ZeroDivision 없이 모든 pct/count가 0"""
        result = self._call(
            total_comment_count=50,
            counts={"positive": 0},
            total_sampled=0,
        )
        assert result["positive_pct"] == 0.0
        assert result["negative_pct"] == 0.0
        assert result["positive_count"] == 0

    def test_missing_category_defaults_to_zero(self):
        """counts dict에 없는 카테고리(negative, neutral, advice)는 0으로 처리"""
        result = self._call(
            total_comment_count=10,
            counts={"positive": 5},  # 나머지 카테고리 키 없음
            total_sampled=5,
        )
        assert result["negative_count"] == 0
        assert result["neutral_count"] == 0
        assert result["advice_count"] == 0

    def test_pct_rounds_to_one_decimal(self):
        """1/3 = 33.333...% → 소수점 1자리 반올림 → 33.3%"""
        result = self._call(
            total_comment_count=30,
            counts={"positive": 1},
            total_sampled=3,
        )
        assert result["positive_pct"] == 33.3

    def test_representative_comments_pass_through(self):
        """representative_comments는 별도 가공 없이 그대로 결과에 포함"""
        rep = [{"category": "positive", "content": "good", "author": "a",
                "published_at": "2024-01-01", "like_count": 5}]
        result = self._call(
            total_comment_count=10,
            counts={"positive": 1},
            total_sampled=1,
            rep=rep,
        )
        assert result["representative_comments"] == rep


# ────────────────────────────────────────────────────────────
# _empty_result
# 수집된 댓글이 0개일 때 반환하는 기본 구조
# ────────────────────────────────────────────────────────────

class TestEmptyResult:
    def setup_method(self):
        self.svc = _make_service()

    def test_empty_result_structure(self):
        """4개 카테고리 키가 모두 존재하고 count/pct가 모두 0인 구조 반환"""
        result = self.svc._empty_result(42)
        assert result["total_comment_count"] == 42
        assert result["positive_count"] == 0
        assert result["positive_pct"] == 0.0
        assert result["representative_comments"] == []
        assert set(result["category_summaries"].keys()) == {"positive", "negative", "neutral", "advice"}

    def test_empty_result_zero_total(self):
        """YouTube stats에서 총 댓글 수가 0인 경우도 정상 처리"""
        result = self.svc._empty_result(0)
        assert result["total_comment_count"] == 0


# ────────────────────────────────────────────────────────────
# _select_representative
# 카테고리별 좋아요 상위 3개 댓글을 직접 인용 댓글로 선정
# ────────────────────────────────────────────────────────────

class TestSelectRepresentative:
    def setup_method(self):
        self.svc = _make_service()

    def test_top_3_by_like_count(self):
        """10개 댓글 중 좋아요 내림차순 상위 3개만 선정, 순서 보장"""
        comments = [_make_comment(f"c{i}", like_count=i) for i in range(10)]
        grouped = {"positive": comments}
        result = self.svc._select_representative(grouped)
        likes = [r["like_count"] for r in result if r["category"] == "positive"]
        assert likes == sorted(likes, reverse=True)
        assert len(likes) == 3

    def test_fewer_than_3_comments(self):
        """댓글이 3개 미만이면 있는 만큼만 반환 (상한만 있고 하한 없음)"""
        grouped = {"positive": [_make_comment("only one", like_count=1)]}
        result = self.svc._select_representative(grouped)
        assert len(result) == 1

    def test_empty_category_not_included(self):
        """댓글이 없는 카테고리는 결과에 포함되지 않음"""
        grouped = {"positive": [], "negative": [_make_comment("bad", like_count=0)]}
        result = self.svc._select_representative(grouped)
        categories = [r["category"] for r in result]
        assert "positive" not in categories
        assert "negative" in categories

    def test_all_four_categories(self):
        """4개 카테고리 모두 5개씩 → 각 카테고리에서 3개 = 총 12개"""
        grouped = {
            cat: [_make_comment(f"{cat}-{i}", like_count=i) for i in range(5)]
            for cat in ["positive", "negative", "neutral", "advice"]
        }
        result = self.svc._select_representative(grouped)
        assert len(result) == 12

    def test_tie_like_count_takes_up_to_3(self):
        """좋아요 수가 동점이어도 최대 3개 제한은 적용됨"""
        comments = [_make_comment(f"c{i}", like_count=5) for i in range(10)]
        grouped = {"positive": comments}
        result = self.svc._select_representative(grouped)
        assert len([r for r in result if r["category"] == "positive"]) == 3


# ────────────────────────────────────────────────────────────
# analyze_comments (공개 메서드 통합 흐름)
# 수집 → 배치 분류 → 카테고리 요약 → 대표 댓글 선정 → 결과 dict 반환
# ────────────────────────────────────────────────────────────

class TestAnalyzeComments:
    def setup_method(self):
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_raises_when_no_youtube_video_id(self):
        """youtube_video_id가 None이면 YouTube API 호출 전에 ValueError 발생"""
        video = MagicMock()
        video.youtube_video_id = None

        with pytest.raises(ValueError, match="YouTube 영상 ID가 없습니다"):
            await self.svc.analyze_comments(video, report_id=1)

    @pytest.mark.asyncio
    async def test_returns_empty_result_when_no_comments(self):
        """수집된 댓글이 0개 → 분류/요약 호출 없이 _empty_result 반환"""
        video = MagicMock()
        video.youtube_video_id = "abc123"

        self.svc.youtube_comment_service.get_total_comment_count = AsyncMock(return_value=0)
        self.svc.youtube_comment_service.get_comments = AsyncMock(return_value=[])

        result = await self.svc.analyze_comments(video, report_id=1)
        assert result["total_comment_count"] == 0
        assert result["positive_count"] == 0

    @pytest.mark.asyncio
    async def test_full_flow_with_comments(self):
        """댓글 2개 → 분류(긍정/부정) → 요약 → 결과 dict 반환까지 전체 흐름 검증"""
        video = MagicMock()
        video.youtube_video_id = "vid123"

        raw = [
            {"content": "great!", "author": "a", "published_at": "2024-01-01", "like_count": 10},
            {"content": "bad!", "author": "b", "published_at": "2024-01-02", "like_count": 2},
        ]
        self.svc.youtube_comment_service.get_total_comment_count = AsyncMock(return_value=200)
        self.svc.youtube_comment_service.get_comments = AsyncMock(return_value=raw)
        # emotion: 1=긍정, 2=부정
        self.svc.rag_service.classify_comments_batch = AsyncMock(
            return_value=[{"index": 0, "emotion": 1}, {"index": 1, "emotion": 2}]
        )
        self.svc.rag_service.summarize_comment_categories = AsyncMock(
            return_value={"positive": "좋아요", "negative": "싫어요", "neutral": "", "advice": ""}
        )

        result = await self.svc.analyze_comments(video, report_id=1)

        assert result["total_comment_count"] == 200
        assert "positive_pct" in result
        assert "representative_comments" in result

    @pytest.mark.asyncio
    async def test_date_params_forwarded_to_youtube_service(self):
        """start_date / end_date 가 YouTube 댓글 수집 API 호출까지 그대로 전달되는지 확인"""
        video = MagicMock()
        video.youtube_video_id = "vid999"

        self.svc.youtube_comment_service.get_total_comment_count = AsyncMock(return_value=0)
        self.svc.youtube_comment_service.get_comments = AsyncMock(return_value=[])

        await self.svc.analyze_comments(
            video, report_id=1, start_date="2024-01-01", end_date="2024-03-31"
        )

        self.svc.youtube_comment_service.get_comments.assert_called_once_with(
            "vid999", 1, start_date="2024-01-01", end_date="2024-03-31"
        )


# ────────────────────────────────────────────────────────────
# _classify_in_batches
# 댓글을 BATCH_SIZE(20)개씩 묶어 LLM에 배치 분류 요청
# 각 댓글의 emotion 코드(1~4)를 카테고리 문자열(positive/negative/neutral/advice)로 변환
# ────────────────────────────────────────────────────────────

class TestClassifyInBatches:
    def setup_method(self):
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_batch_size_splits_correctly(self):
        """22개 댓글 → BATCH_SIZE(20)으로 나뉘어 첫 번째 20개, 두 번째 2개로 호출"""
        raw = [{"content": f"c{i}"} for i in range(22)]
        calls = []

        async def mock_batch(batch_input):
            calls.append(len(batch_input))
            # emotion=1(긍정)으로 전부 반환
            return [{"index": j, "emotion": 1} for j in range(len(batch_input))]

        self.svc.rag_service.classify_comments_batch = mock_batch

        result = await self.svc._classify_in_batches(raw)
        assert calls == [20, 2]
        assert len(result) == 22
        assert all(c == "positive" for c in result)

    @pytest.mark.asyncio
    async def test_fallback_to_neutral_on_parse_error(self):
        """LLM 응답에서 특정 index 누락 시 해당 댓글은 neutral로 처리 (데이터 유실 방지)"""
        raw = [{"content": "c0"}, {"content": "c1"}]
        # index=1 응답 누락
        self.svc.rag_service.classify_comments_batch = AsyncMock(
            return_value=[{"index": 0, "emotion": 1}]
        )
        result = await self.svc._classify_in_batches(raw)
        assert result[0] == "positive"
        assert result[1] == "neutral"  # 누락된 index → neutral fallback

    @pytest.mark.asyncio
    async def test_unknown_emotion_code_maps_to_neutral(self):
        """LLM이 1~4 외의 알 수 없는 emotion 코드를 반환하면 neutral로 처리"""
        raw = [{"content": "x"}]
        self.svc.rag_service.classify_comments_batch = AsyncMock(
            return_value=[{"index": 0, "emotion": 99}]  # 정의되지 않은 코드
        )
        result = await self.svc._classify_in_batches(raw)
        assert result[0] == "neutral"

    @pytest.mark.asyncio
    async def test_empty_comments(self):
        """입력 댓글이 없으면 LLM 호출 없이 빈 리스트 반환"""
        result = await self.svc._classify_in_batches([])
        assert result == []
