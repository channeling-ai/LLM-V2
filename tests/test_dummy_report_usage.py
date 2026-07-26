"""더미 리포트 비용 집계(Step 2) 단위 테스트

BE의 일일 예산 카운터가 이 값을 누적하므로, 두 가지를 못박는다:
1) asyncio.gather로 병렬 실행된 하위 LLM 호출까지 하나의 컨텍스트에 합산되는가
2) 토큰 → USD 환산이 gpt-4o-mini 단가표대로 나오는가
"""
import asyncio

import pytest
from langchain_core.callbacks.usage import get_usage_metadata_callback
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from domain.report.service.usage_cost import to_cost


def _fake_model(input_tokens: int, output_tokens: int) -> GenericFakeChatModel:
    """usage_metadata를 실은 응답 1개를 돌려주는 가짜 채팅 모델."""
    message = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        response_metadata={"model_name": "gpt-4o-mini"},
    )
    return GenericFakeChatModel(messages=iter([message] * 100))


@pytest.mark.asyncio
async def test_parallel_calls_accumulate_into_one_context():
    """gather로 흩어진 호출도 한 컨텍스트에 누적돼야 한다 — 생성 1건은 LLM을 병렬로 여러 번 부른다."""
    model = _fake_model(input_tokens=10, output_tokens=5)

    with get_usage_metadata_callback() as cb:
        await asyncio.gather(*(model.ainvoke("hi") for _ in range(4)))

    cost = to_cost(cb.usage_metadata)
    assert cost.input_tokens == 40
    assert cost.output_tokens == 20


def test_usd_uses_gpt_4o_mini_price_table():
    """$0.15/1M input, $0.60/1M output."""
    usage = {"gpt-4o-mini": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}

    cost = to_cost(usage)

    assert cost.input_tokens == 1_000_000
    assert cost.output_tokens == 1_000_000
    assert cost.usd == pytest.approx(0.75)


def test_unknown_model_counts_tokens_but_not_usd():
    """단가를 모르는 모델은 토큰만 세고 usd는 더하지 않는다 — 예산을 과소·과대 계상하지 않는다."""
    usage = {"some-new-model": {"input_tokens": 100, "output_tokens": 50}}

    cost = to_cost(usage)

    assert (cost.input_tokens, cost.output_tokens) == (100, 50)
    assert cost.usd == 0.0


def test_empty_usage_is_zero():
    """LLM 호출이 전혀 없던 경우(전부 캐시/실패)에도 0으로 안전하게 내려간다."""
    cost = to_cost({})

    assert (cost.input_tokens, cost.output_tokens, cost.usd) == (0, 0, 0.0)


@pytest.mark.asyncio
async def test_controller_fills_measured_cost():
    """컨트롤러 응답의 cost가 실제 집계값이어야 한다 (Step 1의 0 고정에서 바뀐 지점)."""
    from unittest.mock import AsyncMock, patch

    from domain.report.controller import dummy_report_controller as ctrl
    from domain.report.dto.dummy_report_dto import DummyReportRequest
    from tests.test_dummy_report_controller import _generator_with_mocks, _patch_video_meta

    model = _fake_model(input_tokens=1000, output_tokens=200)
    generator = _generator_with_mocks()

    async def _generate_calling_llm(*args, **kwargs):
        await model.ainvoke("hi")
        return await original(*args, **kwargs)

    original = generator.generate
    generator.generate = AsyncMock(side_effect=_generate_calling_llm)

    with patch.object(ctrl, "recommend_generator", generator), _patch_video_meta():
        res = await ctrl.create_dummy_report(DummyReportRequest(youtube_video_id="vid1"))

    cost = res["result"]["cost"]
    assert cost["input_tokens"] == 1000
    assert cost["output_tokens"] == 200
    assert cost["usd"] > 0
