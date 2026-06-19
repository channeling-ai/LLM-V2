import json
import logging
import time

from core.enums.source_type import SourceTypeEnum
from domain.channel.repository.channel_repository import ChannelRepository
from domain.content_chunk.repository.content_chunk_repository import ContentChunkRepository
from domain.report.repository.report_repository import ReportRepository
from domain.trend_keyword.model.trend_keyword_type import TrendKeywordType
from domain.trend_keyword.repository.trend_keyword_repository import TrendKeywordRepository
from domain.video.model.video import Video
from external.rag import leave_analyize
from external.rag.rag_service_impl import RagServiceImpl

logger = logging.getLogger(__name__)

class ReportService:
    def __init__(self):
        self.report_repository = ReportRepository()
        self.content_chunk_repository = ContentChunkRepository()
        self.trend_keyword_repository = TrendKeywordRepository()
        self.channel_repository = ChannelRepository()
        self.rag_service = RagServiceImpl()

    async def create_script_summary(self, video: Video, report_id: int, skip_vector_save: bool = False) -> list:
        """
        영상 스크립트 요약 생성 (JSON 배열 반환)
        벡터 DB 저장만 담당 — PostgreSQL 저장은 Spring(Kafka 결과 수신 후)에서 처리
        """
        start_time = time.time()
        logger.info("스크립트 요약 생성 시작 - Report ID: %d", report_id)

        youtube_video_id = getattr(video, "youtube_video_id", None)
        if not youtube_video_id:
            raise ValueError("YouTube 영상 ID가 없습니다.")

        summary = await self.rag_service.summarize_video(youtube_video_id)
        logger.info("스크립트 요약 완료 - %d 구간 (%.2f초)", len(summary), time.time() - start_time)

        if not skip_vector_save and summary:
            await self.content_chunk_repository.save_context(
                source_type=SourceTypeEnum.VIDEO_SUMMARY,
                source_id=report_id,
                context=json.dumps(summary, ensure_ascii=False),
            )

        return summary

    async def analyze_viewer_retention(self, video: Video, report_id: int, token: str, skip_vector_save: bool = False, num_ticks: int = 10) -> dict:
        """
        시청자 이탈 분석. 분석 결과를 dict로 반환하며 DB 저장은 컨슈머에 위임.
        벡터 DB 저장(레퍼런스용)은 유지.

        Args:
            video: 비디오 객체
            report_id: 리포트 ID
            token: Google 액세스 토큰
            skip_vector_save: Vector DB 저장 스킵 여부 (기본값: False)
            num_ticks: retention graph 눈금 수 (기본값: 10)

        Returns:
            분석 결과 dict (criticalSection, retentionGraph, causes, improvements, expectedEffect)
        """
        start_time = time.time()
        logger.info(f"📊 시청자 이탈 분석 시작 - Report ID: {report_id}")

        try:
            leave_result: dict = await leave_analyize.analyze_leave(video, token, num_ticks=num_ticks)
            logger.info(f"📈 이탈 분석 완료 ({time.time() - start_time:.2f}초)")

            # 레퍼런스용 벡터 DB 저장만 유지 (report_repository.save 제거 — Spring이 Kafka 수신 후 저장)
            if not skip_vector_save:
                await self.content_chunk_repository.save_context(
                    source_type=SourceTypeEnum.VIEWER_ESCAPE_ANALYSIS,
                    source_id=int(report_id),
                    context=json.dumps(leave_result, ensure_ascii=False),
                )
            else:
                logger.info("[V2] 벡터 DB 저장을 스킵했습니다.")

            return leave_result

        except Exception as e:
            raise

    async def analyze_optimization(self, video: Video, report_id: int, skip_vector_save: bool = False) -> dict:
        """
        알고리즘 최적화 분석. 분석 결과를 dict로 반환하며 DB 저장은 컨슈머에 위임.
        벡터 DB 저장(레퍼런스용)은 유지.

        Args:
            video: 비디오 객체
            report_id: 리포트 ID
            skip_vector_save: Vector DB 저장 스킵 여부 (기본값: False)

        Returns:
            분석 결과 dict (categoryList, additionalSuggestions, grade 주입 완료)
        """
        start_time = time.time()
        logger.info(f"⚙️ 알고리즘 최적화 분석 시작 - Report ID: {report_id}")

        try:
            analyze_opt: dict = await self.rag_service.analyze_algorithm_optimization(
                video_id=video.youtube_video_id, skip_vector_save=skip_vector_save
            )
            logger.info(f"⚙️ 알고리즘 최적화 LLM 분석 완료 ({time.time() - start_time:.2f}초)")

            # 레퍼런스용 벡터 DB 저장만 유지 (report_repository.save 제거 — Spring이 Kafka 수신 후 저장)
            if not skip_vector_save:
                await self.content_chunk_repository.save_context(
                    source_type=SourceTypeEnum.ALGORITHM_OPTIMIZATION,
                    source_id=report_id,
                    context=json.dumps(analyze_opt, ensure_ascii=False),
                )
            else:
                logger.info("[V2] 벡터 DB 저장을 스킵했습니다.")

            logger.info(f"⚙️ 알고리즘 최적화 분석 전체 완료 ({time.time() - start_time:.2f}초)")
            return analyze_opt

        except Exception as e:
            logger.error(f"⚙️ 알고리즘 최적화 분석 실패 ({time.time() - start_time:.2f}초): {e}")
            raise

    async def analyze_trends_and_save(self, video: Video, report_id: int, skip_vector_save: bool = False) -> bool:
        """
        트렌드 분석 및 키워드 저장
        
        Args:
            video: 비디오 객체
            report_id: 리포트 ID
            skip_vector_save: Vector DB 저장 스킵 여부 (기본값: False)
            
        Returns:
            성공 시 True, 실패 시 False
        """
        start_time = time.time()
        logger.info(f"📊 트렌드 분석 시작 - Report ID: {report_id}")
        
        try:
            # 1. 실시간 트렌드 분석
            realtime_keyword = await self.rag_service.analyze_realtime_trends()
            
            # 2. 채널 정보 조회
            channel_id = getattr(video, "channel_id", None)
            if not channel_id:
                raise ValueError("video에 channel_id가 없습니다.")
                
            channel = await self.channel_repository.find_by_id(channel_id)
            if not channel:
                raise ValueError(f"channel_id={channel_id}에 해당하는 채널이 없습니다.")
            
            # 3. 채널 맞춤형 트렌드 분석
            channel_concept = getattr(channel, "concept", "")
            target_audience = getattr(channel, "target", "")
            
            channel_keyword = await self.rag_service.analyze_channel_trends(
                channel_concept=channel_concept,
                target_audience=target_audience
            )
            
            # 4. Vector DB에 채널 맞춤형 키워드 저장 (skip_vector_save가 False인 경우만)
            if not skip_vector_save:
                await self.content_chunk_repository.save_context(
                    source_type=SourceTypeEnum.PERSONALIZED_KEYWORDS,
                    source_id=report_id,
                    context=json.dumps(channel_keyword, ensure_ascii=False)
                )
                logger.info("채널 맞춤형 키워드를 Vector DB에 저장했습니다.")
            else:
                logger.info("[V2] 벡터 DB 저장을 스킵했습니다.")
            
            # 5. PostgreSQL에 키워드 저장
            # 실시간 트렌드 키워드 저장
            if realtime_keyword and "trends" in realtime_keyword:
                realtime_keywords_to_save = []
                for keyword_data in realtime_keyword["trends"]:
                    trend_keyword = {
                        "report_id": report_id,
                        "keyword_type": TrendKeywordType.REAL_TIME,
                        "keyword": keyword_data.get("keyword", ""),
                        "score": keyword_data.get("score", 0)
                    }
                    realtime_keywords_to_save.append(trend_keyword)
                
                await self.trend_keyword_repository.save_bulk(realtime_keywords_to_save)
                logger.info("실시간 트렌드 키워드를 PostgreSQL DB에 저장했습니다.")

            # 채널 맞춤형 키워드 저장
            if channel_keyword and "customized_trends" in channel_keyword:
                channel_keywords_to_save = []
                for keyword_data in channel_keyword["customized_trends"]:
                    trend_keyword = {
                        "report_id": report_id,
                        "keyword_type": TrendKeywordType.CHANNEL,
                        "keyword": keyword_data.get("keyword", ""),
                        "score": keyword_data.get("score", 0)
                    }
                    channel_keywords_to_save.append(trend_keyword)
                
                await self.trend_keyword_repository.save_bulk(channel_keywords_to_save)
                logger.info("채널 맞춤형 키워드를 PostgreSQL DB에 저장했습니다.")
            
            total_time = time.time() - start_time
            logger.info(f"📊 트렌드 분석 전체 완료 ({total_time:.2f}초)")
            return True
            
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(f"📊 트렌드 분석 실패 ({total_time:.2f}초): {e}")
            raise

