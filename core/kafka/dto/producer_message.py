from pydantic import BaseModel
from enum import Enum
from typing import Any, Optional, List



class CommentSummaryItem(BaseModel):
    """댓글 요약 항목"""
    comment_type: str
    content: str


class Step(Enum):
    """Kafka 메시지의 단계"""
    overview = "overview"
    analysis = "analysis"


class Message(BaseModel):
    """Kafka 메시지의 기본 클래스"""
    is_success: bool
    task_id: int
    report_id: int
    step: Step
    result: Optional[Any] = None


class OverviewResult(BaseModel):
    """overview 단계 결과"""
    summary: Optional[str] = None
    comment_analysis: Optional[str] = None
    metrics: Optional[dict] = None


class AnalysisResult(BaseModel):
    """analysis 단계 결과"""
    viewer_retention: Optional[str] = None
    optimization: Optional[str] = None