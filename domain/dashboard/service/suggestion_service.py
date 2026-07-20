"""대시보드 suggestion 카드 생성 (LLM) — 역주행 + 트렌드 브릿지 + 댓글 인사이트.

각 카드는 독립적으로 생성되며(try/except), 데이터가 없으면 그 카드만 skip 한다.
출력은 dashboard_message.SuggestionItem 리스트.

설계 결정 (PM 문서 Part 3):
  ① "예상 효과"는 단정적 수치(%) 대신 **정성/예상 표현**만 (프롬프트로 강제) — 가짜 정밀도 방지.
  ② 데이터 없는 카드는 **skip** (역주행 후보 없음 / 트렌드 키워드 없음 / 댓글 없음).
  ③ 협업 등 데이터 부재 항목은 미포함 (Phase 3).

카드1(AI 컨텍스트 인사이트) 슬롯 우선순위 — 항상 정확히 1장 생성(AI_CONTEXT_INSIGHT_SPEC.md):
  1. VIRAL_VIDEO       : 역주행(재유입) 영상 활용 — Analytics 영상별 조회수로 탐지 (`viral_detector`).
  2. CONTENT_EFFICIENCY: 콘텐츠 효율 진단 — 카테고리별 조회수/구독전환 불균형 탐지
                          (`content_efficiency_detector`). 역주행 후보 없을 때 시도.
  3. GENERAL_GROWTH    : 일반 성장 분석 — 위 둘 다 없을 때의 최종 안전망(fallback).

카드2·3 (독립, 폴백 없음):
  - TREND_KEYWORD    : 트렌드 브릿지 — 실시간 트렌드 키워드 × 채널 컨셉.
  - COMMENT_SENTIMENT: 댓글 인사이트 — 저장된 분류 댓글 여론.
"""

import json
import logging
from typing import Optional

from core.kafka.dto.dashboard_message import SuggestionItem
from core.utils.datetime_utils import get_kst_now_naive
from domain.dashboard.service import content_efficiency_detector, viral_detector
from domain.trend_keyword.repository.trend_keyword_repository import TrendKeywordRepository
from domain.video.repository.video_repository import VideoRepository
from external.rag.rag_service_impl import RagServiceImpl
from external.youtube.youtube_comment_service import YoutubeCommentService

logger = logging.getLogger(__name__)

# 댓글 인사이트 라이브 수집 파라미터
RECENT_MONTHS_DAYS = 90       # "최근 3개월" 업로드 기준
TOP_RECENT_VIDEOS = 5         # 3개월내 조회수 상위 N개
FALLBACK_TOP_VIDEOS = 3       # 3개월내 영상 없을 때 채널 전체 조회수 상위 N개
PER_VIDEO_COMMENTS = 50       # 영상당 relevance 댓글 수
MAX_COMMENTS_FOR_LLM = 120    # LLM 프롬프트 크기 상한 (합산 후 좋아요순 컷)


_QUALITATIVE_RULE = (
    "중요: projectedMetrics의 value는 '+15%' 같은 단정적 수치를 절대 쓰지 말고, "
    "'상승 기대','증가 예상','개선 여지'처럼 정성적·예상 표현만 써라. "
    "데이터로 검증되지 않은 수치를 지어내지 마라. 모든 응답은 한국어."
)

_TREND_PROMPT = """너는 유튜브 채널 성장 코치다. 아래 채널에 맞는 '트렌드 브릿지' 조언 카드 1장을 만들어라.

채널명: {name}
채널 컨셉: {concept}
타겟 시청자: {target}
최근 급상승 트렌드 키워드: {keywords}

위 트렌드 키워드 중 이 채널의 컨셉/타겟과 가장 잘 맞는 것을 골라,
기존 시청자를 유지하면서 신규 유입을 늘릴 수 있는 '브릿지 콘텐츠' 방향을 제안하라.

반드시 아래 JSON 형식으로만 답하라(JSON 외 다른 말 금지):
{{
  "title": "20자 내외 카드 제목",
  "summary": "어떤 트렌드 키워드를 왜 골랐는지 매칭 근거를 담은 2~3문장 (최대 500자)",
  "detailAnalysis": "구체적 실행 방향 3~4문장",
  "tips": ["실행 팁1", "실행 팁2"],
  "projectedMetrics": [{{"label":"노출 클릭률","value":"상승 기대"}}, {{"label":"신규 시청자 유입","value":"증가 예상"}}]
}}

""" + _QUALITATIVE_RULE

