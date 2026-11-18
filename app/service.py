"""Opportunity closure chain business logic (reference implementation).

Every rule that the E2E acceptance criteria depend on lives here, so the tests
exercise the production seam (HTTP -> service -> persistence) instead of mocking
the service layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .errors import (
    CONCURRENT_STAGE_ADVANCE,
    DEAL_RECORD_ALREADY_EXISTS,
    DEAL_RECORD_REQUIRED,
    DEAL_RECORD_STAGE_REQUIRED,
    DUPLICATE_STAGE_ADVANCE,
    FUND_FIELDS_FORBIDDEN,
    ILLEGAL_STAGE_TRANSITION,
    INVALID_ENUM_VALUE,
    LOST_REASON_REQUIRED,
    MATCH_ALREADY_CONVERTED,
    MATCH_NOT_CONVERTIBLE,
    NOT_FOUND,
    OPPORTUNITY_CLOSED,
    UNEXPECTED_FIELD,
    ContractError,
)
from .fund_guard import find_fund_fields
from .identity import Identity
from .models import (
    Demand,
    MatchRecord,
    Opportunity,
    OpportunityDealRecord,
    OpportunityStageHistory,
)
from .schemas import (
    DealRecordOut,
    STAGE_LABELS,
    STAGE_ORDER,
    AdvanceRequest,
    CloseRequest,
    ConversionRateOut,
    DealRecordRequest,
    OpportunityDetailOut,
    StageHistoryOut,
    WaterfallOut,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_opportunity(db: Session, ident: Identity, opportunity_id: uuid.UUID) -> Opportunity:
    opp = db.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.org_id == ident.org_id,
            Opportunity.deleted_at.is_(None),
        )
    )
    if opp is None:
        raise ContractError(404, NOT_FOUND, "商机不存在或不在当前组织范围内")
    return opp


def _detail(db: Session, opp: Opportunity) -> OpportunityDetailOut:
    db.refresh(opp)
    history = list(
        db.scalars(
            select(OpportunityStageHistory)
            .where(
                OpportunityStageHistory.opportunity_id == opp.id,
                OpportunityStageHistory.deleted_at.is_(None),
            )
            .order_by(OpportunityStageHistory.sequence)
        )
    )
    deals = list(
        db.scalars(
            select(OpportunityDealRecord)
            .where(
                OpportunityDealRecord.opportunity_id == opp.id,
                OpportunityDealRecord.deleted_at.is_(None),
            )
            .order_by(OpportunityDealRecord.created_at)
        )
    )
    payload = OpportunityDetailOut.model_validate(opp)
    payload.stage_history = [StageHistoryOut.model_validate(row) for row in history]
    payload.deal_records = [
        DealRecordOut.model_validate(deal, from_attributes=True) for deal in deals
    ]
    return payload


def convert_match(db: Session, ident: Identity, match_id: uuid.UUID) -> OpportunityDetailOut:
    """员工把「已举行的对接」转为商机。"""

    match = db.scalar(
        select(MatchRecord).where(
            MatchRecord.id == match_id,
            MatchRecord.org_id == ident.org_id,
            MatchRecord.site_id == ident.site_id,
            MatchRecord.deleted_at.is_(None),
        )
    )
    if match is None:
        raise ContractError(404, NOT_FOUND, "对接记录不存在或不在当前组织范围内")
    if match.status == "converted":
        raise ContractError(409, MATCH_ALREADY_CONVERTED, "该对接已转为商机，不能重复转换")
    if match.status != "held" or match.held_at is None:
        raise ContractError(409, MATCH_NOT_CONVERTIBLE, "只有已举行的对接才能转为商机")

    opp = Opportunity(
        org_id=ident.org_id,
        site_id=ident.site_id,
        created_by=ident.user_id,
        match_id=match.id,
        demand_id=match.demand_id,
        enterprise_name=match.enterprise_name,
        owner_id=ident.user_id,
        current_stage=STAGE_ORDER[0],
        status="open",
        version=0,
    )
    db.add(opp)
    match.status = "converted"
    db.commit()
    db.refresh(opp)
    return _detail(db, opp)


def advance_stage(
    db: Session,
    ident: Identity,
    opportunity_id: uuid.UUID,
    body: AdvanceRequest,
) -> OpportunityDetailOut:
    opp = _get_opportunity(db, ident, opportunity_id)
    if opp.status != "open":
        raise ContractError(409, OPPORTUNITY_CLOSED, "商机已关闭，不能再推进阶段")
    if body.to_stage == opp.current_stage:
        raise ContractError(
            409, DUPLICATE_STAGE_ADVANCE, "目标阶段与当前阶段相同，重复推进被拒绝"
        )

    index = STAGE_ORDER.index(opp.current_stage)
    if index + 1 >= len(STAGE_ORDER):
        raise ContractError(
            422,
            ILLEGAL_STAGE_TRANSITION,
            f"当前阶段 {opp.current_stage} 已是最后一阶段，请改用关闭商机",
        )
    expected = STAGE_ORDER[index + 1]
    if body.to_stage != expected:
        raise ContractError(
            422,
            ILLEGAL_STAGE_TRANSITION,
            f"只能按瀑布流逐阶段推进，next_stage={expected}",
        )

    # Optimistic concurrency: two simultaneous advances must not both write
    # history. Only the request that wins the version compare inserts a row.
    previous_stage = opp.current_stage
    try:
        result = db.execute(
            update(Opportunity)
            .where(
                Opportunity.id == opp.id,
                Opportunity.org_id == ident.org_id,
                Opportunity.version == opp.version,
                Opportunity.status == "open",
            )
            .values(current_stage=body.to_stage, version=opp.version + 1, updated_at=_now())
        )
        if result.rowcount != 1:
            db.rollback()
            raise ContractError(
                409, CONCURRENT_STAGE_ADVANCE, "阶段已被其他操作推进，请刷新后重试"
            )

        sequence = (
            db.scalar(
                select(func.count())
                .select_from(OpportunityStageHistory)
                .where(
                    OpportunityStageHistory.opportunity_id == opp.id,
                    OpportunityStageHistory.deleted_at.is_(None),
                )
            )
            or 0
        ) + 1

        db.add(
            OpportunityStageHistory(
                org_id=ident.org_id,
                site_id=ident.site_id,
                created_by=ident.user_id,
                opportunity_id=opp.id,
                sequence=sequence,
                from_stage=previous_stage,
                to_stage=body.to_stage,
                operator_id=ident.user_id,
                occurred_at=_now(),
                reason=body.reason,
            )
        )
        db.commit()
    except OperationalError as exc:  # backend write contention (e.g. SQLite lock)
        db.rollback()
        raise ContractError(
            409, CONCURRENT_STAGE_ADVANCE, "阶段推进发生并发冲突，请刷新后重试"
        ) from exc

    return _detail(db, opp)


def create_deal_record(
    db: Session,
    ident: Identity,
    opportunity_id: uuid.UUID,
    raw_payload: dict,
) -> dict:
    """成交记录：只收统计字段；任何收付款字段（含嵌套）一律 422。"""

    hits = find_fund_fields(raw_payload)
    if hits:
        raise ContractError(
            422,
            FUND_FIELDS_FORBIDDEN,
            "成交记录仅用于统计，不接受任何收付款字段: " + ", ".join(hits),
        )

    try:
        body = DealRecordRequest.model_validate(raw_payload)
    except Exception as exc:  # pydantic ValidationError
        raise ContractError(422, UNEXPECTED_FIELD, f"成交记录字段不合法: {exc}") from exc

    opp = _get_opportunity(db, ident, opportunity_id)
    if opp.status != "open":
        raise ContractError(409, OPPORTUNITY_CLOSED, "商机已关闭，不能再填写成交记录")

    existing = db.scalar(
        select(OpportunityDealRecord).where(
            OpportunityDealRecord.opportunity_id == opp.id,
            OpportunityDealRecord.deleted_at.is_(None),
        )
    )
    if existing is not None:
        raise ContractError(409, DEAL_RECORD_ALREADY_EXISTS, "该商机已存在成交记录")
    if opp.current_stage != "deal_closure":
        raise ContractError(
            409, DEAL_RECORD_STAGE_REQUIRED, "只有推进到成交阶段后才能填写成交记录"
        )
    if not body.deal_type or not body.confirmation_method or not body.scale_range:
        raise ContractError(422, INVALID_ENUM_VALUE, "成交记录枚举取值不合法")

    deal = OpportunityDealRecord(
        org_id=ident.org_id,
        site_id=ident.site_id,
        created_by=ident.user_id,
        opportunity_id=opp.id,
        deal_type=body.deal_type,
        deal_date=body.deal_date,
        confirmation_method=body.confirmation_method,
        scale_range=body.scale_range,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return {
        "id": str(deal.id),
        "deal_type": deal.deal_type,
        "deal_date": deal.deal_date.isoformat(),
        "confirmation_method": deal.confirmation_method,
        "scale_range": deal.scale_range,
    }


def close_opportunity(
    db: Session,
    ident: Identity,
    opportunity_id: uuid.UUID,
    body: CloseRequest,
) -> OpportunityDetailOut:
    opp = _get_opportunity(db, ident, opportunity_id)
    if opp.status != "open":
        raise ContractError(409, OPPORTUNITY_CLOSED, "商机已关闭")
    if body.outcome not in ("won", "lost"):
        raise ContractError(422, INVALID_ENUM_VALUE, "关闭结果只能是 won 或 lost")

    if body.outcome == "won":
        if opp.current_stage != "deal_closure":
            raise ContractError(
                409, DEAL_RECORD_STAGE_REQUIRED, "未推进到成交阶段，不能按成交关闭"
            )
        deal_exists = db.scalar(
            select(func.count())
            .select_from(OpportunityDealRecord)
            .where(
                OpportunityDealRecord.opportunity_id == opp.id,
                OpportunityDealRecord.deleted_at.is_(None),
            )
        )
        if not deal_exists:
            raise ContractError(409, DEAL_RECORD_REQUIRED, "成交关闭前必须存在成交记录")
        opp.status = "won"
        opp.closed_at = _now()
        opp.updated_at = _now()
        demand = db.scalar(
            select(Demand).where(
                Demand.id == opp.demand_id,
                Demand.org_id == ident.org_id,
                Demand.deleted_at.is_(None),
            )
        )
        if demand is not None:
            demand.status = "fulfilled"
            demand.fulfilled_at = _now()
            demand.updated_at = _now()
    else:
        reason = (body.reason or "").strip()
        if not reason:
            raise ContractError(
                422, LOST_REASON_REQUIRED, "未成交关闭必须选择未成交原因"
            )
        opp.status = "lost"
        opp.close_reason = reason
        opp.closed_at = _now()
        opp.updated_at = _now()

    db.commit()
    return _detail(db, opp)


def waterfall(db: Session, ident: Identity, opportunity_id: uuid.UUID) -> WaterfallOut:
    opp = _get_opportunity(db, ident, opportunity_id)
    detail = _detail(db, opp)
    return WaterfallOut(
        opportunity_id=opp.id,
        stages=[{"key": key, "label": STAGE_LABELS[key]} for key in STAGE_ORDER],
        current_stage=opp.current_stage,
        status=opp.status,
        history=detail.stage_history,
    )


def conversion_rate(db: Session, ident: Identity) -> ConversionRateOut:
    rows = db.execute(
        select(Opportunity.status, func.count())
        .where(
            Opportunity.org_id == ident.org_id,
            Opportunity.deleted_at.is_(None),
        )
        .group_by(Opportunity.status)
    ).all()
    counts = {status: count for status, count in rows}
    won = counts.get("won", 0)
    lost = counts.get("lost", 0)
    open_count = counts.get("open", 0)
    total = won + lost + open_count
    rate = round(won / total, 4) if total else 0.0
    return ConversionRateOut(
        won=won, lost=lost, open=open_count, total=total, conversion_rate=rate
    )


def plaza_demands(db: Session, ident: Identity, include_all: bool = False) -> list[Demand]:
    stmt = select(Demand).where(
        Demand.org_id == ident.org_id,
        Demand.deleted_at.is_(None),
    )
    if not include_all:
        stmt = stmt.where(Demand.status.notin_(("fulfilled", "closed")))
    return list(db.scalars(stmt.order_by(Demand.created_at)))
