"""LLM 토큰 사용량 → 비용(USD) 환산.

체험용 더미 리포트의 일일 예산 상한(BE)이 이 값을 누적한다.
집계 자체는 langchain_core의 get_usage_metadata_callback이 하고, 여기서는 환산만 한다.
"""
import logging
from typing import Any, Dict

from domain.report.dto.dummy_report_dto import Cost

logger = logging.getLogger(__name__)

# 100만 토큰당 USD. 모델명은 콜백이 돌려주는 키(버전 접미사가 붙을 수 있어 prefix로 매칭한다).
PRICE_PER_MILLION_TOKENS = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


def to_cost(usage_metadata: Dict[str, Any]) -> Cost:
    """
    콜백이 모아 준 {모델명: {input_tokens, output_tokens, ...}} 를 Cost로 환산한다.
    단가를 모르는 모델은 토큰만 세고 usd에는 더하지 않는다 — 틀린 금액으로 예산을 갉아먹느니
    과소 계상하고 로그를 남긴다.
    """
    input_tokens = 0
    output_tokens = 0
    usd = 0.0

    for model_name, usage in (usage_metadata or {}).items():
        model_input = usage.get("input_tokens", 0)
        model_output = usage.get("output_tokens", 0)
        input_tokens += model_input
        output_tokens += model_output

        price = _find_price(model_name)
        if price is None:
            logger.warning("단가를 모르는 모델이라 비용에서 제외 - model: %s", model_name)
            continue
        usd += (model_input * price["input"] + model_output * price["output"]) / 1_000_000

    return Cost(input_tokens=input_tokens, output_tokens=output_tokens, usd=usd)


def _find_price(model_name: str):
    """'gpt-4o-mini-2024-07-18'처럼 버전이 붙어도 매칭되게 가장 긴 prefix를 고른다."""
    matches = [key for key in PRICE_PER_MILLION_TOKENS if model_name.startswith(key)]
    if not matches:
        return None
    return PRICE_PER_MILLION_TOKENS[max(matches, key=len)]