_COMMENT_PROMPT = """너는 유튜브 채널 성장 코치다. 아래는 채널 '{concept}'의 인기 영상 시청자 댓글이다 (좋아요 많은 순).
각 줄은 (♥좋아요수) 댓글내용 형식이다.

{comments}

이 댓글들에서 (1) 전반적 시청자 만족/불만 분위기와 (2) 반복 언급되는 요구사항(개선점·다뤄달라는 주제)을 직접 판단해 뽑아
'댓글 인사이트' 조언 카드 1장을 만들어라. (좋아요가 많은 댓글일수록 더 많은 시청자의 의견으로 간주하라.)

반드시 아래 JSON 형식으로만 답하라(JSON 외 다른 말 금지):
{{
  "title": "20자 내외 카드 제목",
  "summary": "만족도 분위기 + 핵심 요구사항을 담은 2~3문장 (최대 500자)",
  "detailAnalysis": "어떻게 반응/대응하면 좋을지 3~4문장",
  "tips": ["실행 팁1", "실행 팁2"],
  "projectedMetrics": [{{"label":"시청 지속 시간","value":"개선 기대"}}, {{"label":"팬덤 충성도","value":"상승 예상"}}]
}}

""" + _QUALITATIVE_RULE

_VIRAL_PROMPT = """너는 유튜브 채널 성장 코치다. 아래 채널에서 '역주행(재유입)' 신호가 잡힌 과거 영상에 대한 조언 카드 1장을 만들어라.

채널 컨셉: {concept}
타겟 시청자: {target}

[역주행 영상]
- 제목: {title}
- 업로드: 약 {age_months}개월 전
- 최근 28일 조회수: {recent_views}회 (이 영상 생애 일평균 대비 약 {ratio}배로 다시 조회가 몰리는 중)

오래된 영상이 지금 다시 주목받는 흐름을 활용해, 재유입을 더 키우고 채널 성장으로 연결할 방향을 제안하라.
(예: 후속/리메이크 콘텐츠, 관련 숏츠 제작, 설명란·고정댓글·재생목록 최적화로 추가 영상 연결 등)

반드시 아래 JSON 형식으로만 답하라(JSON 외 다른 말 금지):
{{
  "title": "20자 내외 카드 제목",
  "summary": "어떤 영상이 왜 역주행 중인지와 활용 방향을 담은 2~3문장 (최대 500자)",
  "detailAnalysis": "구체적 실행 방향 3~4문장",
  "tips": ["실행 팁1", "실행 팁2"],
  "projectedMetrics": [{{"label":"재유입 조회수","value":"상승 기대"}}, {{"label":"채널 유입","value":"증가 예상"}}]
}}

""" + _QUALITATIVE_RULE

_CONTENT_EFFICIENCY_PROMPT = """너는 유튜브 채널 성장 코치다. 아래 채널에서 '콘텐츠 효율 불균형'
신호가 잡혔다 — 조회수를 제일 많이 끄는 카테고리와 구독 전환을 제일 많이 만드는 카테고리가 다르다.
이에 대한 조언 카드 1장을 만들어라.

채널 컨셉: {concept}
타겟 시청자: {target}

[분석 기간: 최근 {window_days}일]
- 조회수 견인 카테고리: '{view_label}' (전체 조회수의 {view_share:.0f}%, 정작 구독전환 기여는 {view_leader_sub_share:.0f}%뿐)
- 구독전환 견인 카테고리: '{sub_label}' (전체 구독전환의 {sub_share:.0f}%, 정작 조회수 비중은 {sub_leader_view_share:.0f}%뿐)

단순 노출용 콘텐츠와 실제 팬(구독자)을 만드는 콘텐츠 사이의 역할 분담이 필요한 시점이다.
구독전환 효율이 높은 '{sub_label}' 카테고리의 제작 비중을 늘리는 방향을 중심으로 제안하라.

반드시 아래 JSON 형식으로만 답하라(JSON 외 다른 말 금지):
{{
  "title": "20자 내외 카드 제목",
  "summary": "두 카테고리의 조회수/구독전환 역할 차이를 담은 2~3문장 (최대 500자)",
  "detailAnalysis": "구체적 실행 방향 3~4문장",
  "tips": ["실행 팁1", "실행 팁2"],
  "projectedMetrics": [{{"label":"구독 전환 효율","value":"개선 기대"}}, {{"label":"제작 리소스 효율","value":"개선 여지"}}]
}}

""" + _QUALITATIVE_RULE

