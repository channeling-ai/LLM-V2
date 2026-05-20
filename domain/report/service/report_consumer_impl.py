
import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from core.enums.source_type import SourceTypeEnum
from domain.channel.repository.channel_repository import ChannelRepository
from domain.comment.service.comment_service import CommentService
from domain.content_chunk.repository.content_chunk_repository import ContentChunkRepository
from domain.idea.service.idea_service import IdeaService
from domain.report.repository.report_repository import ReportRepository
from domain.report.service.report_consumer import ReportConsumer
from domain.report.service.report_service import ReportService
from domain.task.model.task import Status
from domain.task.repository.task_repository import TaskRepository
from domain.trend_keyword.model.trend_keyword_type import TrendKeywordType
from domain.trend_keyword.repository.trend_keyword_repository import TrendKeywordRepository
from domain.video.repository.video_repository import VideoRepository
from domain.video.service.video_service import VideoService
from external.rag import leave_analyize
from external.rag.rag_service_impl import RagServiceImpl
from external.youtube.youtube_comment_service import YoutubeCommentService

logger = logging.getLogger(__name__)

class ReportConsumerImpl(ReportConsumer):
    def __init__(self, broker):
        super().__init__(broker)
        self.rag_service = RagServiceImpl()
        self.video_repository = VideoRepository()
        self.report_repository = ReportRepository()
        self.task_repository = TaskRepository()
        self.content_chunk_repository = ContentChunkRepository()
        self.channel_repository = ChannelRepository()
        self.comment_service = CommentService()
        self.report_service = ReportService()
        self.trend_keyword_repository = TrendKeywordRepository()
        self.idea_service = IdeaService()
        self.youtube_comment_service = YoutubeCommentService()
        self.video_service = VideoService()
 

    async def _get_report_and_video(self, message: Dict[str, Any]) -> Optional[Tuple[Any, Any]]:
        """
        메시지에서 report_id를 추출하고 report와 video 정보를 조회하는 공통 메서드
        
        Args:
            message: 처리할 메시지
            
        Returns:
            성공 시 (report, video) 튜플, 실패 시 None
        """
        logger.info(f"받은 메시지 내용: {message}")

        report_id = message.get("report_id")
        if report_id is None:
            logger.error("report_id가 메시지에 없습니다")
            return None

        report = await self.report_repository.find_by_id(report_id)
        if not report:
            logger.warning(f"report_id={report_id}에 해당하는 보고서가 없습니다.")
            return None

        # Report 정보 로그 출력
        logger.info(f"보고서 정보: {report}")

        # 연관된 Video 정보 로그 출력
        video_id = getattr(report, "video_id", None)
        video = None
        if video_id:
            video = await self.video_repository.find_by_id(video_id)
            if video:
                logger.info(f"연관된 비디오 정보: {video}")
            else:
                logger.warning(f"video_id={video_id}에 해당하는 비디오가 없습니다.")
        else:
            logger.warning("report에 video_id가 없습니다.")
            
        return report, video


    async def handle_overview(self, message: Dict[str, Any]):
        logger.info(f"[V1] Handling overview request")

        start_time = time.time()  # 시작 시간 기록

        try:
            # 공통 메서드로 report와 video 정보 조회
            result = await self._get_report_and_video(message)
            if not result:
                return

            report, video = result
            report_id = report.id  

            # 요약 프로세스
            try:
                await self.report_service.create_script_summary(video, report_id)
            except Exception as e:
                logger.error(f"요약 프로세스 실패: {e!r}")
                raise
                
            # 댓글 프로세스
            try:
                await self.comment_service.analyze_comments(video, report_id)
            except Exception as e:
                logger.error(f"댓글 프로세스 실패: {e!r}")
                raise
                
            # 수치 정보 프로세스
            try:
                token = message.get("google_access_token")
                await self.video_service.analyze_metrics(video, report_id, token)
            except Exception as e:
                logger.error(f"수치 정보 프로세스 실패: {e!r}")
                raise


            # task 정보 업데이트
            task = await self.task_repository.find_by_id(message["task_id"])
            if task:
                await self.task_repository.save({
                    "id": task.id,
                    "overview_status": Status.COMPLETED
                })
                logger.info(f"Task ID {task.id}의 overview_status를 COMPLETED로 업데이트했습니다.")

        except Exception as e:
            logger.error(f"handle_overview 처리 중 오류 발생: {e}")
            # task 정보 업데이트
            task = await self.task_repository.find_by_id(message["task_id"])
            if task:
                await self.task_repository.save({
                    "id": task.id,
                    "overview_status": Status.FAILED
                })
                logger.info(f"Task ID {task.id}의 overview_status를 FAILED로 업데이트했습니다.")
        finally:
            end_time = time.time()  # 종료 시간 기록
            elapsed_time = end_time - start_time
            logger.info(f"[V1] handle_overview 전체 처리 시간: {elapsed_time:.3f}초")

        

    async def handle_analysis(self, message: Dict[str, Any]):
        """보고서 분석 요청 처리"""
        logger.info(f"[V1] Handling analysis request")
        start_time = time.time()  # 시작 시간 기록
        
        try:
            # 공통 메서드로 report와 video 정보 조회
            result = await self._get_report_and_video(message)
            if not result:
                return
            
            report, video = result
            
            # 시청자 이탈 분석 프로세스
            try:
                token = message.get("google_access_token")
                await self.report_service.analyze_viewer_retention(video, report.id, token)
            except Exception as e:
                logger.error(f"시청자 이탈 분석 프로세스 실패: {e!r}")
                raise
                
            # 알고리즘 최적화 분석 프로세스
            try:
                await self.report_service.analyze_optimization(video, report.id)
            except Exception as e:
                logger.error(f"알고리즘 최적화 분석 프로세스 실패: {e!r}")
                raise

            # task 업데이트
            task = await self.task_repository.find_by_id(message["task_id"])
            if task:
                await self.task_repository.save({
                    "id": task.id,
                    "analysis_status": Status.COMPLETED
                })
                logger.info(f"Task ID {task.id}의 analysis_status를 COMPLETED로 업데이트했습니다.")

        except Exception as e:
            logger.error(f"handle_analysis 처리 중 오류 발생: {e}")
            # task 정보 업데이트
            task = await self.task_repository.find_by_id(message["task_id"])
            if task:
                await self.task_repository.save({
                    "id": task.id,
                    "analysis_status": Status.FAILED
                })
                logger.info(f"Task ID {task.id}의 analysis_status를 FAILED로 업데이트했습니다.")
        finally:
            end_time = time.time()  # 종료 시간 기록
            elapsed_time = end_time - start_time
            logger.info(f"[V1] handle_analysis 전체 처리 시간: {elapsed_time:.3f}초")
