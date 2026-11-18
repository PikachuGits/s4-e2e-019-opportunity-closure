"""Contract error codes shared by the reference service and the E2E suite."""

from __future__ import annotations

from fastapi import HTTPException


class ContractError(HTTPException):
    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(
            status_code=status_code,
            detail={"error_code": error_code, "message": message},
        )


# --- stage advancement -------------------------------------------------------
ILLEGAL_STAGE_TRANSITION = "ILLEGAL_STAGE_TRANSITION"
DUPLICATE_STAGE_ADVANCE = "DUPLICATE_STAGE_ADVANCE"
CONCURRENT_STAGE_ADVANCE = "CONCURRENT_STAGE_ADVANCE"
OPPORTUNITY_CLOSED = "OPPORTUNITY_CLOSED"

# --- deal record -------------------------------------------------------------
FUND_FIELDS_FORBIDDEN = "FUND_FIELDS_FORBIDDEN"
DEAL_RECORD_STAGE_REQUIRED = "DEAL_RECORD_STAGE_REQUIRED"
DEAL_RECORD_ALREADY_EXISTS = "DEAL_RECORD_ALREADY_EXISTS"
UNEXPECTED_FIELD = "UNEXPECTED_FIELD"
INVALID_ENUM_VALUE = "INVALID_ENUM_VALUE"

# --- closing -----------------------------------------------------------------
LOST_REASON_REQUIRED = "LOST_REASON_REQUIRED"
DEAL_RECORD_REQUIRED = "DEAL_RECORD_REQUIRED"
INVALID_CLOSE_OUTCOME = "INVALID_CLOSE_OUTCOME"

# --- lookup ------------------------------------------------------------------
NOT_FOUND = "NOT_FOUND"
FORBIDDEN_SCOPE = "FORBIDDEN_SCOPE"
IDENTITY_REQUIRED = "IDENTITY_REQUIRED"
MATCH_NOT_CONVERTIBLE = "MATCH_NOT_CONVERTIBLE"
MATCH_ALREADY_CONVERTED = "MATCH_ALREADY_CONVERTED"