_GENERAL_GROWTH_PROMPT = """너는 유튜브 채널 성장 코치다. 아래 채널은 역주행처럼 특별한 신호는
없는 평소 상태다. 최근 성장 지표를 바탕으로 '현재 채널 상황 진단 및 성장 제안' 카드 1장을 만들어라.

채널명: {name}
채널 컨셉: {concept}
타겟 시청자: {target}

최근 지표 (0~100점, "평소만큼"이 80점 기준. 데이터 부족/미제공은 '데이터 없음'):
{score_summary}

지침:
- 지표가 준수하면(대체로 40점 이상), 어떤 지표가 특히 좋은지 근거로 들어 안정적인 상태임을
  알리고 다음 단계로 시도해볼 만한 것을 제안하라.
- 지표가 낮거나(0점) '데이터 없음'이 많으면, 실패라 단정하지 말고 "아직 판단할 데이터가 부족한
  상태"임을 인정한 뒤, 지금 시도해볼 수 있는 기본기(꾸준한 업로드, 영상 초반 후킹 강화 등)를
  제안하라. 있지도 않은 성과를 지어내지 마라.
- "클릭률"·"노출수" 같은 노출 기반 지표는 언급하지 마라(수익화 채널 전용이라 이 데이터가 없다).
  시청 몰입(시청 지속률) 등 위에 제공된 지표만 근거로 사용하라.

반드시 아래 JSON 형식으로만 답하라(JSON 외 다른 말 금지):
{{
  "title": "20자 내외 카드 제목",
  "summary": "현재 채널 상태 요약 + 다음 방향을 담은 2~3문장 (최대 500자)",
  "detailAnalysis": "구체적 실행 방향 3~4문장",
  "tips": ["실행 팁1", "실행 팁2"],
  "projectedMetrics": [{{"label":"채널 성장","value":"개선 여지"}}]
}}

""" + _QUALITATIVE_RULE

_SITUATION_SUMMARY_PROMPT = """너는 유튜브 채널 성장 코치다. 아래는 이 채널에 대해 이미 분석된
사실들이다. 이 사실들'만' 근거로 삼아, 지금 채널 상태를 진단하는 종합 요약을 작성하라.

문체 가이드 (여러 사실을 한 문장에 엮어 자신감 있게 진단하는 톤 — 아래 예시의 소재·숫자는
문체 참고용일 뿐, 그대로 베끼거나 채널에 없는 숫자를 새로 지어내지 마라):
  예) "○○ 콘텐츠가 조회수를 견인하지만 구독 전환은 △△가 담당하며, 전반적으로는 완만한
      성장 곡선을 그리고 있는 단계입니다."
  예) "업로드 주기와 시청 지속률이 안정적으로 유지되며 견조한 성장세를 보이는 상태입니다."

채널명: {name}
채널 컨셉: {concept}

[보유 지표] (여기 없는 지표는 데이터가 없다는 뜻이니 언급하지 마라)
{available_scores}

[생성된 조언 카드]
{card_summaries}

지침:
- 위 문체처럼 여러 사실을 하나의 흐름으로 엮되, 숫자는 [보유 지표]/[생성된 조언 카드]에
  나온 것만 인용하라.
- 여기 없는 수치(특정 영상의 조회수 증가율, 재방문율, 시청자 잔존율, 만족도% 등)는 채널
  단위로 우리가 갖고 있지 않다. 절대로 새로운 수치를 지어내지 마라.
- 지표가 부족하거나 낮아도 실패로 단정하지 말고, "~단계", "~상태" 같은 진단형 어미로
  1~2문장에 마무리하라.

반드시 아래 JSON 형식으로만 답하라(JSON 외 다른 말 금지):
{{"summary": "종합 요약 문장"}}
"""

_SCORE_LABELS = {
    "growth": "채널 성장",
    "algorithm": "알고리즘",
    "retention": "시청 몰입",
    "engagement": "반응 밀도",
    "inflow": "유입 활력",
    "upload": "업로드 성실도",
}


def _format_score_summary(scores: dict) -> str:
    lines = []
    for key, label in _SCORE_LABELS.items():
        score = (scores.get(key) or {}).get("score")
        lines.append(f"- {label}: {'데이터 없음' if score is None else f'{score}점'}")
    return "\n".join(lines)


