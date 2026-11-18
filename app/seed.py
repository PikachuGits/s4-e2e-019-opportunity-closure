"""Fixture helpers that construct the prerequisite data described in the task.

The task says the precondition is "上一条用例中已举行的对接 1 次". The E2E suite
builds that prerequisite with fixtures instead of depending on data produced by
another test case, so each test is independently executable and repeatable.
All content is fictional.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import Demand, MatchRecord, Opportunity

DEFAULT_ORG = "demo-org"
DEFAULT_SITE = "demo-site"
DEFAULT_USER = "demo-sales-01"


def seed_held_match(
    db: Session,
    *,
    org_id: str = DEFAULT_ORG,
    site_id: str = DEFAULT_SITE,
    user_id: str = DEFAULT_USER,
    title: str = "虚构需求：园区企业年度法律顾问服务",
    enterprise_name: str = "虚构企业甲公司",
    held: bool = True,
) -> tuple[Demand, MatchRecord]:
    demand = Demand(
        org_id=org_id,
        site_id=site_id,
        created_by=user_id,
        title=title,
        status="matching",
    )
    match = MatchRecord(
        org_id=org_id,
        site_id=site_id,
        created_by=user_id,
        demand=demand,
        enterprise_name=enterprise_name,
        status="held" if held else "scheduled",
        held_at=datetime.now(timezone.utc) if held else None,
    )
    db.add_all([demand, match])
    db.commit()
    db.refresh(demand)
    db.refresh(match)
    return demand, match


def seed_extra_opportunity(
    db: Session,
    *,
    org_id: str = DEFAULT_ORG,
    site_id: str = DEFAULT_SITE,
    user_id: str = DEFAULT_USER,
    status: str = "open",
) -> Opportunity:
    """Second opportunity used by the conversion-rate assertion."""

    demand = Demand(
        org_id=org_id,
        site_id=site_id,
        created_by=user_id,
        title=f"虚构需求：{uuid.uuid4().hex[:8]} 配套服务",
        status="matching",
    )
    match = MatchRecord(
        org_id=org_id,
        site_id=site_id,
        created_by=user_id,
        demand=demand,
        enterprise_name="虚构企业乙公司",
        status="converted",
        held_at=datetime.now(timezone.utc),
    )
    opp = Opportunity(
        org_id=org_id,
        site_id=site_id,
        created_by=user_id,
        match=match,
        demand=demand,
        enterprise_name=match.enterprise_name,
        owner_id=user_id,
        current_stage="initial_contact",
        status=status,
        version=0,
    )
    db.add_all([demand, match, opp])
    db.commit()
    db.refresh(opp)
    return opp
