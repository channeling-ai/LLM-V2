from enum import Enum


class OverviewTag(str, Enum):
    POSITIVE = "긍정"
    NEGATIVE = "부정"


class SeoTag(str, Enum):
    OPTIMIZED = "최적화 원할"
    NEEDS_OPTIMIZATION = "최적화 필요"


class RetentionTag(str, Enum):
    GOOD = "양호"
    NEEDS_IMPROVEMENT = "개선 필요"
