"""core/enums/report_tag.py 태그 Enum 단위 테스트"""
import pytest
from core.enums.report_tag import OverviewTag, SeoTag, RetentionTag


class TestOverviewTag:
    def test_positive_value(self):
        assert OverviewTag.POSITIVE == "긍정"

    def test_negative_value(self):
        assert OverviewTag.NEGATIVE == "부정"

    def test_is_str_subclass(self):
        assert isinstance(OverviewTag.POSITIVE, str)

    def test_tag_decision_positive_pct_equal_50(self):
        """경계값: positive_pct == 50 → 긍정"""
        pct = 50
        tag = OverviewTag.POSITIVE if pct >= 50 else OverviewTag.NEGATIVE
        assert tag == OverviewTag.POSITIVE

    def test_tag_decision_positive_pct_below_50(self):
        """경계값: positive_pct == 49.9 → 부정"""
        pct = 49.9
        tag = OverviewTag.POSITIVE if pct >= 50 else OverviewTag.NEGATIVE
        assert tag == OverviewTag.NEGATIVE

    def test_tag_decision_zero_pct(self):
        pct = 0
        tag = OverviewTag.POSITIVE if pct >= 50 else OverviewTag.NEGATIVE
        assert tag == OverviewTag.NEGATIVE

    def test_tag_decision_100_pct(self):
        pct = 100
        tag = OverviewTag.POSITIVE if pct >= 50 else OverviewTag.NEGATIVE
        assert tag == OverviewTag.POSITIVE


class TestSeoTag:
    def test_optimized_value(self):
        assert SeoTag.OPTIMIZED == "최적화 원할"

    def test_needs_optimization_value(self):
        assert SeoTag.NEEDS_OPTIMIZATION == "최적화 필요"

    def test_tag_decision_seo_equal_70(self):
        """경계값: seo == 70 → 최적화 원할"""
        seo = 70
        tag = SeoTag.OPTIMIZED if seo >= 70 else SeoTag.NEEDS_OPTIMIZATION
        assert tag == SeoTag.OPTIMIZED

    def test_tag_decision_seo_below_70(self):
        """경계값: seo == 69.9 → 최적화 필요"""
        seo = 69.9
        tag = SeoTag.OPTIMIZED if seo >= 70 else SeoTag.NEEDS_OPTIMIZATION
        assert tag == SeoTag.NEEDS_OPTIMIZATION

    def test_tag_decision_seo_zero(self):
        seo = 0
        tag = SeoTag.OPTIMIZED if seo >= 70 else SeoTag.NEEDS_OPTIMIZATION
        assert tag == SeoTag.NEEDS_OPTIMIZATION

    def test_tag_decision_seo_100(self):
        seo = 100
        tag = SeoTag.OPTIMIZED if seo >= 70 else SeoTag.NEEDS_OPTIMIZATION
        assert tag == SeoTag.OPTIMIZED


class TestRetentionTag:
    def test_good_value(self):
        assert RetentionTag.GOOD == "양호"

    def test_needs_improvement_value(self):
        assert RetentionTag.NEEDS_IMPROVEMENT == "개선 필요"