def _format_available_scores(scores: dict) -> str:
    """null인 지표는 아예 제외하고 있는 것만 나열 (situation summary 전용, SITUATION_SUMMARY_SPEC.md §3-1)."""
    lines = [
        f"- {label}: {(scores.get(key) or {}).get('score')}점"
        for key, label in _SCORE_LABELS.items()
        if (scores.get(key) or {}).get("score") is not None
    ]
    return "\n".join(lines) if lines else "(보유 지표 없음)"


_SUGGESTION_TYPE_LABELS = {
    "VIRAL_VIDEO": "역주행",
    "CONTENT_EFFICIENCY": "콘텐츠 효율 진단",
    "GENERAL_GROWTH": "일반 성장 분석",
    "TREND_KEYWORD": "트렌드 브릿지",
    "COMMENT_SENTIMENT": "댓글 인사이트",
}


def _format_cards_for_summary(items: list[SuggestionItem]) -> str:
    """방금 생성된 카드들의 title+summary를 그대로 나열 (새 사실 지어내지 않고 재사용)."""
    blocks = []
    for item in items:
        label = _SUGGESTION_TYPE_LABELS.get(item.type, item.type)
        blocks.append(f"[{label}] {item.title} — {item.summary}")
    return "\n".join(blocks) if blocks else "(생성된 카드 없음)"


def _parse_card_json(raw: str) -> Optional[dict]:
    try:
        s = raw.strip().replace("```json", "").replace("```", "")
        return json.loads(s)
    except Exception as e:
        logger.warning("[Dashboard] suggestion JSON 파싱 실패: %r / raw=%.200s", e, raw)
        return None


def _to_item(type_str: str, card: dict) -> Optional[SuggestionItem]:
    title = (card.get("title") or "").strip()
    summary = (card.get("summary") or "").strip()
    if not title or not summary:
        return None
    return SuggestionItem(
        type=type_str,
        title=title[:100],
        summary=summary[:500],
        projected_metrics=card.get("projectedMetrics"),
        detail_analysis=card.get("detailAnalysis"),
        tips=card.get("tips"),
    )


