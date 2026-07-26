"""대시보드 요청 컨슈머 (dashboard-topic-v2 수신 → dashboard-result-v3 발행).

흐름:
  1. 채널 조회 + 윈도우 전체(118일) YouTube 수집 (DB 캐시 없음)
  2. 윈도우 롤링 SUM → 점수 계산 → step=scores 발행 (빠름, 먼저)
  3. suggestion LLM 생성(인프로세스 재시도) → step=suggestions 발행 (느림, 나중)

BaseConsumer는 예외를 삼키고 offset을 커밋(재처리 없음)하므로 핸들러가 자급자족한다:
  - suggestion은 2~3회 backoff 재시도, 소진 시 is_success=False 발행(테이블 미변경)
  - 점수는 이미 발행돼 영향 없음 → 다음날 로그인 게이트로 자연 복구
"""

import asyncio
import logging
import time
from datetime import date
from typing import Any, Dict

from core.config.kafka_config import kafka_config
from core.kafka.base_consumer import BaseConsumer
from core.kafka.dto.dashboard_message import (
    DashboardMessage,
    DashboardScores,
    DashboardScoresPayload,
    DashboardStep,
    DashboardSuggestionsPayload,
    GraphPoint,
    GraphPointScores,
    ScoreItem,
)
from core.kafka.kafka_broker import kafka_broker
from domain.channel.repository.channel_repository import ChannelRepository
from domain.dashboard.service import raw_metrics_collector
from domain.dashboard.service.score_calculation import (
    build_day_map,
    calculate_score_series,
    calculate_scores,
    calculate_subscriber_delta,
)
from domain.dashboard.service.suggestion_service import SuggestionService
from domain.video.repository.video_repository import VideoRepository

logger = logging.getLogger(__name__)

SUGGESTION_MAX_RETRY = 3
SUGGESTION_BACKOFF_SEC = 2


