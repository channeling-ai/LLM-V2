"""domain/dashboard/service/dashboard_consumer_impl.py 결과 메시지 키 테스트

Spring이 scores/suggestions 결과를 같은 channel_dashboard 행에 병합하므로
모든 결과는 channel_id 키로 발행되어 같은 파티션에 들어가야 함.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.kafka.dto.dashboard_message import DashboardStep


def _make_consumer():
    with patch("domain.dashboard.service.dashboard_consumer_impl.ChannelRepository"), \
         patch("domain.dashboard.service.dashboard_consumer_impl.VideoRepository"), \
         patch("domain.dashboard.service.dashboard_consumer_impl.SuggestionService"):
        from domain.dashboard.service.dashboard_consumer_impl import DashboardConsumerImpl
        return DashboardConsumerImpl(MagicMock())


_SCORE = {"score": 50, "delta": 1}
_SCORES = {k: _SCORE for k in ("growth", "algorithm", "retention", "engagement", "inflow", "upload")}


async def _capture(coro_fn):
    published = []

    async def fake_publish(message, topic, key=None):
        published.append((message, key))

    with patch("domain.dashboard.service.dashboard_consumer_impl.kafka_broker") as mock_broker:
        mock_broker.publish = fake_publish
        await coro_fn()

    return published


class TestDashboardResultMessageKey:
    def setup_method(self):
        self.consumer = _make_consumer()

    @pytest.mark.asyncio
    async def test_scores_keyed_by_channel_id(self):
        published = await _capture(
            lambda: self.consumer._publish_scores(3, "2026-10-05", _SCORES)
        )

        assert [k for _, k in published] == [b"3"]

    @pytest.mark.asyncio
    async def test_failure_keyed_by_channel_id(self):
        published = await _capture(
            lambda: self.consumer._publish_failure(3, "2026-10-05", DashboardStep.suggestions)
        )

        assert [k for _, k in published] == [b"3"]

    @pytest.mark.asyncio
    async def test_scores_and_suggestions_share_key(self):
        """한 요청의 scores/suggestions가 같은 키 → 같은 파티션"""
        channel = MagicMock()
        channel.join_date = MagicMock()
        self.consumer.channel_repository.find_by_id = AsyncMock(return_value=channel)
        self.consumer.video_repository.find_by_channel_id = AsyncMock(return_value=[])
        self.consumer.suggestion_service.generate = AsyncMock(return_value=[])
        self.consumer.suggestion_service.summarize_situation = AsyncMock(return_value=None)

        mod = "domain.dashboard.service.dashboard_consumer_impl"
        with patch(f"{mod}.raw_metrics_collector.collect_window", AsyncMock(return_value=[])), \
             patch(f"{mod}.build_day_map", return_value={}), \
             patch(f"{mod}.calculate_scores", return_value=_SCORES), \
             patch(f"{mod}.calculate_subscriber_delta", return_value=None), \
             patch(f"{mod}.calculate_score_series", return_value=[]):
            published = await _capture(lambda: self.consumer.handle_dashboard({
                "channel_id": 3, "dashboard_date": "2026-10-05", "google_access_token": "t",
            }))

        steps = [m.step for m, _ in published]
        assert steps == [DashboardStep.scores, DashboardStep.suggestions]
        assert [k for _, k in published] == [b"3", b"3"]
