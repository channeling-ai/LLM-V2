from enum import Enum
from typing import Any, Optional, List, Dict
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """camelCase 직렬화 베이스 모델 (Spring 호환)"""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


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



# ── Analysis — ViewerRetentionAnalysis ───────────────────────────────────────

class CriticalSection(CamelModel):
    """최대 이탈 구간 — build_critical_section() 결과와 1:1 매핑"""
    start_time: str   # "01:06"
    end_time: str     # "01:45"
    duration: int     # 초 단위 정수


class RetentionGraphPoint(CamelModel):
    """retentionGraph 눈금 1개 — build_retention_graph() 결과 항목과 1:1 매핑"""
    time: str          # "1:24" (M:SS)
    retention_rate: int  # 0~100


class AnalysisItem(CamelModel):
    """causes / improvements 항목 1개"""
    title: str
    description: str


class ViewerRetentionAnalysis(CamelModel):
    critical_section: CriticalSection
    retention_graph: List[RetentionGraphPoint]
    causes: List[AnalysisItem]
    improvements: List[AnalysisItem]
    expected_effect: str


# ── Analysis — AlgorithmOptimization ─────────────────────────────────────────

class IssueItem(CamelModel):
    """카테고리 내 이슈 항목"""
    type: str                    # "PROBLEM" | "IMPROVEMENT" | "CURRENT_STATUS"
    content: Optional[str] = None
    examples: Optional[str] = None


class CategoryItem(CamelModel):
    """알고리즘 최적화 카테고리 1개"""
    category: str   # "TITLE" | "DESCRIPTION" | "HASHTAG" | "THUMBNAIL" | "DURATION"
    score: int      # 0~10
    grade: str      # "NEEDS_IMPROVEMENT" | "NORMAL" | "GOOD"
    issues: List[IssueItem]


class AlgorithmOptimization(CamelModel):
    category_list: List[CategoryItem]
    additional_suggestions: List[str]

# ── Analysis 결과 통합 ────────────────────────────────────────────────────────

class AnalysisResult(CamelModel):
    # Kafka Message.result 에 담겨 Spring으로 전달되는 최종 payload
    report_id: int
    viewer_retention_analysis: Optional[ViewerRetentionAnalysis] = None
    algorithm_optimization: Optional[AlgorithmOptimization] = None


# ── Overview ────────────────────────────────────────────────────────
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
    seo_summary: Optional[ReportSummary] = None


class AnalysisResult(BaseModel):
    """analysis 단계 결과"""
    viewer_retention: Optional[str] = None
    optimization: Optional[str] = None

class CommentSummaryItem(BaseModel):
    comment_type: str
    content: str
