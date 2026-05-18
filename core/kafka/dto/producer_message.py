from pydantic import BaseModel
from enum import Enum
from typing import Any, Optional, List, Dict


class Step(Enum):
    overview = "overview"
    analysis = "analysis"


class ScriptSection(BaseModel):
    """영상 스크립트 구간"""
    time: str
    title: str
    content: str


class RepresentativeComment(BaseModel):
    """직접 인용 댓글"""
    category: str
    content: str
    author: str
    published_at: str
    like_count: int


class CommentAnalysis(BaseModel):
    """댓글 분석 결과"""
    total_comment_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    advice_count: int
    positive_pct: float
    negative_pct: float
    neutral_pct: float
    advice_pct: float
    representative_comments: List[RepresentativeComment]
    category_summaries: Dict[str, str]


class Metrics(BaseModel):
    """영상 수치 지표"""
    view: int
    view_channel_avg: float
    like_count: int
    like_channel_avg: float
    comment_count: int
    comment_channel_avg: float
    concept: float
    seo: float
    revisit: float


class ReportSummary(BaseModel):
    """리포트 요약 (개요/이탈/SEO)"""
    title: str
    content: str
    tag: str


class OverviewResult(BaseModel):
    """overview 단계 결과"""
    summary: List[ScriptSection]
    metrics: Metrics
    comment_analysis: CommentAnalysis
    overview_summary: ReportSummary


class AnalysisResult(BaseModel):
    """analysis 단계 결과"""
    viewer_retention: Optional[str] = None
    optimization: Optional[str] = None


class Message(BaseModel):
    """Kafka 결과 메시지"""
    is_success: bool
    task_id: int
    report_id: int
    step: Step
    result: Optional[Any] = None


# 하위 호환 유지
class CommentSummaryItem(BaseModel):
    comment_type: str
    content: str
