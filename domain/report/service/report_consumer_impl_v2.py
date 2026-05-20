import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

from core.kafka.kafka_broker import kafka_broker
from core.kafka.dto.producer_message import (
    Message, Step, OverviewResult, AnalysisResult,
    ScriptSection, Metrics, CommentAnalysis, RepresentativeComment, ReportSummary,
)
from core.enums.report_tag import OverviewTag, SeoTag
from core.config.kafka_config import kafka_config
from domain.channel.repository.channel_repository import ChannelRepository
from domain.comment.service.comment_service import CommentService
from domain.content_chunk.repository.content_chunk_repository import ContentChunkRepository
from domain.idea.service.idea_service import IdeaService
from domain.report.repository.report_repository import ReportRepository
from domain.report.service.report_consumer import ReportConsumer
from domain.report.service.report_service import ReportService
from domain.trend_keyword.repository.trend_keyword_repository import TrendKeywordRepository
from domain.video.repository.video_repository import VideoRepository
from domain.video.service.video_service import VideoService
from external.rag.rag_service_impl import RagServiceImpl
from core.cache.redis_client import RedisService

logger = logging.getLogger(__name__)


class ReportConsumerImplV2(ReportConsumer):
    def __init__(self, broker, group_id: str = kafka_config.consumer_group_id):
        super().__init__(broker, group_id=group_id)
        self.rag_service = RagServiceImpl()
        self.video_repository = VideoRepository()
        self.report_repository = ReportRepository()
        self.content_chunk_repository = ContentChunkRepository()
        self.channel_repository = ChannelRepository()
        self.comment_service = CommentService()
        self.report_service = ReportService()
        self.trend_keyword_repository = TrendKeywordRepository()
        self.idea_service = IdeaService()
        self.video_service = VideoService()
        self.redis_service = RedisService()

    async def _get_report_and_video(self, message: Dict[str, Any]) -> Optional[Tuple[Any, Any]]:
        logger.info("받은 메시지 내용: %s", message)
        report_id = message.get("report_id")
        if report_id is None:
            logger.error("report_id가 메시지에 없습니다")
            return None

        report = await self.report_repository.find_by_id(report_id)
        if not report:
            logger.warning("report_id=%s에 해당하는 보고서가 없습니다.", report_id)
            return None

        video_id = getattr(report, "video_id", None)
        video = None
        if video_id:
            video = await self.video_repository.find_by_id(video_id)
            if not video:
                logger.warning("video_id=%s에 해당하는 비디오가 없습니다.", video_id)
        return report, video

    async def handle_overview_v2(self, message: Dict[str, Any]):
        logger.info("[V2] Overview 처리 시작")
        start_time = time.time()

        task_id = message.get("task_id")
        report_id = message.get("report_id")
        token = message.get("google_access_token")
        skip_vector_save = message.get("skip_vector_save", False)
        start_date = message.get("start_date")
        end_date = message.get("end_date")
        previous_report_id = message.get("previous_report_id")

        try:
            result = await self._get_report_and_video(message)
            if not result:
                raise ValueError(f"메시지 정보 조회 실패: {message}")
            report, video = result
            report_id = report.id

            # 이전 리포트 조회 (재생성 시 비교용)
            previous_report = None
            if previous_report_id:
                previous_report = await self.report_repository.find_by_id(previous_report_id)

            # 3개 프로세스 병렬 실행
            summary, comment_analysis, metrics = await asyncio.gather(
                self.report_service.create_script_summary(video, report_id, skip_vector_save=skip_vector_save),
                self.comment_service.analyze_comments(video, report_id, start_date=start_date, end_date=end_date),
                self.video_service.analyze_metrics(video, report_id, token, start_date=start_date, end_date=end_date),
            )

            # overview_summary / seo_summary — 실패해도 성공 메시지 발행
            positive_pct = comment_analysis.get("positive_pct", 0)
            overview_tag = OverviewTag.POSITIVE if positive_pct >= 50 else OverviewTag.NEGATIVE
            seo_tag = SeoTag.OPTIMIZED if metrics.get("seo", 0) >= 70 else SeoTag.NEEDS_OPTIMIZATION

            overview_summary = ReportSummary(title="", content="", tag=overview_tag)
            seo_summary = ReportSummary(title="", content="", tag=seo_tag)
            try:
                raw_overview, raw_seo = await asyncio.gather(
                    self.rag_service.generate_overview_summary(
                        metrics=metrics,
                        comment_analysis=comment_analysis,
                        previous_report=previous_report,
                    ),
                    self.rag_service.generate_seo_summary(
                        seo_score=metrics.get("seo", 0),
                    ),
                )
                overview_summary = ReportSummary(
                    title=raw_overview.get("title", ""),
                    content=raw_overview.get("content", ""),
                    tag=overview_tag,
                )
                seo_summary = ReportSummary(
                    title=raw_seo.get("title", ""),
                    content=raw_seo.get("content", ""),
                    tag=seo_tag,
                )
            except Exception as e:
                logger.error("[V2] overview_summary/seo_summary 생성 실패 (report_id=%s): %s", report_id, e)

            # Kafka 결과 발행
            await kafka_broker.publish(
                Message(
                    is_success=True,
                    task_id=task_id,
                    report_id=report_id,
                    step=Step.overview,
                    result=OverviewResult(
                        summary=[ScriptSection(**s) for s in summary],
                        metrics=Metrics(**metrics),
                        comment_analysis=CommentAnalysis(
                            **{k: v for k, v in comment_analysis.items() if k != "representative_comments"},
                            representative_comments=[
                                RepresentativeComment(**c)
                                for c in comment_analysis.get("representative_comments", [])
                            ],
                        ),
                        overview_summary=overview_summary,
                        seo_summary=seo_summary,
                    ),
                ),
                topic=kafka_config.report_result_v3,
            )
            logger.info("[V2] Overview 결과 발행 완료 (%.2f초)", time.time() - start_time)

        except Exception as e:
            logger.error("handle_overview 처리 중 오류 발생: %s", e)
            await kafka_broker.publish(
                Message(
                    is_success=False,
                    task_id=task_id,
                    report_id=report_id,
                    step=Step.overview,
                ),
                topic=kafka_config.report_result_v3,
            )
        finally:
            logger.info("[V2] handle_overview 전체 처리 시간: %.3f초", time.time() - start_time)

    async def handle_analysis_v2(self, message: Dict[str, Any]):
        """보고서 분석 요청 처리"""
        logger.info("[V2] Analysis 처리 시작")
        start_time = time.time()
        task_id = message.get("task_id")
        report_id = message.get("report_id")

        try:
            result = await self._get_report_and_video(message)
            if not result:
                raise ValueError(f"메시지 정보 조회 실패: {message}")
            report, video = result

            skip_vector_save = message.get("skip_vector_save", False)
            token = message.get("google_access_token")
            start_date = message.get("start_date")
            end_date = message.get("end_date")

            await self.report_service.analyze_viewer_retention(
                video, report.id, token, skip_vector_save=skip_vector_save
            )
            await self.report_service.analyze_optimization(
                video, report.id, skip_vector_save=skip_vector_save
            )

            await kafka_broker.publish(
                Message(
                    is_success=True,
                    task_id=task_id,
                    report_id=report.id,
                    step=Step.analysis,
                    result=AnalysisResult(),
                ),
                topic=kafka_config.report_result_v3,
            )

        except Exception as e:
            logger.error("handle_analysis 처리 중 오류 발생: %s", e)
            await kafka_broker.publish(
                Message(
                    is_success=False,
                    task_id=task_id,
                    report_id=report_id,
                    step=Step.analysis,
                ),
                topic=kafka_config.report_result_v3,
            )
        finally:
            logger.info("[V2] handle_analysis 전체 처리 시간: %.3f초", time.time() - start_time)

    async def handle_idea_v2(self, message: Dict[str, Any]):
        """보고서 아이디어 요청 처리"""
        logger.info("[V2] Idea 처리 시작")
        start_time = time.time()
        task_id = message.get("task_id")
        report_id = message.get("report_id")

        try:
            result = await self._get_report_and_video(message)
            if not result:
                return
            report, video = result
            skip_vector_save = message.get("skip_vector_save", False)

            await self.report_service.analyze_trends_and_save(video, report.id, skip_vector_save=skip_vector_save)

            channel_id = getattr(video, "channel_id", None)
            if not channel_id:
                logger.error("video에 channel_id가 없습니다.")
                return

            channel = await self.channel_repository.find_by_id(channel_id)
            if not channel:
                logger.warning("channel_id=%s에 해당하는 채널이 없습니다.", channel_id)
                return

            await self.idea_service.create_idea(video, channel, report.id)

        except Exception as e:
            logger.error("handle_idea 처리 중 오류 발생: %s", e)
        finally:
            logger.info("[V2] handle_idea 처리 완료 (%.2f초)", time.time() - start_time)
