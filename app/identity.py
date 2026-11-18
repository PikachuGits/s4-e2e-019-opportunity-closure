"""Trusted identity boundary.

In a real deployment the org / site / user triple is injected by the trusted
identity middleware (gateway-verified token) and the service must never accept
client-supplied values. The harness keeps the same header names so tests
exercise the production seam; it does **not** implement authentication itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header

from .errors import ContractError, IDENTITY_REQUIRED


@dataclass(frozen=True)
class Identity:
    org_id: str
    site_id: str
    user_id: str


def identity(
    x_org_id: str | None = Header(default=None),
    x_site_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> Identity:
    missing = [
        name
        for name, value in (
            ("X-Org-ID", x_org_id),
            ("X-Site-ID", x_site_id),
            ("X-User-ID", x_user_id),
        )
        if not value
    ]
    if missing:
        raise ContractError(401, IDENTITY_REQUIRED, f"缺少可信身份头: {', '.join(missing)}")
    return Identity(org_id=x_org_id, site_id=x_site_id, user_id=x_user_id)
