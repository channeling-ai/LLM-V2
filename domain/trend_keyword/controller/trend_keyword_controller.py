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
            trend_keyword = {
                "channel_id":  None,
                "keyword_type": TrendKeywordType.REAL_TIME,
                "keyword": keyword_data.get("keyword", ""),
                "score": score
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

    # 실시간 트랜드 상위 5개 가져오기
    latest_trend_keywords = await trend_keyword_repository.get_latest_real_time_keywords()

    #채널 트랜드 ....
    channel_keyword = await rag_service.analyze_channel_trends(
        channel_concept=channel_concept,
        target_audience=target_audience,
        latest_trend_keywords=latest_trend_keywords  # 키워드 인자로 전달
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
            trend_keyword = {
                "channel_id": channel_id,
                "keyword_type": TrendKeywordType.CHANNEL,
                "keyword": keyword_data.get("keyword", ""),
                "score": score
            }
            channel_keywords_to_save.append(trend_keyword)
        
        await trend_keyword_repository.save_bulk(channel_keywords_to_save)
        logger.info("채널 맞춤형 키워드를 PG DB에 저장했습니다.")
    return {"message": "ok"}
