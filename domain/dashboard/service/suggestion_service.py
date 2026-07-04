"""대시보드 suggestion 카드 생성 (LLM) — 역주행 + 트렌드 브릿지 + 댓글 인사이트.

각 카드는 독립적으로 생성되며(try/except), 데이터가 없으면 그 카드만 skip 한다.
출력은 dashboard_message.SuggestionItem 리스트.

설계 결정 (PM 문서 Part 3):
  ① "예상 효과"는 단정적 수치(%) 대신 **정성/예상 표현**만 (프롬프트로 강제) — 가짜 정밀도 방지.
  ② 데이터 없는 카드는 **skip** (역주행 후보 없음 / 트렌드 키워드 없음 / 댓글 없음).
  ③ 협업 등 데이터 부재 항목은 미포함 (Phase 3).

카드 종류:
  - VIRAL_VIDEO      : 역주행(재유입) 영상 활용 — Analytics 영상별 조회수로 탐지 (`viral_detector`).
  - TREND_KEYWORD    : 트렌드 브릿지 — 실시간 트렌드 키워드 × 채널 컨셉.
  - COMMENT_SENTIMENT: 댓글 인사이트 — 저장된 분류 댓글 여론.
"""

import json
import logging
from typing import Optional

from core.kafka.dto.dashboard_message import SuggestionItem
from core.utils.datetime_utils import get_kst_now_naive
from domain.dashboard.service import viral_detector
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
        """카드 3종 생성. 카드별 독립 — 하나 실패/데이터없음이어도 나머지 발행."""
        items: list[SuggestionItem] = []
        cards = [
            ("viral_video", lambda: self._viral_video(channel, access_token)),
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
                               name, getattr(channel, "id", None), e)
        return items

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
