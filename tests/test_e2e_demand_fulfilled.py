"""AC-4：需求状态为 fulfilled，需求广场接口查不到该需求。"""

from __future__ import annotations

import pytest

from app import seed
from tests.conftest import VALID_DEAL, advance_to_deal_closure, convert_match


async def _run_won_chain(ctx) -> str:
    opportunity_id = await convert_match(ctx)
    await advance_to_deal_closure(ctx, opportunity_id)
    deal = await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/deals",
        headers=ctx.headers,
        json=VALID_DEAL,
    )
    assert deal.status_code == 201, deal.text
    closed = await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/close",
        headers=ctx.headers,
        json={"outcome": "won"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "won"
    return opportunity_id


@pytest.mark.asyncio
async def test_won_close_fulfils_demand_and_removes_it_from_plaza(ctx):
    plaza_before = (await ctx.client.get("/api/v1/demands", headers=ctx.headers)).json()
    assert ctx.demand_id in {row["id"] for row in plaza_before}

    await _run_won_chain(ctx)

    demand = (await ctx.client.get(f"/api/v1/demands/{ctx.demand_id}", headers=ctx.headers)).json()
    assert demand["status"] == "fulfilled"

    plaza_after = (await ctx.client.get("/api/v1/demands", headers=ctx.headers)).json()
    assert ctx.demand_id not in {row["id"] for row in plaza_after}

    # 管理/审计视角仍可读到该需求，避免“查不到=数据丢失”的误解
    archived = (
        await ctx.client.get("/api/v1/demands?include_all=true", headers=ctx.headers)
    ).json()
    assert any(row["id"] == ctx.demand_id and row["status"] == "fulfilled" for row in archived)


@pytest.mark.asyncio
async def test_conversion_rate_updates_after_won_and_lost(ctx, db):
    seed.seed_extra_opportunity(db)

    rate_before = (
        await ctx.client.get("/api/v1/stats/opportunity-conversion", headers=ctx.headers)
    ).json()
    assert rate_before == {"won": 0, "lost": 0, "open": 1, "total": 1, "conversion_rate": 0.0}

    await _run_won_chain(ctx)

    rate_after = (
        await ctx.client.get("/api/v1/stats/opportunity-conversion", headers=ctx.headers)
    ).json()
    assert rate_after["won"] == 1
    assert rate_after["total"] == 2
    assert rate_after["conversion_rate"] == 0.5   # 成交商机 ÷ 商机总数
