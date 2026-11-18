"""AC-2：提交收付款类字段返回 422（含嵌套与数组层级）。"""

from __future__ import annotations

import pytest

from app.fund_guard import FUND_FIELD_TOKENS
from app.models import OpportunityDealRecord
from tests.conftest import VALID_DEAL, advance_to_deal_closure, convert_match


async def _opportunity_at_deal_stage(ctx) -> str:
    opportunity_id = await convert_match(ctx)
    await advance_to_deal_closure(ctx, opportunity_id)
    return opportunity_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden_payload",
    [
        {"amount_paid": "120.00"},
        {"payment_account": "6222020200000000000"},
        {"paid_amount": 12000},
        {"received_amount": "120.00", "payment_account": "虚构账户"},
        # nested object
        {"extra": {"payment_account": "6222020200000000000"}},
        {"commercial": {"detail": {"amount_paid": 12000}}},
        # nested array
        {"attachments": [{"amount_paid": 12000}]},
        {"attachments": [{"meta": {"bank_account": "6222"}}]},
    ],
)
async def test_fund_fields_are_rejected_with_422(ctx, forbidden_payload):
    opportunity_id = await _opportunity_at_deal_stage(ctx)
    payload = {**VALID_DEAL, **forbidden_payload}

    response = await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/deals",
        headers=ctx.headers,
        json=payload,
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error_code"] == "FUND_FIELDS_FORBIDDEN"


@pytest.mark.asyncio
async def test_snake_and_camel_case_variants_are_rejected(ctx):
    opportunity_id = await _opportunity_at_deal_stage(ctx)
    payload = {**VALID_DEAL, "amountPaid": 12000, "PaymentAccount": "6222"}

    response = await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/deals",
        headers=ctx.headers,
        json=payload,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "FUND_FIELDS_FORBIDDEN"


@pytest.mark.asyncio
async def test_valid_statistics_only_record_is_accepted(ctx, db):
    opportunity_id = await _opportunity_at_deal_stage(ctx)

    response = await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/deals",
        headers=ctx.headers,
        json=VALID_DEAL,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "deal_type", "deal_date", "confirmation_method", "scale_range"}
    assert body["deal_type"] == "new_business"
    assert body["scale_range"] == "scale_100k_500k"

    # 落库的成交记录也只有统计字段：库表中不存在任何收付款列
    columns = {column.name for column in OpportunityDealRecord.__table__.columns}
    fund_columns = {
        name for name in columns if "".join(ch for ch in name.lower() if ch.isalnum()) in FUND_FIELD_TOKENS
    }
    assert fund_columns == set()

    stored = db.query(OpportunityDealRecord).one()
    assert stored.deal_type == "new_business"
    assert stored.scale_range == "scale_100k_500k"


@pytest.mark.asyncio
async def test_deal_record_requires_deal_stage(ctx):
    opportunity_id = await convert_match(ctx)
    response = await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/deals",
        headers=ctx.headers,
        json=VALID_DEAL,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "DEAL_RECORD_STAGE_REQUIRED"


@pytest.mark.asyncio
async def test_unknown_non_fund_field_is_also_rejected(ctx):
    opportunity_id = await _opportunity_at_deal_stage(ctx)
    response = await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/deals",
        headers=ctx.headers,
        json={**VALID_DEAL, "remark": "随便写点"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "UNEXPECTED_FIELD"


@pytest.mark.asyncio
async def test_physical_table_schema_has_no_fund_columns(ctx, db):
    """在真实建表后的 schema 上做 introspection，而不是只看 ORM 元数据。"""

    from sqlalchemy import inspect, text

    from app.fund_guard import normalise_key

    opportunity_id = await _opportunity_at_deal_stage(ctx)
    assert (
        await ctx.client.post(
            f"/api/v1/opportunities/{opportunity_id}/deals",
            headers=ctx.headers,
            json=VALID_DEAL,
        )
    ).status_code == 201

    inspector = inspect(db.get_bind())
    columns = {column["name"] for column in inspector.get_columns("opportunity_deal_records")}
    assert {"deal_type", "deal_date", "confirmation_method", "scale_range"} <= columns
    assert {name for name in columns if normalise_key(name) in FUND_FIELD_TOKENS} == set()

    if db.get_bind().dialect.name == "sqlite":
        ddl = db.execute(
            text("select sql from sqlite_master where type='table' and name='opportunity_deal_records'")
        ).scalar()
        for token in ("amount", "payment", "account", "payee", "payer", "currency", "price"):
            assert token not in ddl.lower(), f"物理表 DDL 出现资金字段关键字: {token}"
