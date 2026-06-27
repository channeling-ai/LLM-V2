from domain.trend_keyword.repository.trend_keyword_repository import TrendKeywordRepository
import logging


logger = logging.getLogger(__name__)

class TrendKeywordService:

    def __init__(self):
        self.trend_keyword_repository = TrendKeywordRepository()

    async def delete_past_chennel_keyword_if_exist(self, channel_id: int):
        logger.info(f"[delete_past_if_exist] 채널 ID={channel_id} 의 과거 키워드 조회 시작")

        # 실제 repository 메서드 호출
        latest_channel_keywords = await self.trend_keyword_repository.get_latest_channel_keywords(channel_id)
        if latest_channel_keywords:
            logger.info(f"[delete_past_if_exist] 채널 ID={channel_id} 기존 키워드 {len(latest_channel_keywords)}개 발견")
            # bulk 삭제 호출 
            await self.trend_keyword_repository.delete_trend_keywords_bulk(latest_channel_keywords)
            logger.info(f"[delete_past_if_exist] 채널 ID={channel_id} 기존 키워드 {len(latest_channel_keywords)}개 삭제 완료")
        
        else:
            logger.info(f"[delete_past_if_exist] 채널 ID={channel_id} 기존 키워드가 존재하지 않음 — 삭제 스킵")


    async def delete_past_realtime_keyword_if_exist(self):
        logger.info(f"[delete_realtime_keyword] 과거 실시간 트렌드 키워드 조회 시작")

        # 실제 repository 메서드 호출 (삭제 대상은 전체 조회)
        latest_channel_keywords = await self.trend_keyword_repository.get_latest_real_time_keywords(limit=1000)
        if latest_channel_keywords:
            logger.info(f"[delete_realtime_keyword]  기존 키워드 {len(latest_channel_keywords)}개 발견")
            # bulk 삭제 호출 
            await self.trend_keyword_repository.delete_trend_keywords_bulk(latest_channel_keywords)
            logger.info(f"[delete_realtime_keyword] 기존 키워드 {len(latest_channel_keywords)}개 삭제 완료")
        
        else:
            logger.info(f"[delete_realtime_keyword] 기존 키워드가 존재하지 않음 — 삭제 스킵")


