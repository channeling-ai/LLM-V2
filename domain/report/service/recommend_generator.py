import asyncio
import logging
import time
from typing import Optional

from core.enums.report_tag import OverviewTag
from core.kafka.dto.producer_message import (
    AlgorithmOptimization,
    CategoryItem,
    CommentAnalysis,
    IssueItem,
    RecommendMetrics,
    RecommendResult,
    ReportSummary,
    RepresentativeComment,
    ScriptSection,
)
from domain.comment.service.comment_service import CommentService
from domain.report.service.report_service import ReportService
from domain.video.model.video import Video
from external.rag.rag_service_impl import RagServiceImpl
from external.youtube.video_detail_service import VideoDetailService

logger = logging.getLogger(__name__)

# 리포트 행이 없는 호출(더미 리포트)에서 쓰는 report_id 대체값.
# 재사용 서비스에서 report_id는 로깅과 벡터 저장에만 쓰이며, 벡터 저장은 skip 하므로 안전하다.
NO_REPORT_ID = 0


class RecommendGenerator:
    """
    youtube_video_id 하나만으로 추천 리포트 본문(4개 blob)을 조립한다.
    유저 토큰·소유 엔티티·DB 행에 의존하지 않으므로
    Kafka 컨슈머(추천 리포트)와 REST 엔드포인트(더미 리포트)가 함께 재사용한다.
    """

    def __init__(
        self,
        report_service: Optional[ReportService] = None,
        comment_service: Optional[CommentService] = None,
        video_detail_service: Optional[VideoDetailService] = None,
        rag_service: Optional[RagServiceImpl] = None,
    ):
        self.report_service = report_service or ReportService()
        self.comment_service = comment_service or CommentService()
        self.video_detail_service = video_detail_service or VideoDetailService()
        self.rag_service = rag_service or RagServiceImpl()

    async def generate(self, youtube_video_id: str, report_id: int = NO_REPORT_ID) -> RecommendResult:
        """
        스크립트 요약 + 댓글 분석 + 공개 지표 + 알고리즘 최적화를 병렬 생성해 조립한다.
        실패는 그대로 전파한다 — 호출자가 실패 표현 방식(Kafka 실패 메시지 / HTTP 502)을 정한다.
        """
        if not youtube_video_id:
            raise ValueError("youtube_video_id가 없습니다")

        start_time = time.time()

        # 공개 상세 (제목/설명/view/like/comment) — 서버 키, 유저 토큰 불필요
        details = await self.video_detail_service.get_video_details(youtube_video_id)
        if not details:
            raise ValueError(f"영상 상세 조회 실패: {youtube_video_id}")

        # 경량 video 뷰 — 재사용 서비스는 youtube_video_id만 참조 (§R1)
        video = Video(
            youtube_video_id=youtube_video_id,
            title=details.get("title"),
            description=details.get("description"),
            view=details.get("viewCount", 0),
            like_count=details.get("likeCount", 0),
            comment_count=details.get("commentCount", 0),
        )

        # skip_vector_save=True — 추천/더미 리포트는 유저 종속 벡터 저장 불필요
        summary, comment_analysis, optimization = await asyncio.gather(
            self.report_service.create_script_summary(video, report_id, skip_vector_save=True),
            self.comment_service.analyze_comments(video, report_id),
            self.report_service.analyze_optimization(video, report_id, skip_vector_save=True),
        )

        metrics = RecommendMetrics(
            view=details.get("viewCount", 0),
            like_count=details.get("likeCount", 0),
            comment_count=details.get("commentCount", 0),
        )

        # 지표·댓글이 입력이라 위 gather 이후에만 만들 수 있다 (병렬화 불가)
        overview_summary = await self._build_overview_summary(metrics, comment_analysis)

        result = RecommendResult(
            summary=[ScriptSection(**s) for s in summary],
            comment_analysis=CommentAnalysis(
                **{k: v for k, v in comment_analysis.items() if k != "representative_comments"},
                representative_comments=[
                    RepresentativeComment(**c)
                    for c in comment_analysis.get("representative_comments", [])
                ],
            ),
            metrics=metrics,
            overview_summary=overview_summary,
            algorithm_optimization=AlgorithmOptimization(
                category_list=[
                    CategoryItem(
                        category=cat["category"],
                        score=cat["score"],
                        grade=cat["grade"],
                        issues=[IssueItem(**iss) for iss in cat.get("issues", [])],
                    )
                    for cat in optimization.get("categoryList", [])
                ],
                additional_suggestions=optimization.get("additionalSuggestions", []),
            ),
        )

        logger.info(
            "추천 리포트 본문 조립 완료 - videoId: %s (%.2f초)", youtube_video_id, time.time() - start_time
        )
        return result

    async def _build_overview_summary(
        self, metrics: RecommendMetrics, comment_analysis: dict
    ) -> ReportSummary:
        """
        개요 화면에 함께 내려갈 요약.
        일반 리포트와 동일하게 tag는 LLM 판단이 아니라 positive_pct 규칙으로 덮어쓴다.
        요약 생성이 실패해도 리포트 본문은 살려야 하므로 빈 요약으로 대체한다.
        """
        tag = OverviewTag.POSITIVE if comment_analysis.get("positive_pct", 0) >= 50 else OverviewTag.NEGATIVE

        try:
            raw = await self.rag_service.generate_overview_summary(
                metrics=metrics.model_dump(),
                comment_analysis=comment_analysis,
            )
        except Exception as e:
            logger.error("추천/더미 리포트 overview_summary 생성 실패: %s", e, exc_info=True)
            return ReportSummary(title="", content="", tag=tag)

        return ReportSummary(
            title=raw.get("title", ""),
            content=raw.get("content", ""),
            tag=tag,
        )
