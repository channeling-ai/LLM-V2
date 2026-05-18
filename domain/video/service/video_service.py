import logging
from typing import Optional

import isodate
import numpy as np

from domain.content_chunk.repository.content_chunk_repository import ContentChunkRepository
from domain.video.model.video import Video
from domain.video.repository.video_repository import VideoRepository
import external.youtube.analytics_service as analytics_service
from external.youtube.video_detail_service import VideoDetailService
from external.rag.rag_service_impl import RagServiceImpl

logger = logging.getLogger(__name__)


class VideoService:

    def __init__(self):
        self.video_repository = VideoRepository()
        self.content_chunk_repository = ContentChunkRepository()
        self.youtube_video_detail_service = VideoDetailService()
        self.rag_service = RagServiceImpl()

    async def analyze_metrics(
        self,
        video: Video,
        report_id: int,
        access_token: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        영상 수치 지표 분석
        Returns: metrics dict (Kafka 결과 메시지용)
        """
        analytics_data, concept_score = await self._gather_base_data(
            video, access_token, start_date, end_date
        )

        video_detail = await self.youtube_video_detail_service.get_video_details(video.youtube_video_id)
        channel_avgs = await self._get_channel_averages(video)

        seo = await self._calculate_seo(analytics_data, video_detail, video)
        revisit = self._calculate_revisit(video, analytics_data)

        return {
            "view": video.view,
            "view_channel_avg": channel_avgs["view_avg"],
            "like_count": video.like_count,
            "like_channel_avg": channel_avgs["like_avg"],
            "comment_count": video.comment_count,
            "comment_channel_avg": channel_avgs["comment_avg"],
            "concept": round(concept_score, 1),
            "seo": seo,
            "revisit": revisit,
        }

    async def _gather_base_data(self, video: Video, access_token: str, start_date, end_date):
        """Analytics API 호출 + concept 계산 병렬 실행"""
        import asyncio
        return await asyncio.gather(
            analytics_service.get_youtube_analytics_data(
                access_token=access_token,
                video_id=video.youtube_video_id,
                metrics="views,averageViewDuration,likes,shares,subscribersGained,impressionClickThroughRate",
                start_date=start_date,
                end_date=end_date,
            ),
            self._analyze_concept(video),
        )

    async def _analyze_concept(self, video: Video) -> float:
        """채널 일관성 — 제목+설명+태그 임베딩 코사인 유사도 (현재 영상 제외)"""
        videos = await self.video_repository.find_by_channel_id(video.channel_id)
        other_videos = [v for v in videos if v.id != video.id]

        if not other_videos:
            return 100.0

        target_text = f"{video.title} {video.description}"
        target_embedding = await self.content_chunk_repository.generate_embedding(target_text)

        scores = []
        for v in other_videos:
            other_text = f"{v.title} {v.description}"
            other_embedding = await self.content_chunk_repository.generate_embedding(other_text)
            dot = np.dot(target_embedding, other_embedding)
            norm = np.linalg.norm(target_embedding) * np.linalg.norm(other_embedding)
            scores.append(dot / norm if norm != 0 else 0)

        return float(np.mean(scores) * 100)

    async def _calculate_seo(self, analytics_data: dict, video_detail: dict, video: Video) -> float:
        """SEO 하이브리드 점수 (수치 50점 + 정성 50점)"""
        numeric_score = self._calculate_seo_numeric(analytics_data, video_detail)
        qualitative = await self.rag_service.evaluate_seo_qualitative(video_detail)
        qualitative_score = qualitative.get("score", 0)
        return round(numeric_score + qualitative_score, 1)

    def _calculate_seo_numeric(self, analytics_data: dict, video_detail: dict) -> float:
        """수치 기반 SEO 점수 (0~50점): CTR + 시청지속률"""
        rows = analytics_data.get("rows", [[]])
        if not rows:
            return 0.0

        row = rows[0]
        avg_view_duration = row[1] if len(row) > 1 else 0
        ctr = row[5] if len(row) > 5 else 0  # impressionClickThroughRate

        duration_str = video_detail.get("duration", "PT0S")
        try:
            total_seconds = isodate.parse_duration(duration_str).total_seconds()
        except Exception:
            total_seconds = 1

        watch_ratio = min(avg_view_duration / total_seconds, 1.0) if total_seconds else 0
        ctr_normalized = min(ctr / 10.0, 1.0)  # CTR 10%를 만점 기준

        # 시청지속률 30점 + CTR 20점
        return round(watch_ratio * 30 + ctr_normalized * 20, 1)

    def _calculate_revisit(self, video: Video, analytics_data: dict) -> float:
        """재방문률 = (좋아요 + 공유 + 구독) / 조회수"""
        if not video.view:
            return 0.0
        rows = analytics_data.get("rows", [[]])
        row = rows[0] if rows else []
        shares = row[3] if len(row) > 3 else 0
        subscribers_gained = row[4] if len(row) > 4 else 0
        revisit = ((video.like_count or 0) + shares + subscribers_gained) / video.view
        return round(revisit * 100, 2)

    async def _get_channel_averages(self, video: Video) -> dict:
        """채널 내 평균값 (현재 영상 제외)"""
        videos = await self.video_repository.find_by_channel_id(video.channel_id)
        others = [v for v in videos if v.id != video.id]

        if not others:
            return {"view_avg": 0.0, "like_avg": 0.0, "comment_avg": 0.0}

        return {
            "view_avg": round(sum(v.view for v in others) / len(others), 1),
            "like_avg": round(sum(v.like_count for v in others) / len(others), 1),
            "comment_avg": round(sum(v.comment_count for v in others) / len(others), 1),
        }
