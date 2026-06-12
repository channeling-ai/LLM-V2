from typing import List

from dotenv import load_dotenv
from domain.content_chunk.repository.content_chunk_repository import ContentChunkRepository
import external.youtube.analytics_service as analyticsServcie
import external.rag.chunk_service as ChunkService # ← 지연 import로 순환참조 방지
from external.youtube.transcript_service import TranscriptService  # 유튜브 자막 처리 서비스
from domain.video.model.video import Video
from core.enums.source_type import SourceTypeEnum
from external.rag.rag_service_impl import RagServiceImpl
import json
from core.llm.prompt_template_manager import PromptTemplateManager
from domain.channel.repository.channel_repository import ChannelRepository
import os
import logging
import time
load_dotenv()

logger = logging.getLogger(__name__)
transcript_service = TranscriptService()
content_repository = ContentChunkRepository()
rag_service = RagServiceImpl()
channel_repository = ChannelRepository()

async def analyze_leave(video: Video, token: str) -> str:
    try:
        logger.info(f"시청자 이탈 분석 시작 - 비디오 ID: {video.id}, 유튜브 ID: {video.youtube_video_id}")
    






        # 1. 영상, 채널 정보 가져오기
        
        # 영상 가져오기
        youtube_video_id = video.youtube_video_id
        video_id = video.id
        logger.info(f"분석 대상 - 유튜브 비디오 ID: {youtube_video_id}, 내부 비디오 ID: {video_id}")

        # 채널 가져오기    
        channel_id = video.channel_id
        channel = await channel_repository.find_by_id(channel_id)
        if not channel:
            logger.error(f"채널 ID {channel_id}를 찾을 수 없습니다.")
            raise ValueError(f"채널을 찾을 수 없습니다: {channel_id}")

    # context, analytics_data = await asyncio.gather(
    #     transcript_service.get_structured_transcript(youtube_video_id),
    #     analyticsServcie.get_youtube_analytics_data(token, youtube_video_id)
    # )




        # 2. 영상의 스크립트 가져오기
        # 대본 스크립트 가져오기 (Redis 캐싱 적용)
        transcript_start = time.time()
        logger.info("📜 영상 자막 데이터 가져오는 중...")
        context = await transcript_service.get_structured_transcript(youtube_video_id)
        transcript_time = time.time() - transcript_start
        logger.info(f"📜 자막 데이터 가져오기 완료 ({transcript_time:.2f}초)")
        
        if not context:
            logger.error("자막 데이터를 가져올 수 없습니다.")
            return "자막을 불러올 수 없는 영상입니다."
        
        # 3. 스크립트를 사용해서 영상 총 길이 구하기
        video_length = context[-1]["end_time"]
        logger.info(f"영상 총 길이: {video_length}초")

        # 4. 영상 분석 결과 가져오기 (analytics)
        analytics_start = time.time()
        logger.info("📊 YouTube Analytics 데이터 가져오는 중...")
        metrics = "audienceWatchRatio,relativeRetentionPerformance"
        dimensions = "elapsedVideoTimeRatio"
        analytics_data = await analyticsServcie.get_youtube_analytics_data(token, youtube_video_id, metrics, dimensions)
        analytics_time = time.time() - analytics_start
        logger.info(f"📊 YouTube Analytics 데이터 가져오기 완료 ({analytics_time:.2f}초)")
        
        if not analytics_data or "rows" not in analytics_data:
            logger.warning("Analytics 데이터를 가져올 수 없습니다. 기본값 사용.")
            analytics_data = {"rows": []}

        # 5. 분석 결과로 이탈 시점 구하기
        worst_ratio = analyticsServcie.find_max_drop_time(analytics_data.get("rows", []))
        logger.info(f"최대 이탈 시점 비율: {worst_ratio}")

        # 6. 시간 단위 청킹 및 임베딩 저장
        chunking_start = time.time()
        logger.info("🔧 시간 단위 청킹 데이터 확인 중...")
        exists = await content_repository.exists_by_chunk_type_and_id("time", video_id)
        if exists:
            logger.info("기존에 저장한 적 있는 영상입니다. 대본 기반의 청킹 생성을 건너뜁니다.")
        else:
            logger.info("🔧 시간 단위 청킹 생성 중...")
            await ChunkService.create_time_chunks_with_focus(video_id, video_length, context, analytics_data.get("rows", []), worst_ratio)
        
        # 7. 의미 단위 청킹 및 임베딩 저장
        logger.info("🔧 의미 단위 청킹 생성 중...")
        await ChunkService.create_meaning_chunks_with_focus(video_id, video_length, context, analytics_data.get("rows", []), worst_ratio)
        chunking_time = time.time() - chunking_start
        logger.info(f"🔧 청킹 및 임베딩 저장 완료 ({chunking_time:.2f}초)")



        # 8. 질문 리스트와 유사도 분석해서, 각 질문마다 3개씩의 청킹을 조회
        similarity_start = time.time()
        logger.info("🔍 유사도 검색 시작...")
        
        # # 1) 질문 리스트
        questions = {
            "cause": "이 영상의 시청 이탈 원인을 설명해 주세요.",
            "improvement": "이 영상의 시청 이탈을 줄이기 위한 개선 방안을 제시해 주세요.",
            "editing_flow": "이 영상에 적합한 예상 편집 흐름을 제안해 주세요."
        }

        # 추가 필터링이 있다면..?
        meta = {}
        # 2) 질문별 임베딩 및 유사 청킹 검색
        # 이탈 원인 질문의 상위 3개 청킹 데이터 조회 
        cause_chunk = await content_repository.search_similar_K(questions["cause"],SourceTypeEnum.VIEWER_ESCAPE_ANALYSIS.value.upper(), video_id, meta ,3)
        # 이탈 원인 질문의 상위 3개 청킹 데이터 조회 
        improvement_chunk = await content_repository.search_similar_K(questions["improvement"],SourceTypeEnum.VIEWER_ESCAPE_ANALYSIS.value.upper(), video_id ,meta ,3)
        # 이탈 원인 질문의 상위 3개 청킹 데이터 조회 
        editing_flow_chunk = await content_repository.search_similar_K(questions["editing_flow"],SourceTypeEnum.VIEWER_ESCAPE_ANALYSIS.value.upper(), video_id, meta ,3)
        
        similarity_time = time.time() - similarity_start
        logger.info(f"🔍 유사도 검색 완료 ({similarity_time:.2f}초)")


        # llm 출력
        worst_sec = int(worst_ratio * video_length)  # 최악 이탈 시점(초)
        focus_range_sec = max(10, min(int(0.04 * video_length), 300))  # 집중 범위: 영상 길이의 4%, 최소 10초, 최대 5분
        start_focus_time = max(0, worst_sec - focus_range_sec // 2)
        end_focus_time = min(video_length, worst_sec + focus_range_sec // 2)
        # 3. context 생성
        context_data = {
            "cause_chunk": json.dumps(cause_chunk, ensure_ascii=False, indent=2),
            "improvement_chunk": json.dumps(improvement_chunk, ensure_ascii=False, indent=2),
            "editing_flow_chunk": json.dumps(editing_flow_chunk, ensure_ascii=False, indent=2),
            "worst_sec": worst_sec,
            "start_focus_time": start_focus_time,
            "end_focus_time": end_focus_time,
            "video_length": video_length,
            "video_title" : video.title,
            "video_description" : video.description,
            "video_category" : video.video_category,
            "channel_concept" : channel.concept,
            "channel_target" : channel.target,
            "channel_hashtag" : channel.channel_hash_tag
        }

        # 9. 1,8번에서 조회한 정보를 프롬프트에 넣기   
        prompt_template_str = PromptTemplateManager.get_viewer_escape_analysis_prompt()
        formatted_prompt = prompt_template_str.format(**context_data)  
    
        # 10. LLM 직접 호출해서 결과 가져오기
        llm_start = time.time()
        logger.info("🤖 LLM 이탈 분석 실행 중...")
        result = await rag_service.execute_llm_direct(formatted_prompt)
        llm_time = time.time() - llm_start
        logger.info(f"🤖 LLM 이탈 분석 완료 ({llm_time:.2f}초)")
        
        return result

    except Exception as e:
        logger.error(f"시청자 이탈 분석 중 오류 발생: {e}")
        raise e
   
