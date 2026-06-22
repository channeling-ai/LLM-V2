from datetime import datetime
from typing import Optional

from sqlalchemy import Column
from sqlmodel import SQLModel, Field

from core.enums.video_category import VideoCategory
from core.utils.datetime_utils import get_kst_now_naive
from sqlalchemy import Column, Enum as SAEnum



class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(description="채널 ID")
    youtube_video_id: str = Field(description="YouTube 비디오 ID")
    video_category: VideoCategory = Field(
        sa_column=Column(
            SAEnum(VideoCategory, name="videocategory", native_enum=False),
            nullable=False
        )
    )
    title: Optional[str] = Field(description="비디오 제목")
    view: Optional[int] = Field(description="조회수")
    like_count: Optional[int] = Field(description="좋아요 수")
    comment_count: Optional[int] = Field(description="댓글 수")
    link: Optional[str] = Field(description="비디오 링크")
    upload_date: Optional[datetime] = Field(description="업로드 날짜")
    thumbnail: Optional[str] = Field(description="썸네일 URL")
    description: Optional[str] = Field(description="비디오 설명")

    # BaseEntity 상속 부분 (created_at, updated_at)
    created_at: Optional[datetime] = Field(default_factory=get_kst_now_naive)
    updated_at: Optional[datetime] = Field(default_factory=get_kst_now_naive)
    # data v3
    # duration : Optional[int] = Field(description="비디오 길이 (초 단위)")
    # analytics 항목
    # share_count: Optional[int] = Field(description="공유 수")
    # average_view_duration: Optional[int] = Field(description="평균 시청 시간 (초)")
    # subscribers_gained: Optional[int] = Field(description="구독자 증가 수")
