import logging
import os
from datetime import datetime
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

POPULAR_COUNT = 150
RECENT_COUNT = 50


class YoutubeCommentService:
    """YouTube 댓글 처리 서비스"""

    def __init__(self):
        self.api_key = os.getenv('YOUTUBE_API_KEY')
        self.youtube = build('youtube', 'v3', developerKey=self.api_key)

    async def get_comments(
        self,
        video_id: str,
        report_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[dict]:
        """인기순 150개 + 최신순 50개 수집 후 기간 필터링"""
        popular = await self._fetch_comments(video_id, report_id, order="relevance", max_count=POPULAR_COUNT)
        recent = await self._fetch_comments(video_id, report_id, order="time", max_count=RECENT_COUNT)

        # 중복 제거 (content 기준)
        seen = {c["content"] for c in popular}
        unique_recent = [c for c in recent if c["content"] not in seen]
        all_comments = popular + unique_recent

        if start_date or end_date:
            all_comments = self._filter_by_period(all_comments, start_date, end_date)

        return all_comments

    async def get_total_comment_count(self, video_id: str) -> int:
        """YouTube stats에서 실제 총 댓글 수 조회"""
        try:
            response = self.youtube.videos().list(
                part="statistics",
                id=video_id,
            ).execute()
            items = response.get("items", [])
            if not items:
                return 0
            return int(items[0]["statistics"].get("commentCount", 0))
        except Exception as e:
            logger.error("총 댓글 수 조회 실패: %s", e)
            return 0

    async def _fetch_comments(
        self,
        video_id: str,
        report_id: int,
        order: str,
        max_count: int,
    ) -> list[dict]:
        comments = []
        page_count = 0
        max_pages = (max_count + 99) // 100

        try:
            response = self.youtube.commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                order=order,
                maxResults=min(max_count, 100),
            ).execute()
        except HttpError as e:
            logger.error("YouTube API 에러: %s", e)
            if e.resp.status == 403 and "commentsDisabled" in str(e):
                logger.warning("비디오 %s 댓글 비활성화", video_id)
                return []
            raise
        except Exception as e:
            logger.error("YouTube 댓글 가져오기 실패: %s", e)
            return []

        while response and len(comments) < max_count and page_count < max_pages:
            for item in response["items"]:
                if len(comments) >= max_count:
                    break
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "comment_type": None,
                    "content": snippet["textDisplay"],
                    "author": snippet["authorDisplayName"],
                    "published_at": snippet["publishedAt"],
                    "like_count": snippet["likeCount"],
                    "report_id": report_id,
                })

                if item["snippet"]["totalReplyCount"] > 0 and "replies" in item:
                    for reply_item in item["replies"]["comments"]:
                        if len(comments) >= max_count:
                            break
                        reply = reply_item["snippet"]
                        comments.append({
                            "comment_type": None,
                            "content": reply["textDisplay"],
                            "author": reply["authorDisplayName"],
                            "published_at": reply["publishedAt"],
                            "like_count": reply["likeCount"],
                            "report_id": report_id,
                        })

            if len(comments) >= max_count or "nextPageToken" not in response:
                break

            page_count += 1
            try:
                response = self.youtube.commentThreads().list(
                    part="snippet,replies",
                    videoId=video_id,
                    order=order,
                    pageToken=response["nextPageToken"],
                    maxResults=100,
                ).execute()
            except HttpError as e:
                if e.resp.status == 400:
                    logger.warning("pageToken 에러, 수집 중단: %s", e)
                    break
                raise

        return comments

    def _filter_by_period(
        self,
        comments: list[dict],
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> list[dict]:
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59) if end_date else None

        filtered = []
        for c in comments:
            try:
                published = datetime.fromisoformat(c["published_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                if start and published < start:
                    continue
                if end and published > end:
                    continue
                filtered.append(c)
            except Exception:
                filtered.append(c)
        return filtered