class DashboardConsumerImpl(BaseConsumer):
    def __init__(self, broker, group_id: str = kafka_config.dashboard_consumer_group_id):
        super().__init__(broker, group_id=group_id)
        self.channel_repository = ChannelRepository()
        self.video_repository = VideoRepository()
        self.suggestion_service = SuggestionService()

    async def handle_dashboard(self, message: Dict[str, Any]):
        start_time = time.time()
        channel_id = message.get("channel_id")
        dashboard_date_str = message.get("dashboard_date")
        token = message.get("google_access_token")
        # 토큰은 마스킹 — 존재 여부/길이만 로깅
        token_info = f"len={len(token)}" if token else "MISSING"
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("📥 [Dashboard] 요청 수신 - channel_id=%s, date=%s, token=%s",
                    channel_id, dashboard_date_str, token_info)
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if channel_id is None or dashboard_date_str is None or not token:
            logger.error("[Dashboard] ❌ 필수 필드 누락 - channel_id=%s, date=%s, token=%s",
                         channel_id, dashboard_date_str, token_info)
            return

        today = date.fromisoformat(dashboard_date_str)

        # ── step=scores ──────────────────────────────────────────────────
        try:
            t0 = time.time()
            channel = await self.channel_repository.find_by_id(channel_id)
            if not channel:
                logger.error("[Dashboard] ❌ 채널 없음 - channel_id=%s", channel_id)
                return

            join_date = channel.join_date.date() if hasattr(channel.join_date, "date") else channel.join_date
            logger.info("[Dashboard] 1️⃣ 채널 로드 - id=%s, name='%s', join_date=%s (%.0fms)",
                        channel_id, getattr(channel, "name", "?"), join_date, (time.time() - t0) * 1000)

            t0 = time.time()
            upload_counts = await self._upload_counts(channel_id)
            logger.info("[Dashboard] 2️⃣ 업로드 수 집계 - 업로드 있는 날 %d일 (총 %d편) (%.0fms)",
                        len(upload_counts), sum(upload_counts.values()), (time.time() - t0) * 1000)

            # 윈도우 전체(118일)를 YouTube에서 통째로 수집 (DB 캐시 없음)
            t0 = time.time()
            rows = await raw_metrics_collector.collect_window(
                access_token=token,
                join_date=join_date,
                today_kst=today,
                upload_counts_by_date=upload_counts,
            )
            ypp = bool(rows and rows[0].get("ypp"))
            logger.info("[Dashboard] 3️⃣ YouTube 수집 완료 - %d일치, ypp=%s (%.0fms)",
                        len(rows), ypp, (time.time() - t0) * 1000)

            t0 = time.time()
            day_map = build_day_map(rows)
            scores = calculate_scores(day_map, today)
            subscriber_delta = calculate_subscriber_delta(day_map, today)
            graph_points = calculate_score_series(day_map, today)
            logger.info("[Dashboard] 4️⃣ 점수 계산 완료 - %s subscriberDelta=%s graphPoints=%d개 (%.0fms)",
                        self._fmt_scores(scores),
                        "N/A" if subscriber_delta is None else f"{subscriber_delta:+d}",
                        len(graph_points),
                        (time.time() - t0) * 1000)

            await self._publish_scores(channel_id, dashboard_date_str, scores, subscriber_delta, graph_points)
            logger.info("[Dashboard] ✅ scores 발행 완료 - channel_id=%s, topic=%s (누적 %.2f초)",
                        channel_id, kafka_config.dashboard_result_v3, time.time() - start_time)
        except Exception as e:
            logger.error("[Dashboard] ❌ scores 처리 실패 - channel_id=%s: %r", channel_id, e, exc_info=True)
            await self._publish_failure(channel_id, dashboard_date_str, DashboardStep.scores)
            return  # 점수 실패 시 suggestion도 무의미 → 종료

        # ── step=suggestions (인프로세스 재시도) ─────────────────────────
        for attempt in range(1, SUGGESTION_MAX_RETRY + 1):
            try:
                logger.info("[Dashboard] 5️⃣ suggestions 생성 시도 %d/%d - channel_id=%s",
                            attempt, SUGGESTION_MAX_RETRY, channel_id)
                t0 = time.time()
                items = await self.suggestion_service.generate(channel, scores, day_map, access_token=token)
                logger.info("[Dashboard] suggestions 생성됨 - 개수=%d, types=%s (%.0fms)",
                            len(items), [i.type for i in items], (time.time() - t0) * 1000)

                # "현재 채널 상황 정리" 종합 문단 — 카드 생성 이후 독립 후처리, 실패해도 카드 발행엔 영향 없음
                try:
                    summary_message = await self.suggestion_service.summarize_situation(channel, scores, items)
                except Exception as e:
                    logger.warning("[Dashboard] situation summary 생성 실패 - channel_id=%s: %r", channel_id, e)
                    summary_message = None

                payload = DashboardSuggestionsPayload(suggestions=items, summary_message=summary_message)
                await kafka_broker.publish(
                    DashboardMessage(
                        is_success=True,
                        step=DashboardStep.suggestions,
                        channel_id=channel_id,
                        dashboard_date=dashboard_date_str,
                        result=payload.model_dump(by_alias=True),
                    ),
                    topic=kafka_config.dashboard_result_v3,
                )
                logger.info("[Dashboard] ✅ suggestions 발행 완료 - channel_id=%s, 개수=%d (전체 %.2f초)",
                            channel_id, len(items), time.time() - start_time)
                break
            except Exception as e:
                logger.warning("[Dashboard] ⚠️ suggestions 생성 실패(%d/%d) - channel_id=%s: %r",
                               attempt, SUGGESTION_MAX_RETRY, channel_id, e)
                if attempt < SUGGESTION_MAX_RETRY:
                    await asyncio.sleep(SUGGESTION_BACKOFF_SEC * attempt)
                else:
                    # 소진 → 실패 발행 (점수는 그대로 유효 = 부분 완성 대시보드)
                    logger.error("[Dashboard] ❌ suggestions 재시도 소진 - channel_id=%s → is_success=False 발행", channel_id)
                    await self._publish_failure(channel_id, dashboard_date_str, DashboardStep.suggestions)

    @staticmethod
    def _fmt_scores(scores: dict) -> str:
        """점수 dict를 'growth=72(+5) algorithm=N/A ...' 형태로 압축."""
        parts = []
        for k, v in scores.items():
            s = v.get("score")
            d = v.get("delta")
            s_str = "N/A" if s is None else str(s)
            d_str = "" if d is None else f"({'+' if d >= 0 else ''}{d})"
            parts.append(f"{k}={s_str}{d_str}")
        return " ".join(parts)

    async def _upload_counts(self, channel_id: int) -> dict[date, int]:
        """채널 영상 upload_date 기준 일별 업로드 수 (upload_score 입력)."""
        videos = await self.video_repository.find_by_channel_id(channel_id)
        counts: dict[date, int] = {}
        for v in videos or []:
            if getattr(v, "upload_date", None):
                d = v.upload_date.date() if hasattr(v.upload_date, "date") else v.upload_date
                counts[d] = counts.get(d, 0) + 1
        return counts

    async def _publish_scores(self, channel_id, dashboard_date_str, scores, subscriber_delta=None,
                              graph_points=None):
        payload = DashboardScoresPayload(
            scores=DashboardScores(
                growth=ScoreItem(**scores["growth"]),
                algorithm=ScoreItem(**scores["algorithm"]),
                retention=ScoreItem(**scores["retention"]),
                engagement=ScoreItem(**scores["engagement"]),
                inflow=ScoreItem(**scores["inflow"]),
                upload=ScoreItem(**scores["upload"]),
            ),
            subscriber_delta=subscriber_delta,
            graph_points=[
                GraphPoint(date=p["date"], scores=GraphPointScores(**p["scores"]))
                for p in (graph_points or [])
            ],
        )
        await kafka_broker.publish(
            DashboardMessage(
                is_success=True,
                step=DashboardStep.scores,
                channel_id=channel_id,
                dashboard_date=dashboard_date_str,
                result=payload.model_dump(by_alias=True),
            ),
            topic=kafka_config.dashboard_result_v3,
        )

    async def _publish_failure(self, channel_id, dashboard_date_str, step: DashboardStep):
        try:
            await kafka_broker.publish(
                DashboardMessage(
                    is_success=False,
                    step=step,
                    channel_id=channel_id,
                    dashboard_date=dashboard_date_str,
                ),
                topic=kafka_config.dashboard_result_v3,
            )
        except Exception as e:
            logger.error("[Dashboard] 실패 메시지 발행 실패 - channel_id=%s, step=%s: %r",
                         channel_id, step, e)