class SuggestionService:
    def __init__(self):
        self.rag = RagServiceImpl()
        self.trend_repo = TrendKeywordRepository()
        self.video_repo = VideoRepository()
        self.youtube_comment_service = YoutubeCommentService()

    async def generate(self, channel, scores, day_map, access_token=None) -> list[SuggestionItem]:
        """카드 3종 생성. 카드별 독립 — 하나 실패/데이터없음이어도 나머지 발행.

        카드1(AI 컨텍스트 인사이트)은 역주행 → 콘텐츠효율 → 일반성장 순으로 시도해 빈 슬롯으로
        skip하지 않고 항상 1장 생성한다(AI_CONTEXT_INSIGHT_SPEC.md). 셋 다 실패하면(이론상 일반성장이
        최종 안전망이라 거의 발생하지 않아야 함) 카드1이 비었다는 사실을 로그로 남긴다.
        """
        items: list[SuggestionItem] = []
        channel_id = getattr(channel, "id", None)

        # 카드1: 역주행 → 콘텐츠효율 → 일반성장 순으로 시도, 처음 성공한 것을 채택
        try:
            card1 = await self._viral_video(channel, access_token)
        except Exception as e:
            logger.warning("[Dashboard] suggestion 카드 생성 실패(viral_video) - channel_id=%s: %r",
                           channel_id, e)
            card1 = None

        if card1 is None:
            try:
                card1 = await self._content_efficiency(channel, access_token)
            except Exception as e:
                logger.warning("[Dashboard] suggestion 카드 생성 실패(content_efficiency) - channel_id=%s: %r",
                               channel_id, e)
                card1 = None

        if card1 is None:
            try:
                card1 = await self._general_growth(channel, scores)
            except Exception as e:
                logger.warning("[Dashboard] suggestion 카드 생성 실패(general_growth) - channel_id=%s: %r",
                               channel_id, e)
                card1 = None

        if card1:
            items.append(card1)
        else:
            logger.error("[Dashboard] 카드1(AI 컨텍스트 인사이트) 전부 실패 - 역주행/콘텐츠효율/일반성장 "
                         "3가지 다 실패해 빈 슬롯으로 발행됨 - channel_id=%s", channel_id)

        # 카드2·3: 기존 그대로, 독립적 — 하나 실패/데이터없음이어도 나머지 발행
        cards = [
            ("trend_bridge", lambda: self._trend_bridge(channel)),
            ("comment_insight", lambda: self._comment_insight(channel)),
        ]
        for name, factory in cards:
            try:
                item = await factory()
                if item:
                    items.append(item)
            except Exception as e:
                logger.warning("[Dashboard] suggestion 카드 생성 실패(%s) - channel_id=%s: %r",
                               name, channel_id, e)
        return items

    async def summarize_situation(self, channel, scores, items: list[SuggestionItem]) -> Optional[str]:
        """"현재 채널 상황 정리" 종합 문단 생성 (SITUATION_SUMMARY_SPEC.md).

        카드 생성이 이미 끝난 뒤의 독립적인 후처리 — 실패해도 카드 발행에는 영향 없음(호출부에서
        try/except로 격리해야 함). 분석 기반 1(카드)+3(점수)만 사용, 새 사실을 지어내지 않도록
        이미 생성된 카드 텍스트와 null 아닌 점수만 근거로 준다.
        """
        if not items:
            logger.info("[Dashboard] 카드 없음 → situation summary skip (channel_id=%s)",
                        getattr(channel, "id", None))
            return None

        prompt = _SITUATION_SUMMARY_PROMPT.format(
            name=getattr(channel, "name", "") or "",
            concept=getattr(channel, "concept", None) or "미설정",
            available_scores=_format_available_scores(scores),
            card_summaries=_format_cards_for_summary(items),
        )
        raw = await self.rag.execute_llm_direct(prompt)
        parsed = _parse_card_json(raw)
        summary = (parsed or {}).get("summary")
        return summary.strip() if isinstance(summary, str) and summary.strip() else None

    # ── 카드: 역주행 영상 ──────────────────────────────────────────────────
    async def _viral_video(self, channel, access_token) -> Optional[SuggestionItem]:
        if not access_token:
            logger.info("[Dashboard] access_token 없음 → 역주행 카드 skip (channel_id=%s)", channel.id)
            return None

        videos = await self.video_repo.find_by_channel_id(channel.id)
        if not videos:
            logger.info("[Dashboard] 영상 없음 → 역주행 카드 skip (channel_id=%s)", channel.id)
            return None

        today_kst = get_kst_now_naive().date()
        candidates = await viral_detector.detect_resurgent_videos(access_token, videos, today_kst)
        if not candidates:
            logger.info("[Dashboard] 역주행 후보 없음 → 역주행 카드 skip (channel_id=%s)", channel.id)
            return None

        top = candidates[0]
        prompt = _VIRAL_PROMPT.format(
            concept=getattr(channel, "concept", None) or "미설정",
            target=getattr(channel, "target", None) or "미설정",
            title=top["title"] or "(제목 없음)",
            age_months=max(1, round(top["age_days"] / 30)),
            recent_views=top["recent_views"],
            ratio=top["ratio"],
        )
        raw = await self.rag.execute_llm_direct(prompt)
        card = _parse_card_json(raw)
        return _to_item("VIRAL_VIDEO", card) if card else None

    # ── 카드: 콘텐츠 효율 진단 (역주행 없을 때 2순위) ────────────────────────
    async def _content_efficiency(self, channel, access_token) -> Optional[SuggestionItem]:
        if not access_token:
            logger.info("[Dashboard] access_token 없음 → 콘텐츠효율 카드 skip (channel_id=%s)", channel.id)
            return None

        videos = await self.video_repo.find_by_channel_id(channel.id)
        if not videos:
            logger.info("[Dashboard] 영상 없음 → 콘텐츠효율 카드 skip (channel_id=%s)", channel.id)
            return None

        today_kst = get_kst_now_naive().date()
        result = await content_efficiency_detector.detect_content_imbalance(access_token, videos, today_kst)
        if not result:
            # 상세 사유는 content_efficiency_detector 내부에서 이미 로깅함
            return None

        view_leader = result["view_leader"]
        sub_leader = result["sub_leader"]
        prompt = _CONTENT_EFFICIENCY_PROMPT.format(
            concept=getattr(channel, "concept", None) or "미설정",
            target=getattr(channel, "target", None) or "미설정",
            window_days=content_efficiency_detector.WINDOW_DAYS,
            view_label=view_leader["label"],
            view_share=view_leader["view_share"] * 100,
            view_leader_sub_share=view_leader["sub_share"] * 100,
            sub_label=sub_leader["label"],
            sub_share=sub_leader["sub_share"] * 100,
            sub_leader_view_share=sub_leader["view_share"] * 100,
        )
        raw = await self.rag.execute_llm_direct(prompt)
        card = _parse_card_json(raw)
        return _to_item("CONTENT_EFFICIENCY", card) if card else None

    # ── 카드: 일반 성장 분석 (역주행 후보 없을 때의 안전망) ──────────────────
    async def _general_growth(self, channel, scores) -> Optional[SuggestionItem]:
        prompt = _GENERAL_GROWTH_PROMPT.format(
            name=getattr(channel, "name", "") or "",
            concept=getattr(channel, "concept", None) or "미설정",
            target=getattr(channel, "target", None) or "미설정",
            score_summary=_format_score_summary(scores),
        )
        raw = await self.rag.execute_llm_direct(prompt)
        card = _parse_card_json(raw)
        return _to_item("GENERAL_GROWTH", card) if card else None

    # ── 카드: 트렌드 브릿지 ────────────────────────────────────────────────
    async def _trend_bridge(self, channel) -> Optional[SuggestionItem]:
        keywords = await self.trend_repo.get_latest_real_time_keywords(5)
        if not keywords:
            logger.info("[Dashboard] 트렌드 키워드 없음 → 트렌드 카드 skip")
            return None

        prompt = _TREND_PROMPT.format(
            name=getattr(channel, "name", "") or "",
            concept=getattr(channel, "concept", None) or "미설정",
            target=getattr(channel, "target", None) or "미설정",
            keywords=", ".join(k.keyword for k in keywords),
        )
        raw = await self.rag.execute_llm_direct(prompt)
        card = _parse_card_json(raw)
        return _to_item("TREND_KEYWORD", card) if card else None

    # ── 카드: 댓글 인사이트 (유튜브 라이브 수집) ─────────────────────────────
    @staticmethod
    def _select_target_videos(videos: list) -> list:
        """댓글 수집 대상 영상 선정: 최근 3개월 업로드 중 조회수 top5.
        3개월내 영상이 없으면 채널 전체 조회수 top3로 fallback."""
        today = get_kst_now_naive().date()

        def _view(v):
            return getattr(v, "view", 0) or 0

        def _upload(v):
            ud = getattr(v, "upload_date", None)
            return ud.date() if hasattr(ud, "date") else ud

        recent = [v for v in videos if _upload(v) and (today - _upload(v)).days <= RECENT_MONTHS_DAYS]
        if recent:
            recent.sort(key=_view, reverse=True)
            return recent[:TOP_RECENT_VIDEOS]
        return sorted(videos, key=_view, reverse=True)[:FALLBACK_TOP_VIDEOS]

    async def _comment_insight(self, channel) -> Optional[SuggestionItem]:
        videos = await self.video_repo.find_by_channel_id(channel.id)
        if not videos:
            logger.info("[Dashboard] 영상 없음 → 댓글 카드 skip (channel_id=%s)", channel.id)
            return None

        targets = self._select_target_videos(videos)
        if not targets:
            logger.info("[Dashboard] 대상 영상 없음 → 댓글 카드 skip (channel_id=%s)", channel.id)
            return None

        # 영상별 relevance top50 라이브 수집 (개별 영상 실패는 무시)
        collected: list[dict] = []
        for v in targets:
            yid = getattr(v, "youtube_video_id", None)
            if not yid:
                continue
            try:
                collected.extend(
                    await self.youtube_comment_service.get_relevant_comments(yid, PER_VIDEO_COMMENTS)
                )
            except Exception as e:
                logger.warning("[Dashboard] 댓글 수집 실패(video=%s) - %r", yid, e)

        # content 기준 중복 제거 → 좋아요순 정렬 → LLM 상한 컷
        seen: set = set()
        deduped: list[dict] = []
        for c in collected:
            content = c.get("content", "")
            if content and content not in seen:
                seen.add(content)
                deduped.append(c)
        deduped.sort(key=lambda c: c.get("like_count", 0), reverse=True)
        top = deduped[:MAX_COMMENTS_FOR_LLM]

        if not top:
            logger.info("[Dashboard] 수집 댓글 없음 → 댓글 카드 skip (channel_id=%s)", channel.id)
            return None

        logger.info("[Dashboard] 댓글 라이브 수집 - 영상 %d개, 댓글 %d개 (channel_id=%s)",
                    len(targets), len(top), channel.id)

        lines = [f"(♥{c.get('like_count', 0)}) {c['content']}" for c in top]
        prompt = _COMMENT_PROMPT.format(
            concept=getattr(channel, "concept", None) or "미설정",
            comments="\n".join(lines),
        )
        raw = await self.rag.execute_llm_direct(prompt)
        card = _parse_card_json(raw)
        return _to_item("COMMENT_SENTIMENT", card) if card else None
