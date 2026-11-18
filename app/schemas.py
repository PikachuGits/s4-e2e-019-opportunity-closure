"""Pydantic contracts for the reference opportunity service."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Stage = Literal[
    "initial_contact",
    "solution_discussion",
    "business_negotiation",
    "deal_closure",
]

STAGE_ORDER: tuple[Stage, ...] = (
    "initial_contact",
    "solution_discussion",
    "business_negotiation",
    "deal_closure",
)

STAGE_LABELS: dict[str, str] = {
    "initial_contact": "初步接触",
    "solution_discussion": "方案沟通",
    "business_negotiation": "商务谈判",
    "deal_closure": "成交",
}

DealType = Literal["new_business", "renewal", "expansion"]
ConfirmationMethod = Literal[
    "written_contract",
    "email_confirmation",
    "meeting_minutes",
    "platform_message",
]
ScaleRange = Literal[
    "scale_lt_100k",
    "scale_100k_500k",
    "scale_500k_2m",
    "scale_gte_2m",
]


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_stage: Stage
    reason: str | None = Field(default=None, max_length=500)


class CloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["won", "lost"]
    reason: str | None = Field(default=None, max_length=500)


class DealRecordRequest(BaseModel):
    """Statistics-only deal record: four fields, no payment information."""

    model_config = ConfigDict(extra="forbid")

    deal_type: DealType
    deal_date: date
    confirmation_method: ConfirmationMethod
    scale_range: ScaleRange


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalise naive timestamps (SQLite) to UTC; PostgreSQL returns aware ones."""

    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class StageHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    from_stage: str
    to_stage: str
    operator_id: str
    occurred_at: datetime
    _tz = field_validator("occurred_at")(ensure_utc)
    reason: str | None = None


class DealRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deal_type: str
    deal_date: date
    confirmation_method: str
    scale_range: str


class OpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    match_id: uuid.UUID
    demand_id: uuid.UUID
    enterprise_name: str
    owner_id: str
    current_stage: str
    status: str
    close_reason: str | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    _tz_created = field_validator("created_at")(ensure_utc)
    _tz_updated = field_validator("updated_at")(ensure_utc)


class OpportunityDetailOut(OpportunityOut):
    stage_history: list[StageHistoryOut] = Field(default_factory=list)
    deal_records: list[DealRecordOut] = Field(default_factory=list)


class WaterfallOut(BaseModel):
    opportunity_id: uuid.UUID
    stages: list[dict[str, str]]
    current_stage: str
    status: str
    history: list[StageHistoryOut]


class ConversionRateOut(BaseModel):
    won: int
    lost: int
    open: int
    total: int
    conversion_rate: float


class DemandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
