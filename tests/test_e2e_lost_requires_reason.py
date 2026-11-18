"""AC-3：未选择原因的未成交关闭被拒绝。"""

from __future__ import annotations

import pytest

from tests.conftest import advance, convert_match


async def _close(ctx, opportunity_id: str, payload: dict):
    return await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/close",
        headers=ctx.headers,
        json=payload,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"outcome": "lost"}, {"outcome": "lost", "reason": ""}, {"outcome": "lost", "reason": "   "}])
async def test_lost_close_without_reason_is_rejected(ctx, payload):
    opportunity_id = await convert_match(ctx)
    await advance(ctx, opportunity_id, "solution_discussion")

    response = await _close(ctx, opportunity_id, payload)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error_code"] == "LOST_REASON_REQUIRED"

    detail = (await ctx.client.get(
        f"/api/v1/opportunities/{opportunity_id}", headers=ctx.headers
    )).json()
    assert detail["status"] == "open"
    assert detail["close_reason"] is None
    assert detail["closed_at"] is None


@pytest.mark.asyncio
async def test_lost_close_with_reason_succeeds(ctx):
    opportunity_id = await convert_match(ctx)
    await advance(ctx, opportunity_id, "solution_discussion")

    response = await _close(
        ctx, opportunity_id, {"outcome": "lost", "reason": "客户预算未获批准"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "lost"
    assert body["close_reason"] == "客户预算未获批准"
    assert body["closed_at"] is not None

    # 关闭后不能再推进阶段
    blocked = await advance(ctx, opportunity_id, "business_negotiation")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error_code"] == "OPPORTUNITY_CLOSED"


@pytest.mark.asyncio
async def test_won_close_requires_deal_record(ctx):
    opportunity_id = await convert_match(ctx)
    for stage in ("solution_discussion", "business_negotiation", "deal_closure"):
        assert (await advance(ctx, opportunity_id, stage)).status_code == 200

    response = await _close(ctx, opportunity_id, {"outcome": "won"})
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "DEAL_RECORD_REQUIRED"

    # 需求在成交前保持可匹配状态
    demand = (await ctx.client.get(f"/api/v1/demands/{ctx.demand_id}", headers=ctx.headers)).json()
    assert demand["status"] == "matching"
