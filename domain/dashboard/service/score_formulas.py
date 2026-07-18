"""6개 지표 점수 계산 공식 (Spring `ScoreFormulas` 포팅 + 버그 수정).

원본: channeling-be `ScoreFormulas`/`ScoreCalculationService` (stash 974c991, 브랜치 `backup/dashboard-score-stash`).
포팅하면서 기존 버그를 **복제하지 않고 고쳐서** 옮긴다 (근거: `docs/SCORE_FORMULA_DEV.md`).

내장한 수정:
  A. `to28d` 분모를 90 고정 → **윈도우의 실제 데이터 일수**(`day_count`)로.
  B. growth 결측 항목을 0점 처리 → **제외 후 남은 가중치 재정규화**.
  C. baseline 윈도우 중첩 제거 → **윈도우 정의(호출부) 책임**. 여기선 받은 윈도우를 그대로 사용.
  D. algorithm 절대척도 → **baseline 대비 상대화**(다른 5개와 같은 잣대).
  E. `normalize` 하한 없음(음수) → **0~100 클램프**.
  ① 비수익화(비YPP) 채널: inflow·algorithm → **None(N/A)** (0/40점으로 깔지 않음).
  delta. 한쪽 결측이면 **None 유지**("비교 데이터 없음").

모든 점수는 0~100 정수 또는 None. None = 데이터 부족/미지원 → 화면에 "데이터 수집 중"/"전용 지표".
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WindowSum:
    """한 윈도우(current/previous/baseline)의 raw_metrics 합산 결과.

    `averageViewPercentage`는 단순 SUM이 불가능한 평균값이라,
    `avp_times_views = SUM(avp * views)`로 받아 `/ views`로 가중평균을 낸다.
    비YPP 전용 필드(browse/non_subscriber)는 비수익화 채널에서 None(미수집).
    """

    day_count: int                              # 윈도우 내 실제 데이터 일수 (버그 A 분모)
    subscribers_gained: int
    subscribers_lost: int
    views: int
    avp_times_views: float                      # 가중평균 분자: SUM(avp * views)
    likes: int
    comments: int
    shares: int
    upload_count: int
    ypp: bool                                   # 수익화 채널 여부
    browse_and_suggested_views: Optional[int]   # 비YPP → None
    non_subscriber_views: Optional[int]         # 비YPP → None


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────

def _normalize(current: float, baseline: float) -> Optional[int]:
    """현재값을 baseline 대비 0~100점으로 정규화 (평소만큼=80, +25%=100).

    baseline <= 0 → None(데이터 부족). 버그 E: 하한 0 클램프 추가.
    """
    if baseline <= 0:
        return None
    return max(0, min(100, int((current / baseline) * 80)))


def _to28d(baseline_sum: float, actual_days: int) -> float:
    """절댓값 누적 지표를 28일 기준 기대치로 환산.

    버그 A: 90 고정 분모 → 윈도우의 실제 데이터 일수(`actual_days`)로 나눈다.
    """
    if actual_days <= 0:
        return 0.0
    return baseline_sum / actual_days * 28


def _weighted_avp(w: WindowSum) -> float:
    """averageViewPercentage 가중평균 = SUM(avp*views) / SUM(views)."""
    if w.views == 0:
        return 0.0
    return w.avp_times_views / w.views


def _renormalize(parts: list[tuple[Optional[int], float]]) -> Optional[int]:
    """`(점수, 가중치)` 목록에서 결측(None)을 제외하고 남은 가중치로 재정규화.

    버그 B: 한쪽이 None이어도 0점 페널티를 주지 않는다. 전부 None이면 None.
    """
    total = 0.0
    weight = 0.0
    for score, w in parts:
        if score is not None:
            total += score * w
            weight += w
    return None if weight == 0 else round(total / weight)


# ── ① 채널 성장 (growth) ─────────────────────────────────────────────────

def growth_score(cur: WindowSum, base: WindowSum) -> Optional[int]:
    """구독자 순증(0.7) + 조회수(0.3). 둘 다 절댓값 → baseline 28d 환산."""
    if cur.day_count <= 0:
        return None  # 윈도우에 데이터 없음 → 점수 N/A (delta null 정책 ③의 근거)
    net_subs_c = cur.subscribers_gained - cur.subscribers_lost
    net_subs_b28 = _to28d(base.subscribers_gained - base.subscribers_lost, base.day_count)
    views_b28 = _to28d(base.views, base.day_count)

    net_subs_score = _normalize(net_subs_c, net_subs_b28)
    views_score = _normalize(cur.views, views_b28)
    # 버그 B: 결측 제외 후 재정규화 (0점 페널티 제거)
    return _renormalize([(net_subs_score, 0.7), (views_score, 0.3)])


# ── ② 알고리즘 (algorithm) ───────────────────────────────────────────────

def algorithm_score(cur: WindowSum, base: WindowSum) -> Optional[int]:
    """유입질(browse 비중, 0.6) + 지속(AVP, 0.4).

    버그 ①: 비YPP → None(N/A). 버그 D: 절대척도 → baseline 대비 상대화.
    """
    if cur.day_count <= 0:
        return None  # 윈도우에 데이터 없음 → N/A
    if not cur.ypp or cur.browse_and_suggested_views is None or base.browse_and_suggested_views is None:
        return None  # 비수익화/미수집 → 전용 지표 N/A

    quality_score = None
    if cur.views > 0 and base.views > 0:
        browse_ratio_c = cur.browse_and_suggested_views / cur.views
        browse_ratio_b = base.browse_and_suggested_views / base.views
        quality_score = _normalize(browse_ratio_c, browse_ratio_b)

    retention_score_ = _normalize(_weighted_avp(cur), _weighted_avp(base))
    return _renormalize([(quality_score, 0.6), (retention_score_, 0.4)])


# ── ③ 시청 몰입 (retention) ──────────────────────────────────────────────

def retention_score(cur: WindowSum, base: WindowSum) -> Optional[int]:
    """AVP 가중평균 비교. 비율값이라 28d 환산 없이 직접 비교."""
    if cur.day_count <= 0:
        return None
    return _normalize(_weighted_avp(cur), _weighted_avp(base))


# ── ④ 반응 밀도 (engagement) ─────────────────────────────────────────────

def engagement_score(cur: WindowSum, base: WindowSum) -> Optional[int]:
    """ER = (likes+comments+shares)/views 비교. views<100이면 신뢰도 부족 → None."""
    if cur.day_count <= 0:
        return None
    if cur.views < 100:
        return None
    er_c = (cur.likes + cur.comments + cur.shares) / cur.views
    if base.views == 0:
        return None
    er_b = (base.likes + base.comments + base.shares) / base.views
    return _normalize(er_c, er_b)


# ── ⑤ 유입 활력 (inflow) ─────────────────────────────────────────────────

def inflow_score(cur: WindowSum, base: WindowSum) -> Optional[int]:
    """신규유입비중 = 비구독자 views / 전체 views 비교.

    버그 ①: 비YPP → None(N/A).
    """
    if cur.day_count <= 0:
        return None
    if not cur.ypp or cur.non_subscriber_views is None or base.non_subscriber_views is None:
        return None
    if cur.views == 0 or base.views == 0:
        return None
    ratio_c = cur.non_subscriber_views / cur.views
    ratio_b = base.non_subscriber_views / base.views
    return _normalize(ratio_c, ratio_b)


# ── ⑥ 업로드 성실도 (upload) ─────────────────────────────────────────────

def upload_score(cur: WindowSum, base: WindowSum) -> Optional[int]:
    """현재 28일 업로드 수 vs 90일 평균(28d 환산). baseline 0인 신규 → 월 4회 기본값."""
    if cur.day_count <= 0:
        return None
    uploads_b28 = _to28d(base.upload_count, base.day_count)
    if uploads_b28 <= 0:
        uploads_b28 = 4.0  # 신규 채널 기본 기대치: 월 4회
    return _normalize(cur.upload_count, uploads_b28)


# ── delta + 일괄 계산 ────────────────────────────────────────────────────

_SCORE_FNS = {
    "growth": growth_score,
    "algorithm": algorithm_score,
    "retention": retention_score,
    "engagement": engagement_score,
    "inflow": inflow_score,
    "upload": upload_score,
}


def _delta(fn, cur: WindowSum, prev: WindowSum, base: WindowSum) -> Optional[int]:
    """현재 점수 - 이전 점수. 한쪽이라도 None이면 None ("비교 데이터 없음")."""
    cur_score = fn(cur, base)
    prev_score = fn(prev, base)
    if cur_score is None or prev_score is None:
        return None
    return cur_score - prev_score


def calculate_all(
    current: WindowSum,
    previous: WindowSum,
    baseline: WindowSum,
) -> dict[str, dict[str, Optional[int]]]:
    """6개 지표의 score/delta(12개)를 `{지표: {"score":..., "delta":...}}`로 반환.

    delta는 current/previous를 **동일 baseline** 대비로 비교한다 (원본과 동일).
    """
    return {
        name: {
            "score": fn(current, baseline),
            "delta": _delta(fn, current, previous, baseline),
        }
        for name, fn in _SCORE_FNS.items()
    }


def calculate_scores_only(current: WindowSum, baseline: WindowSum) -> dict[str, Optional[int]]:
    """6개 지표의 score만 `{지표: score}`로 반환 (delta 미계산).

    그래프 소급 포인트(과거 앵커)는 delta가 필요 없어 previous 윈도우 합산을 생략할 수 있다 —
    `calculate_all`보다 가벼움.
    """
    return {name: fn(current, baseline) for name, fn in _SCORE_FNS.items()}
