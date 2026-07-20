"""대시보드 결과 메시지 DTO (FastAPI → Spring, dashboard-result-v3).

봉투(envelope)는 snake_case(Spring `DashboardResultMessage`의 @JsonProperty와 매핑),
result 내부는 camelCase(`CamelModel` + `model_dump(by_alias=True)`)로 직렬화한다.

step으로 점수/제안을 분리 발행 — 각 메시지가 Spring에서 독립 트랜잭션으로 처리된다.
  - step=scores      : 점수 6종 (빠름, 먼저). raw_metrics는 저장 안 함(슬림화).
  - step=suggestions : LLM suggestion 카드들 (느림, 나중)
"""

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel
from core.kafka.dto.producer_message import CamelModel


class DashboardStep(str, Enum):
    scores = "scores"
    suggestions = "suggestions"


# ── step=scores payload (camelCase) ──────────────────────────────────────

class ScoreItem(CamelModel):
    score: Optional[int] = None  # YPP 미지원·데이터 부족·신규 → None
    delta: Optional[int] = None


class DashboardScores(CamelModel):
    growth: ScoreItem
    algorithm: ScoreItem
    retention: ScoreItem
    engagement: ScoreItem
    inflow: ScoreItem
    upload: ScoreItem


class DashboardScoresPayload(CamelModel):
    scores: DashboardScores
    subscriber_delta: Optional[int] = None  # 한 달(28일) 구독자 순증감. 데이터 부족 → None


# ── step=suggestions payload (camelCase) ─────────────────────────────────

class SuggestionItem(CamelModel):
    type: str                          # VIRAL_VIDEO | TREND_KEYWORD | COMMENT_SENTIMENT
    title: str
    summary: str
    projected_metrics: Any = None      # [{label, value}, ...]
    detail_analysis: Optional[str] = None
    tips: Any = None                   # ["팁1", "팁2", ...]


class DashboardSuggestionsPayload(CamelModel):
    suggestions: List[SuggestionItem]
    summary_message: Optional[str] = None  # "현재 채널 상황 정리" 종합 문단. 생성 실패 시 None


# ── 봉투 (snake_case) ────────────────────────────────────────────────────

class DashboardMessage(BaseModel):
    """dashboard-result-v3로 발행되는 결과 메시지. result는 step별 payload를
    model_dump(by_alias=True)로 camelCase 직렬화한 dict를 담는다."""
    is_success: bool
    step: DashboardStep
    channel_id: int
    dashboard_date: str                # yyyy-MM-dd (KST)
    result: Optional[Any] = None
