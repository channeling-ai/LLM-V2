import logging
import time
from collections import defaultdict
from typing import Optional

from domain.comment.model.comment_type import CommentType
from domain.video.model.video import Video
from external.rag.rag_service_impl import RagServiceImpl
from external.youtube.youtube_comment_service import YoutubeCommentService

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
REPRESENTATIVE_PER_CATEGORY = 3

EMOTION_TO_CATEGORY = {
    1: "positive",
    2: "negative",
    3: "neutral",
    4: "advice",
}

CATEGORY_TO_COMMENT_TYPE = {
    "positive": CommentType.POSITIVE,
    "negative": CommentType.NEGATIVE,
    "neutral": CommentType.NEUTRAL,
    "advice": CommentType.ADVICE,
}


class CommentService:
    def __init__(self):
        self.rag_service = RagServiceImpl()
        self.youtube_comment_service = YoutubeCommentService()

    async def analyze_comments(
        self,
        video: Video,
        report_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        댓글 수집 → 배치 분류 → 카테고리 요약 → 대표 댓글 선정
        Returns: comment_analysis dict (Kafka 결과 메시지용)
        """
        start_time = time.time()
        youtube_video_id = getattr(video, "youtube_video_id", None)
        if not youtube_video_id:
            raise ValueError("YouTube 영상 ID가 없습니다.")

        # 1. 실제 총 댓글 수 (YouTube stats)
        total_comment_count = await self.youtube_comment_service.get_total_comment_count(youtube_video_id)
        logger.info("실제 총 댓글 수: %d", total_comment_count)

        # 2. 댓글 수집 (인기순 150 + 최신순 50, 기간 필터)
        raw_comments = await self.youtube_comment_service.get_comments(
            youtube_video_id, report_id, start_date=start_date, end_date=end_date
        )
        logger.info("수집된 댓글 수: %d", len(raw_comments))

        if not raw_comments:
            return self._empty_result(total_comment_count)

        # 3. 배치 분류 (20개씩)
        classified = await self._classify_in_batches(raw_comments)

        # 4. 카테고리별 그룹핑
        grouped: dict[str, list[dict]] = defaultdict(list)
        for comment, category in zip(raw_comments, classified):
            grouped[category].append(comment)

        # 5. 카테고리별 한줄 요약 (댓글이 있는 카테고리만 LLM 호출)
        category_texts = {
            cat: [c["content"] for c in comments[:50]]
            for cat, comments in grouped.items()
            if comments
        }
        raw_summaries = await self.rag_service.summarize_comment_categories(category_texts)
        category_summaries = {
            cat: raw_summaries.get(cat, "")
            for cat in ["positive", "negative", "neutral", "advice"]
        }

        # 6. 대표 댓글 선정 (카테고리별 좋아요 상위 3개)
        representative_comments = self._select_representative(grouped)

        # 7. 카테고리별 수 & 비율 계산
        counts = {cat: len(comments) for cat, comments in grouped.items()}
        total_sampled = len(raw_comments)
        result = self._build_result(
            total_comment_count, counts, total_sampled,
            representative_comments, category_summaries
        )

        logger.info("댓글 분석 완료 (%.2f초)", time.time() - start_time)
        return result

    async def _classify_in_batches(self, raw_comments: list[dict]) -> list[str]:
        """배치 분류 → 각 댓글의 카테고리 문자열 리스트 반환"""
        categories = []
        for i in range(0, len(raw_comments), BATCH_SIZE):
            batch = raw_comments[i:i + BATCH_SIZE]
            batch_input = [{"index": j, "content": c["content"]} for j, c in enumerate(batch)]
            results = await self.rag_service.classify_comments_batch(batch_input)

            # index 순서 보장
            result_map = {r["index"]: r.get("emotion", 3) for r in results}
            for j in range(len(batch)):
                emotion = result_map.get(j, 3)
                categories.append(EMOTION_TO_CATEGORY.get(emotion, "neutral"))

        return categories

    def _select_representative(self, grouped: dict[str, list[dict]]) -> list[dict]:
        """카테고리별 좋아요 상위 3개 직접 인용"""
        representative = []
        for category in ["positive", "negative", "neutral", "advice"]:
            comments = grouped.get(category, [])
            top = sorted(comments, key=lambda c: c.get("like_count", 0), reverse=True)[:REPRESENTATIVE_PER_CATEGORY]
            for c in top:
                representative.append({
                    "category": category,
                    "content": c["content"],
                    "author": c.get("author", ""),
                    "published_at": c.get("published_at", ""),
                    "like_count": c.get("like_count", 0),
                })
        return representative

    def _build_result(
        self,
        total_comment_count: int,
        counts: dict,
        total_sampled: int,
        representative_comments: list[dict],
        category_summaries: dict,
    ) -> dict:
        positive = counts.get("positive", 0)
        negative = counts.get("negative", 0)
        neutral = counts.get("neutral", 0)
        advice = counts.get("advice", 0)

        def pct(n):
            return round(n / total_sampled * 100, 1) if total_sampled else 0

        def estimated(n):
            return round(total_comment_count * n / total_sampled) if total_sampled else 0

        return {
            "total_comment_count": total_comment_count,
            "positive_count": estimated(positive),
            "negative_count": estimated(negative),
            "neutral_count": estimated(neutral),
            "advice_count": estimated(advice),
            "positive_pct": pct(positive),
            "negative_pct": pct(negative),
            "neutral_pct": pct(neutral),
            "advice_pct": pct(advice),
            "representative_comments": representative_comments,
            "category_summaries": category_summaries,
        }

    def _empty_result(self, total_comment_count: int) -> dict:
        return {
            "total_comment_count": total_comment_count,
            "positive_count": 0, "negative_count": 0,
            "neutral_count": 0, "advice_count": 0,
            "positive_pct": 0.0, "negative_pct": 0.0,
            "neutral_pct": 0.0, "advice_pct": 0.0,
            "representative_comments": [],
            "category_summaries": {"positive": "", "negative": "", "neutral": "", "advice": ""},
        }
