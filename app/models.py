"""SQLAlchemy 2.x models for the opportunity (商机) closure chain.

The unified convention of the project is followed: every business table carries
``id (UUID)``, ``org_id``, ``site_id``, ``created_at``, ``created_by``,
``updated_at`` and ``deleted_at`` (soft delete). Money is never stored here:
the deal record is statistics-only by contract, see ``DEAL_FORBIDDEN_FIELDS``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class OrgSiteMixin:
    org_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Demand(Base, OrgSiteMixin):
    """需求（需求广场条目）；成交后自动置为 fulfilled 并下架。"""

    __tablename__ = "demands"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # open | matching | fulfilled | closed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    matches: Mapped[list["MatchRecord"]] = relationship(back_populates="demand")


class MatchRecord(Base, OrgSiteMixin):
    """对接记录（S3-MATCH 域的写入口在真实系统里，本仓库用接口桩模拟）。"""

    __tablename__ = "match_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    demand_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("demands.id"), nullable=False, index=True
    )
    enterprise_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # scheduled | held | converted | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    demand: Mapped[Demand] = relationship(back_populates="matches")


class Opportunity(Base, OrgSiteMixin):
    """商机：由一次已举行的对接转换而来，按瀑布流阶段推进。"""

    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("match_records.id"), nullable=False, unique=True
    )
    demand_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("demands.id"), nullable=False, index=True
    )
    enterprise_name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # initial_contact | solution_discussion | business_negotiation | deal_closure
    current_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="initial_contact"
    )
    # open | won | lost
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    close_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # optimistic concurrency token for stage advancement
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    stage_history: Mapped[list["OpportunityStageHistory"]] = relationship(
        back_populates="opportunity", order_by="OpportunityStageHistory.sequence"
    )
    deal_records: Mapped[list["OpportunityDealRecord"]] = relationship(back_populates="opportunity")
    match: Mapped[MatchRecord] = relationship()
    demand: Mapped[Demand] = relationship()


class OpportunityStageHistory(Base, OrgSiteMixin):
    """阶段推进留痕：一次推进恰好一条，操作人 / 时间 / 前后阶段齐全。"""

    __tablename__ = "opportunity_stage_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("opportunities.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    opportunity: Mapped[Opportunity] = relationship(back_populates="stage_history")


class OpportunityDealRecord(Base, OrgSiteMixin):
    """成交记录：仅统计字段，不含任何收付款字段。"""

    __tablename__ = "opportunity_deal_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("opportunities.id"), nullable=False, index=True
    )
    # new_business | renewal | expansion
    deal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    deal_date: Mapped[date] = mapped_column(Date, nullable=False)
    # written_contract | email_confirmation | meeting_minutes | platform_message
    confirmation_method: Mapped[str] = mapped_column(String(32), nullable=False)
    # scale_lt_100k | scale_100k_500k | scale_500k_2m | scale_gte_2m
    scale_range: Mapped[str] = mapped_column(String(32), nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="deal_records")
