from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from domain.trend_keyword.model.trend_keyword_type import TrendKeywordType
from core.utils.datetime_utils import get_kst_now_naive
from sqlalchemy import Column, Enum as SAEnum



class TrendKeyword(SQLModel, table=True):
    """TrendKeyword 테이블 모델 - 리포트별 트렌드 키워드 저장"""
    __tablename__ = "trend_keyword"
    
    # Primary Key
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Foreign Key - Channel 테이블 참조
    # null 허용이므로, optional
    channel_id: Optional[int] = Field(
        default=None,
        description="연관된 채널 ID (null 허용)"
    )
    
    # 키워드 타입
    keyword_type: TrendKeywordType = Field(
        sa_column=Column(
            SAEnum(TrendKeywordType, name="trendkeywordtype", native_enum=False),
            nullable=False
        )
    )
    
    # 키워드 정보
    keyword: str = Field(
        max_length=255,
        description="트렌드 키워드"
    )
    
    # 점수
    score: int = Field(
        description="키워드 관련성 점수 (0-100)"
    )
    
    # 키워드 트렌드 시작 시각 (Google Trends start_timestamp)
    started_at: Optional[datetime] = Field(default=None)

    # 직전 수집 점수 (점수 변동 비교용)
    previous_score: Optional[int] = Field(default=None)

    # BaseEntity 상속 부분 (created_at, updated_at)
    created_at: Optional[datetime] = Field(default_factory=get_kst_now_naive)
    updated_at: Optional[datetime] = Field(default_factory=get_kst_now_naive)