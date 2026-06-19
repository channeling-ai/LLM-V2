import json
import logging
import re
import time
from typing import List

from dotenv import load_dotenv

from core.enums.source_type import SourceTypeEnum
from core.llm.prompt_template_manager import PromptTemplateManager
from domain.channel.repository.channel_repository import ChannelRepository
from domain.content_chunk.repository.content_chunk_repository import ContentChunkRepository
from domain.video.model.video import Video
import external.youtube.analytics_service as analyticsService
import external.rag.chunk_service as ChunkService  # 지연 import로 순환참조 방지
from external.youtube.transcript_service import TranscriptService
from external.rag.rag_service_impl import RagServiceImpl

load_dotenv()

logger = logging.getLogger(__name__)
transcript_service = TranscriptService()
content_repository = ContentChunkRepository()
rag_service = RagServiceImpl()
channel_repository = ChannelRepository()


def _format_retention_graph(retention_graph: list) -> str:
    """retention_graph 리스트를 프롬프트용 문자열로 포맷"""
    return ", ".join(f"{p['time']}={p['retentionRate']}%" for p in retention_graph)


async def analyze_leave(video: Video, token: str, num_ticks: int = 10) -> dict:
    try:
        logger.info(f"시청자 이탈 분석 시작 - 비디오 ID: {video.id}, 유튜브 ID: {video.youtube_video_id}")

        # 1. 영상, 채널 정보 가져오기
        youtube_video_id = video.youtube_video_id
        video_id = video.id
        logger.info(f"분석 대상 - 유튜브 비디오 ID: {youtube_video_id}, 내부 비디오 ID: {video_id}")

        channel_id = video.channel_id
        channel = await channel_repository.find_by_id(channel_id)
        if not channel:
            logger.error(f"채널 ID {channel_id}를 찾을 수 없습니다.")
            raise ValueError(f"채널을 찾을 수 없습니다: {channel_id}")

        # 2. 영상 스크립트 가져오기 (Redis 캐싱 적용)
        transcript_start = time.time()
        logger.info("영상 자막 데이터 가져오는 중...")
        context = await transcript_service.get_structured_transcript(youtube_video_id)
        logger.info(f"자막 데이터 가져오기 완료 ({time.time() - transcript_start:.2f}초)")

        if not context:
            logger.error("자막 데이터를 가져올 수 없습니다.")
            return {
                "criticalSection": {"startTime": "00:00", "endTime": "00:10", "duration": 10},
                "retentionGraph": [],
                "causes": [],
                "improvements": [],
                "expectedEffect": "자막을 불러올 수 없는 영상입니다.",
            }

        # 3. 영상 총 길이 구하기
        video_length = context[-1]["end_time"]
        logger.info(f"영상 총 길이: {video_length}초")

        # 4. YouTube Analytics 데이터 가져오기
        analytics_start = time.time()
        logger.info("YouTube Analytics 데이터 가져오는 중...")
        metrics = "audienceWatchRatio,relativeRetentionPerformance"
        dimensions = "elapsedVideoTimeRatio"
        analytics_data = await analyticsService.get_youtube_analytics_data(token, youtube_video_id, metrics, dimensions)
        logger.info(f"YouTube Analytics 데이터 가져오기 완료 ({time.time() - analytics_start:.2f}초)")

        if not analytics_data or "rows" not in analytics_data:
            logger.warning("Analytics 데이터를 가져올 수 없습니다. 기본값 사용.")
            analytics_data = {"rows": []}

        rows = analytics_data.get("rows", [])
        logger.info(f"Analytics rows 수신: {len(rows)}개 (0개면 조회수 부족으로 YouTube 데이터 미제공)")

        # 5. 이탈 지점 계산 및 구간/그래프 생성
        worst = analyticsService.find_worst_drop(rows, video_length)
        worst_ratio = worst["ratio"]
        logger.info(f"최대 이탈 시점: {worst['sec']:.1f}초 (비율: {worst_ratio:.3f})")

        critical_section = analyticsService.build_critical_section(worst_ratio, video_length)
        retention_graph = analyticsService.build_retention_graph(rows, video_length, num_ticks)

        # 6. 시간/의미 단위 청킹 및 임베딩 저장
        chunking_start = time.time()
        logger.info("시간 단위 청킹 데이터 확인 중...")
        exists = await content_repository.exists_by_chunk_type_and_id("time", video_id)
        if exists:
            logger.info("기존에 저장한 적 있는 영상입니다. 대본 기반의 청킹 생성을 건너뜁니다.")
        else:
            logger.info("시간 단위 청킹 생성 중...")
            await ChunkService.create_time_chunks_with_focus(video_id, video_length, context, rows, worst_ratio)

        logger.info("의미 단위 청킹 생성 중...")
        await ChunkService.create_meaning_chunks_with_focus(video_id, video_length, context, rows, worst_ratio)
        logger.info(f"청킹 및 임베딩 저장 완료 ({time.time() - chunking_start:.2f}초)")

        # 7. 유사도 검색 (원인 / 개선 2개 질문, editing_flow 제거)
        similarity_start = time.time()
        logger.info("유사도 검색 시작...")
        meta = {}
        cause_chunk = await content_repository.search_similar_K(
            "이 영상의 시청 이탈 원인을 설명해 주세요.",
            SourceTypeEnum.VIEWER_ESCAPE_ANALYSIS.value.upper(), video_id, meta, 3
        )
        improvement_chunk = await content_repository.search_similar_K(
            "이 영상의 시청 이탈을 줄이기 위한 개선 방안을 제시해 주세요.",
            SourceTypeEnum.VIEWER_ESCAPE_ANALYSIS.value.upper(), video_id, meta, 3
        )
        logger.info(f"유사도 검색 완료 ({time.time() - similarity_start:.2f}초)")

        # 8. 프롬프트 조립 및 LLM 호출
        context_data = {
            "timeline":          _format_retention_graph(retention_graph),
            "drop_points":       f"{worst['sec']:.1f}초 ({worst_ratio * 100:.1f}%)",
            "cause_chunk":       json.dumps(cause_chunk, ensure_ascii=False, indent=2),
            "improvement_chunk": json.dumps(improvement_chunk, ensure_ascii=False, indent=2),
            "video_title":       video.title,
            "video_category":    video.video_category,
            "channel_concept":   channel.concept,
            "channel_target":    channel.target,
        }

        prompt_template_str = PromptTemplateManager.get_viewer_escape_analysis_prompt()
        formatted_prompt = prompt_template_str.format(**context_data)

        llm_start = time.time()
        logger.info("LLM 이탈 분석 실행 중...")
        raw = await rag_service.execute_llm_direct(formatted_prompt)
        logger.info(f"LLM 이탈 분석 완료 ({time.time() - llm_start:.2f}초)")

        # 9. JSON 파싱 (마크다운 코드블록 제거 후 파싱)
        json_str = re.sub(r"```json|```", "", raw).strip()
        try:
            llm_result = json.loads(json_str)
        except json.JSONDecodeError:
            logger.error(f"LLM JSON 파싱 실패: {raw[:200]}")
            llm_result = {"causes": [], "improvements": [], "expectedEffect": "분석 결과를 생성하지 못했습니다."}

        return {
            "criticalSection": critical_section,
            "retentionGraph":  retention_graph,
            "causes":          llm_result.get("causes", []),
            "improvements":    llm_result.get("improvements", []),
            "expectedEffect":  llm_result.get("expectedEffect", ""),
        }

    except Exception as e:
        logger.error(f"시청자 이탈 분석 중 오류 발생: {e}")
        raise e
