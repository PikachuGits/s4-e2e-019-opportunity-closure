"""Shared fixtures for the opportunity closure-chain E2E suite.

Each test gets a clean schema and a freshly built "已举行的对接" precondition,
so no case depends on data produced by another case.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _assert_isolated_pg(url: str) -> None:
    """Refuse anything that is not an explicitly namespaced local test database."""

    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError("TEST_DATABASE_URL 只接受 postgresql:// 连接串")
    if parsed.host not in (None, "127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"拒绝对非本机数据库运行测试: host={parsed.host}")
    database = (parsed.database or "").lower()
    if "test" not in database and "e2e" not in database:
        raise RuntimeError(f"库名必须含 test/e2e，避免误连共享库: {parsed.database}")


@pytest.fixture(scope="session")
def database_url(tmp_path_factory) -> str:
    """Explicit TEST_DATABASE_URL wins (PostgreSQL path); otherwise throw-away SQLite.

    The PostgreSQL path is expected to be migrated first (``alembic upgrade head``);
    the suite never creates schema on it.
    """

    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        _assert_isolated_pg(explicit)
        os.environ["DATABASE_URL"] = explicit
        os.environ["SEED_DEMO_DATA"] = "0"
        os.environ["AUTO_CREATE_SCHEMA"] = os.getenv("AUTO_CREATE_SCHEMA", "0")
        return explicit

    db_file = tmp_path_factory.mktemp("db") / "e2e.sqlite3"
    url = f"sqlite+pysqlite:///{db_file}"
    os.environ["DATABASE_URL"] = url
    os.environ["AUTO_CREATE_SCHEMA"] = "1"
    os.environ["SEED_DEMO_DATA"] = "0"
    return url


@pytest.fixture(scope="session")
def app(database_url):
    from app.main import app as fastapi_app
    from app.db import init_schema

    if not os.getenv("TEST_DATABASE_URL"):
        # PostgreSQL path is migrated by the caller (alembic upgrade head)
        init_schema()
    return fastapi_app


@pytest.fixture(scope="session")
def session_factory(app, database_url):
    from app.db import SessionLocal

    return SessionLocal


@pytest.fixture()
def db(session_factory):
    from app.models import Base

    session = session_factory()
    # isolate every case: wipe rows in FK-safe order
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    try:
        yield session
    finally:
        session.close()


@dataclass
class Ctx:
    client: AsyncClient
    headers: dict[str, str]
    demand_id: str
    match_id: str
    user_id: str


@pytest_asyncio.fixture()
async def ctx(app, db):
    from app import seed

    demand, match = seed.seed_held_match(db)
    headers = {
        "X-Org-ID": seed.DEFAULT_ORG,
        "X-Site-ID": seed.DEFAULT_SITE,
        "X-User-ID": seed.DEFAULT_USER,
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://e2e.local") as client:
        yield Ctx(
            client=client,
            headers=headers,
            demand_id=str(demand.id),
            match_id=str(match.id),
            user_id=seed.DEFAULT_USER,
        )


async def convert_match(ctx: Ctx) -> str:
    response = await ctx.client.post(
        f"/api/v1/matches/{ctx.match_id}/convert", headers=ctx.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def advance(ctx: Ctx, opportunity_id: str, to_stage: str, reason: str | None = None):
    payload = {"to_stage": to_stage}
    if reason is not None:
        payload["reason"] = reason
    return await ctx.client.post(
        f"/api/v1/opportunities/{opportunity_id}/advance",
        headers=ctx.headers,
        json=payload,
    )


async def advance_to_deal_closure(ctx: Ctx, opportunity_id: str) -> None:
    for stage in ("solution_discussion", "business_negotiation", "deal_closure"):
        response = await advance(ctx, opportunity_id, stage)
        assert response.status_code == 200, response.text


VALID_DEAL = {
    "deal_type": "new_business",
    "deal_date": "2026-11-17",
    "confirmation_method": "written_contract",
    "scale_range": "scale_100k_500k",
}
