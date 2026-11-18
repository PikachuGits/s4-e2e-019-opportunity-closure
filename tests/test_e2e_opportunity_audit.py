"""AC-1：阶段推进留痕条数等于推进次数（操作人 / 时间 / 前后阶段）。"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from tests.conftest import advance, convert_match


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@pytest.mark.asyncio
async def test_advance_writes_one_history_row_per_advance(ctx):
    opportunity_id = await convert_match(ctx)

    detail = (await ctx.client.get(
        f"/api/v1/opportunities/{opportunity_id}", headers=ctx.headers
    )).json()
    assert detail["current_stage"] == "initial_contact"
    assert detail["stage_history"] == []

    # ① 初步接触 -> 方案沟通
    first = await advance(ctx, opportunity_id, "solution_discussion", reason="首次方案沟通完成")
    assert first.status_code == 200, first.text
    history = first.json()["stage_history"]
    assert len(history) == 1
    row = history[0]
    assert row["sequence"] == 1
    assert row["from_stage"] == "initial_contact"
    assert row["to_stage"] == "solution_discussion"
    assert row["operator_id"] == ctx.user_id          # 操作人
    assert _iso(row["occurred_at"]).tzinfo is not None  # 时间（带时区）
    assert row["reason"] == "首次方案沟通完成"

    # ② 方案沟通 -> 商务谈判
    second = await advance(ctx, opportunity_id, "business_negotiation")
    assert second.status_code == 200, second.text

    # ③ 商务谈判 -> 成交
    third = await advance(ctx, opportunity_id, "deal_closure", reason="双方确认成交")
    assert third.status_code == 200, third.text

    final = third.json()
    assert final["current_stage"] == "deal_closure"
    assert len(final["stage_history"]) == 3          # 留痕条数 == 推进次数
    assert [item["sequence"] for item in final["stage_history"]] == [1, 2, 3]
    assert [item["to_stage"] for item in final["stage_history"]] == [
        "solution_discussion",
        "business_negotiation",
        "deal_closure",
    ]
    # 前后阶段首尾相接
    for previous, current in zip(final["stage_history"], final["stage_history"][1:]):
        assert current["from_stage"] == previous["to_stage"]


@pytest.mark.asyncio
async def test_duplicate_and_out_of_order_advance_do_not_add_history(ctx):
    opportunity_id = await convert_match(ctx)
    assert (await advance(ctx, opportunity_id, "solution_discussion")).status_code == 200

    duplicate = await advance(ctx, opportunity_id, "solution_discussion")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error_code"] == "DUPLICATE_STAGE_ADVANCE"

    skipped = await advance(ctx, opportunity_id, "deal_closure")
    assert skipped.status_code == 422
    assert skipped.json()["detail"]["error_code"] == "ILLEGAL_STAGE_TRANSITION"

    detail = (await ctx.client.get(
        f"/api/v1/opportunities/{opportunity_id}", headers=ctx.headers
    )).json()
    assert len(detail["stage_history"]) == 1         # 被拒绝的推进不留痕


@pytest.mark.asyncio
async def test_concurrent_advance_keeps_history_consistent(ctx):
    opportunity_id = await convert_match(ctx)

    responses = await asyncio.gather(
        advance(ctx, opportunity_id, "solution_discussion"),
        advance(ctx, opportunity_id, "solution_discussion"),
    )
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 409], [r.text for r in responses]

    detail = (await ctx.client.get(
        f"/api/v1/opportunities/{opportunity_id}", headers=ctx.headers
    )).json()
    assert detail["current_stage"] == "solution_discussion"
    assert len(detail["stage_history"]) == 1


@pytest.mark.asyncio
async def test_waterfall_endpoint_exposes_same_history(ctx):
    opportunity_id = await convert_match(ctx)
    await advance(ctx, opportunity_id, "solution_discussion")
    await advance(ctx, opportunity_id, "business_negotiation")

    waterfall = (await ctx.client.get(
        f"/api/v1/opportunities/{opportunity_id}/waterfall", headers=ctx.headers
    )).json()
    assert [stage["key"] for stage in waterfall["stages"]] == [
        "initial_contact",
        "solution_discussion",
        "business_negotiation",
        "deal_closure",
    ]
    assert waterfall["current_stage"] == "business_negotiation"
    assert len(waterfall["history"]) == 2
    detail = (await ctx.client.get(
        f"/api/v1/opportunities/{opportunity_id}", headers=ctx.headers
    )).json()
    assert waterfall["history"] == detail["stage_history"]
