from datetime import datetime
from fastapi import APIRouter
import logging
from external.rag.rag_service_impl import RagServiceImpl
from domain.trend_keyword.repository.trend_keyword_repository import TrendKeywordRepository
from domain.trend_keyword.service.trend_keyword_service import TrendKeywordService
from domain.channel.repository.channel_repository import ChannelRepository
from domain.trend_keyword.model.trend_keyword_type import TrendKeywordType


logger = logging.getLogger(__name__)

trend_keyword_repository = TrendKeywordRepository()
trend_keyword_service = TrendKeywordService()
channel_repository = ChannelRepository()
rag_service = RagServiceImpl()

router = APIRouter(prefix="/trend-keywords", tags=["trend-keywords"])

@router.post("/real-time")
async def create_real_time_keyword():

    # 삭제 전 이전 score 백업
    existing_keywords = await trend_keyword_repository.get_latest_real_time_keywords(limit=100)
    previous_score_map = {kw.keyword: kw.score for kw in existing_keywords}

    await trend_keyword_service.delete_past_realtime_keyword_if_exist()

    realtime_keyword = await rag_service.analyze_realtime_trends()
    if "error" not in realtime_keyword:
        logger.info(f"실시간 트렌드 LLM 응답: {realtime_keyword}")

    # 실시간 트렌드 키워드 저장
    if realtime_keyword and "trends" in realtime_keyword:
        realtime_keywords_to_save = []
        for keyword_data in realtime_keyword["trends"]:
            # int 가 아닌 float 이 반환되는 경우 처리
            try:
                score = int(keyword_data.get("score", 0))
            except (ValueError, TypeError):
                score = 0
            keyword = keyword_data.get("keyword", "")
            started_at_str = keyword_data.get("started_at")
            started_at = datetime.strptime(started_at_str, "%Y-%m-%d %H:%M") if started_at_str else None
            trend_keyword = {
                "channel_id":  None,
                "keyword_type": TrendKeywordType.REAL_TIME,
                "keyword": keyword,
                "score": score,
                "started_at": started_at,
                "previous_score": previous_score_map.get(keyword),
            }
            realtime_keywords_to_save.append(trend_keyword)

        await trend_keyword_repository.save_bulk(realtime_keywords_to_save)
        logger.info("실시간 트렌드 키워드를 PG DB에 저장했습니다.")
    return {"message": "ok"}



@router.post("/channel/{channel_id}")
async def create_channel_keyword(channel_id: int):

    # 채널 조회 및 컨셉, 타겟 꺼내기
    channel = await channel_repository.find_by_id(channel_id)
    if not channel:
        raise ValueError(f"channel_id={channel_id}에 해당하는 채널이 없습니다.")

    channel_concept = getattr(channel, "concept", "")
    target_audience = getattr(channel, "target", "")

    # 삭제 전 이전 score 백업 (LLM 호출 전에 수행해야 race condition 방지)
    existing_channel_keywords = await trend_keyword_repository.get_latest_channel_keywords(channel_id)
    previous_score_map = {kw.keyword: kw.score for kw in existing_channel_keywords}

    # 실시간 트랜드 상위 5개 가져오기
    latest_trend_keywords = await trend_keyword_repository.get_latest_real_time_keywords()

    # 채널 트랜드 분석
    channel_keyword = await rag_service.analyze_channel_trends(
        channel_concept=channel_concept,
        target_audience=target_audience,
        latest_trend_keywords=latest_trend_keywords
    )
    logger.info(f"채널 맞춤형 트렌드 LLM 응답: {channel_keyword}")

    # 기존 채널 맞춤형 키워드 존재 시 삭제
    await trend_keyword_service.delete_past_chennel_keyword_if_exist(channel_id)

    # 채널 맞춤형 키워드 저장
    if channel_keyword and "customized_trends" in channel_keyword:
        channel_keywords_to_save = []
        for keyword_data in channel_keyword["customized_trends"]:
            # int 가 아닌 float 이 반환되는 경우 처리
            try:
                score = int(keyword_data.get("score", 0))
            except (ValueError, TypeError):
                score = 0
            keyword = keyword_data.get("keyword", "")
            trend_keyword = {
                "channel_id": channel_id,
                "keyword_type": TrendKeywordType.CHANNEL,
                "keyword": keyword,
                "score": score,
                "previous_score": previous_score_map.get(keyword),
            }
            channel_keywords_to_save.append(trend_keyword)

        await trend_keyword_repository.save_bulk(channel_keywords_to_save)
        logger.info("채널 맞춤형 키워드를 PG DB에 저장했습니다.")
    return {"message": "ok"}
