"""core/kafka/dto/producer_message.py DTO 단위 테스트"""
import pytest
from core.kafka.dto.producer_message import (
    Message, Step, OverviewResult, AnalysisResult,
    ScriptSection, Metrics, CommentAnalysis, RepresentativeComment, ReportSummary,
    CommentSummaryItem,
)


def _make_metrics(**kwargs):
    defaults = dict(
        view=1000, view_channel_avg=500.0,
        like_count=50, like_channel_avg=30.0,
        comment_count=20, comment_channel_avg=10.0,
        concept=80.0, seo=75.0, revisit=5.0,
    )
    return Metrics(**{**defaults, **kwargs})


def _make_comment_analysis(**kwargs):
    defaults = dict(
        total_comment_count=100,
        positive_count=60, negative_count=20, neutral_count=10, advice_count=10,
        positive_pct=60.0, negative_pct=20.0, neutral_pct=10.0, advice_pct=10.0,
        representative_comments=[],
        category_summaries={"positive": "", "negative": "", "neutral": "", "advice": ""},
    )
    return CommentAnalysis(**{**defaults, **kwargs})


class TestStep:
    def test_values(self):
        assert Step.overview.value == "overview"
        assert Step.analysis.value == "analysis"


class TestMessage:
    def test_success_message(self):
        msg = Message(is_success=True, task_id=1, report_id=10, step=Step.overview)
        assert msg.is_success is True
        assert msg.result is None

    def test_failure_message(self):
        msg = Message(is_success=False, task_id=1, report_id=10, step=Step.analysis)
        assert msg.is_success is False

    def test_message_with_result(self):
        result = AnalysisResult()
        msg = Message(is_success=True, task_id=1, report_id=10, step=Step.analysis, result=result)
        assert msg.result is not None

    def test_serializable(self):
        msg = Message(is_success=True, task_id=1, report_id=5, step=Step.overview)
        d = msg.model_dump()
        assert d["is_success"] is True
        assert d["step"] == Step.overview


class TestScriptSection:
    def test_basic(self):
        s = ScriptSection(time="0:00", title="인트로", content="소개 내용")
        assert s.time == "0:00"

    def test_from_dict(self):
        s = ScriptSection(**{"time": "1:30", "title": "본론", "content": "내용"})
        assert s.title == "본론"


class TestMetrics:
    def test_all_fields(self):
        m = _make_metrics()
        assert m.view == 1000
        assert m.seo == 75.0

    def test_zero_values_allowed(self):
        m = _make_metrics(view=0, like_count=0)
        assert m.view == 0


class TestCommentAnalysis:
    def test_basic(self):
        ca = _make_comment_analysis()
        assert ca.total_comment_count == 100
        assert ca.positive_pct == 60.0

    def test_with_representative_comments(self):
        rep = RepresentativeComment(
            category="positive", content="최고예요", author="user1",
            published_at="2024-01-01", like_count=100
        )
        ca = _make_comment_analysis(representative_comments=[rep])
        assert len(ca.representative_comments) == 1
        assert ca.representative_comments[0].like_count == 100

    def test_zero_counts(self):
        ca = _make_comment_analysis(
            positive_count=0, negative_count=0, neutral_count=0, advice_count=0,
            positive_pct=0.0, negative_pct=0.0, neutral_pct=0.0, advice_pct=0.0,
        )
        assert ca.positive_count == 0


class TestReportSummary:
    def test_basic(self):
        s = ReportSummary(title="제목", content="내용", tag="긍정")
        assert s.tag == "긍정"


class TestOverviewResult:
    def test_full_construction(self):
        result = OverviewResult(
            summary=[ScriptSection(time="0:00", title="A", content="B")],
            metrics=_make_metrics(),
            comment_analysis=_make_comment_analysis(),
            overview_summary=ReportSummary(title="T", content="C", tag="긍정"),
        )
        assert result.seo_summary is None  # optional

    def test_with_seo_summary(self):
        result = OverviewResult(
            summary=[],
            metrics=_make_metrics(),
            comment_analysis=_make_comment_analysis(),
            overview_summary=ReportSummary(title="T", content="C", tag="긍정"),
            seo_summary=ReportSummary(title="SEO", content="내용", tag="최적화 원할"),
        )
        assert result.seo_summary.tag == "최적화 원할"

    def test_serializable(self):
        result = OverviewResult(
            summary=[],
            metrics=_make_metrics(),
            comment_analysis=_make_comment_analysis(),
            overview_summary=ReportSummary(title="T", content="C", tag="긍정"),
        )
        d = result.model_dump()
        assert "summary" in d
        assert "metrics" in d


class TestAnalysisResult:
    def test_defaults_none(self):
        r = AnalysisResult()
        assert r.viewer_retention is None
        assert r.optimization is None

    def test_with_values(self):
        r = AnalysisResult(viewer_retention="분석결과", optimization="최적화결과")
        assert r.viewer_retention == "분석결과"


class TestCommentSummaryItem:
    def test_backward_compat(self):
        item = CommentSummaryItem(comment_type="POSITIVE", content="좋아요")
        assert item.comment_type == "POSITIVE"
