
import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from core.kafka.kafka_broker import kafka_broker
from core.kafka.dto.producer_message import Message, Step, OverviewResult, AnalysisResult
from core.config.kafka_config import kafka_config
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
from core.cache.redis_client import RedisService  # 합쳐진 RedisService


logger = logging.getLogger(__name__)

class ReportConsumerImplV2(ReportConsumer):
    def __init__(self, broker, group_id: str = kafka_config.consumer_group_id):
        super().__init__(broker, group_id=group_id)
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
        self.redis_service = RedisService()  # 기본 host/port 사용

 

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

    async def create_summary_update(self, report_id):
        task = await self.task_repository.find_by_report(report_id)
        if task.overview_status == Status.COMPLETED and task.analysis_status == Status.COMPLETED:
            logger.info(f"모든 작업 완료. 요약 생성 시작 (Report {report_id})")
            await self.report_service.summarize_update_changes(report_id)


    async def handle_overview_v2(self, message: Dict[str, Any]):
        logger.info(f"[V2] Handling overview request")

        start_time = time.time()  # 시작 시간 기록

        try:
            # 공통 메서드로 report와 video 정보 조회
            result = await self._get_report_and_video(message)
            if not result:
                logger.error(f"메시지 정보를 가져오지 못했습니다. 메시지: {message}")
                raise

            report, video = result
            report_id = report.id  

            # 요약 프로세스 (skip_vector_save=True)
            skip_vector_save = message.get("skip_vector_save", False)
            logger.info(f"[V2] skip_vector_save: {skip_vector_save}")
            
            try:
                await self.report_service.create_summary(video, report_id, skip_vector_save=skip_vector_save)
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

                logger.info(f"Kafka publish 시작: topic={kafka_config.report_result_v3}, report_id={report.id}, task_id={task.id}")
                await kafka_broker.publish(
                    Message(
                        is_success=True,
                        task_id=task.id,
                        report_id=report.id,
                        step=Step.overview,
                        result=OverviewResult(
                            summary="summary_test",
                            comment_analysis="comment_test",
                        )
                    ),
                    topic=kafka_config.report_result_v3
                )
                logger.info(f"Kafka publish 완료: topic={kafka_config.report_result_v3}")

            await self.create_summary_update(report.id)

        except Exception as e:
            logger.error(f"handle_overview 처리 중 오류 발생: {e}")
            # task 정보 업데이트
            task = await self.task_repository.find_by_id(message["task_id"])
            if task:
                await self.task_repository.save({
                    "id": task.id,
                    "overview_status": Status.FAILED
                })
                await kafka_broker.publish( 
                    Message(
                        is_success=False,
                        task_id=task.id,
                        report_id=message.get("report_id"),
                        step=Step.overview,
                    ),
                    topic=kafka_config.report_result_v3
                )
        finally:
            end_time = time.time()  # 종료 시간 기록
            elapsed_time = end_time - start_time
            logger.info(f"[V2] handle_overview 전체 처리 시간: {elapsed_time:.3f}초")

        

    async def handle_analysis_v2(self, message: Dict[str, Any]):
        """보고서 분석 요청 처리"""
        logger.info(f"[V2] Handling analysis request")
        start_time = time.time()  # 시작 시간 기록

        try:
            # 공통 메서드로 report와 video 정보 조회
            result = await self._get_report_and_video(message)
            if not result:
                logger.error(f"메시지 정보를 가져오지 못했습니다. 메시지: {message}")
                raise
            
            report, video = result
            
            # 시청자 이탈 분석 프로세스 (skip_vector_save=True)
            skip_vector_save = message.get("skip_vector_save", False)
            logger.info(f"[V2] skip_vector_save: {skip_vector_save}")
            
            try:
                token = message.get("google_access_token")
                await self.report_service.analyze_viewer_retention(video, report.id, token, skip_vector_save=skip_vector_save)
            except Exception as e:
                logger.error(f"시청자 이탈 분석 프로세스 실패: {e!r}")
                raise
                
            # 알고리즘 최적화 분석 프로세스 (skip_vector_save=True)
            try:
                await self.report_service.analyze_optimization(video, report.id, skip_vector_save=skip_vector_save)
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
                
                # Kafka 발행
                logger.info(f"Kafka publish 시작: topic={kafka_config.report_result_v3}, report_id={report.id}, task_id={task.id}")
                await kafka_broker.publish(
                    Message(
                        is_success=True,
                        task_id=task.id,
                        report_id=report.id,
                        step=Step.analysis,
                        result=AnalysisResult(
                            viewer_retention="viewer_test",
                            optimization="optimization_test",
                        )
                    ),
                    topic=kafka_config.report_result_v3
                )
                logger.info(f"Kafka publish 완료: topic={kafka_config.report_result_v3}")

            await self.create_summary_update(report.id)

        except Exception as e:
            logger.error(f"handle_analysis 처리 중 오류 발생: {e}")
            # task 정보 업데이트
            task = await self.task_repository.find_by_id(message["task_id"])
            if task:
                await self.task_repository.save({
                    "id": task.id,
                    "analysis_status": Status.FAILED
                })
                await kafka_broker.publish(
                    Message(
                        is_success=False,
                        task_id=task.id,
                        report_id=message.get("report_id"),
                        step=Step.analysis,
                    ),
                    topic=kafka_config.report_result_v3
                )
        finally:
            end_time = time.time()  # 종료 시간 기록
            elapsed_time = end_time - start_time
            logger.info(f"[V2] handle_analysis 전체 처리 시간: {elapsed_time:.3f}초")


    async def handle_idea_v2(self, message: Dict[str, Any]):
        """보고서 아이디어 요청 처리"""
        logger.info(f"[V2] Handling idea request")
        start_time = time.time()  # 시작 시간 기록
        try:
            # 공통 메서드로 report와 video 정보 조회
            result = await self._get_report_and_video(message)
            if not result:
                return
            report, video = result
            report_id = report.id
            # 트렌드 분석 및 키워드 저장 프로세스 (skip_vector_save=True)
            skip_vector_save = message.get("skip_vector_save", False)
            logger.info(f"[V2] skip_vector_save: {skip_vector_save}")
            
            try:
                await self.report_service.analyze_trends_and_save(video, report_id, skip_vector_save=skip_vector_save)
            except Exception as e:
                logger.error(f"트렌드 분석 및 키워드 저장 프로세스 실패: {e!r}")
                raise
                
            # 채널 정보는 아이디어 서비스에서 필요하므로 조회
            channel_id = getattr(video, "channel_id", None)
            if not channel_id:
                logger.error("video에 channel_id가 없습니다.")
                return
                
            channel = await self.channel_repository.find_by_id(channel_id)
            if not channel:
                logger.warning(f"channel_id={channel_id}에 해당하는 채널이 없습니다.")
                return

            # 아이디어 생성 프로세스
            try:
                await self.idea_service.create_idea(video, channel, report_id)
            except Exception as e:
                logger.error(f"아이디어 생성 프로세스 실패: {e!r}")
                raise

            # task 업데이트
            task = await self.task_repository.find_by_id(message["task_id"])
            if task:
                await self.task_repository.save({
                    "id": task.id,
                    "idea_status": Status.COMPLETED
                })
                logger.info(f"Task ID {task.id}의 idea_status를 COMPLETED로 업데이트했습니다.")

        except Exception as e:
            logger.error(f"handle_idea 처리 중 오류 발생: {e!r}")
            # task 정보 업데이트
            task = await self.task_repository.find_by_id(message["task_id"])
            if task:
                await self.task_repository.save({
                    "id": task.id,
                    "idea_status": Status.FAILED
                })
                logger.info(f"Task ID {task.id}의 idea_status를 FAILED로 업데이트했습니다.")
        finally:
            end_time = time.time()  # 종료 시간 기록
            elapsed_time = end_time - start_time
            logger.info(f"[V2] handle_idea 처리 완료 (소요 시간: {elapsed_time:.2f}초)")
