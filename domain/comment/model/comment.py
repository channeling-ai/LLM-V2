from sqlmodel import SQLModel, Field, Column
from datetime import datetime
from typing import Optional
from domain.comment.model.comment_type import CommentType
from core.utils.datetime_utils import get_kst_now_naive
from sqlalchemy import Column, Enum as SAEnum



class Comment(SQLModel, table=True):
    """댓글 모델 - SQLModel로 정의"""
    __tablename__ = "comment"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="report.id", description="리포트 ID")
    comment_type: CommentType = Field(
        sa_column=Column(
            SAEnum(CommentType, name="commenttype", native_enum=False),
            nullable=False
        )
    )
    content: str = Field(description="댓글 내용")
    author: Optional[str] = Field(default=None, description="댓글 작성자")
    like_count: Optional[int] = Field(default=None, description="댓글 좋아요 수")
    is_representative: bool = Field(default=False, description="대표 댓글 여부")

    # BaseEntity 상속 부분 (created_at, updated_at)
    created_at: Optional[datetime] = Field(default_factory=get_kst_now_naive)
    updated_at: Optional[datetime] = Field(default_factory=get_kst_now_naive)
