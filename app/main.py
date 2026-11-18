"""FastAPI application for the opportunity closure chain (reference harness).

Endpoints mirror the contracts referenced by the task's acceptance criteria:

* ``POST /api/v1/matches/{id}/convert``       对接转商机
* ``POST /api/v1/opportunities/{id}/advance`` 瀑布流阶段推进
* ``POST /api/v1/opportunities/{id}/deals``   成交记录（仅统计字段）
* ``POST /api/v1/opportunities/{id}/close``   关闭商机
* ``GET  /api/v1/opportunities/{id}/waterfall`` 瀑布流 + 留痕
* ``GET  /api/v1/stats/opportunity-conversion`` 商机转化率
* ``GET  /api/v1/demands``                     需求广场
* ``GET  /waterfall/{id}``                     瀑布流页面（Playwright 截图用）

Path / field names are the harness contract; the integrating service can be
retargeted by setting ``BASE_URL`` for the test suite (see README).
"""

from __future__ import annotations

import html
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from . import seed
from .config import settings
from .db import get_db, init_schema, session_scope
from .errors import UNEXPECTED_FIELD, ContractError
from .identity import Identity, identity
from .models import Demand
from .schemas import (
    STAGE_LABELS,
    AdvanceRequest,
    CloseRequest,
    ConversionRateOut,
    DemandOut,
    OpportunityDetailOut,
    WaterfallOut,
)
from .service import (
    advance_stage,
    close_opportunity,
    conversion_rate,
    convert_match,
    create_deal_record,
    plaza_demands,
    waterfall,
)

DEMO_IDENTITY = Identity(org_id=seed.DEFAULT_ORG, site_id=seed.DEFAULT_SITE, user_id=seed.DEFAULT_USER)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_schema:
        init_schema()
    if settings.seed_demo_data:
        with session_scope() as db:
            existing = db.query(Demand).count()
            if existing == 0:
                seed.seed_held_match(db)
    yield


app = FastAPI(title="Opportunity closure chain (test harness)", lifespan=lifespan)


@app.exception_handler(ContractError)
async def contract_error_handler(_: Request, exc: ContractError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/matches/{match_id}/convert", response_model=OpportunityDetailOut)
def convert(
    match_id: uuid.UUID,
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> OpportunityDetailOut:
    return convert_match(db, ident, match_id)


@app.get("/api/v1/opportunities/{opportunity_id}", response_model=OpportunityDetailOut)
def get_opportunity(
    opportunity_id: uuid.UUID,
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> OpportunityDetailOut:
    from .service import _get_opportunity, _detail  # local import keeps module surface small

    return _detail(db, _get_opportunity(db, ident, opportunity_id))


@app.get("/api/v1/opportunities/{opportunity_id}/waterfall", response_model=WaterfallOut)
def get_waterfall(
    opportunity_id: uuid.UUID,
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> WaterfallOut:
    return waterfall(db, ident, opportunity_id)


@app.post("/api/v1/opportunities/{opportunity_id}/advance", response_model=OpportunityDetailOut)
def advance(
    opportunity_id: uuid.UUID,
    body: AdvanceRequest,
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> OpportunityDetailOut:
    return advance_stage(db, ident, opportunity_id, body)


@app.post("/api/v1/opportunities/{opportunity_id}/deals")
async def create_deal(
    opportunity_id: uuid.UUID,
    request: Request,
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        raw = await request.json()
    except Exception:
        raise ContractError(422, UNEXPECTED_FIELD, "请求体必须是合法 JSON 对象") from None
    if not isinstance(raw, dict):
        raise ContractError(422, UNEXPECTED_FIELD, "请求体必须是 JSON 对象")
    result = create_deal_record(db, ident, opportunity_id, raw)
    return JSONResponse(status_code=201, content=result)


@app.post("/api/v1/opportunities/{opportunity_id}/close", response_model=OpportunityDetailOut)
def close(
    opportunity_id: uuid.UUID,
    body: CloseRequest,
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> OpportunityDetailOut:
    return close_opportunity(db, ident, opportunity_id, body)


@app.get("/api/v1/stats/opportunity-conversion", response_model=ConversionRateOut)
def stats(
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> ConversionRateOut:
    return conversion_rate(db, ident)


@app.get("/api/v1/demands", response_model=list[DemandOut])
def list_demands(
    include_all: bool = False,
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> list[DemandOut]:
    return [DemandOut.model_validate(row) for row in plaza_demands(db, ident, include_all)]


@app.get("/api/v1/demands/{demand_id}", response_model=DemandOut)
def get_demand(
    demand_id: uuid.UUID,
    ident: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> DemandOut:
    demand = (
        db.query(Demand)
        .filter(
            Demand.id == demand_id,
            Demand.org_id == ident.org_id,
            Demand.deleted_at.is_(None),
        )
        .one_or_none()
    )
    if demand is None:
        raise ContractError(404, "NOT_FOUND", "需求不存在")
    return DemandOut.model_validate(demand)


@app.get("/waterfall/{opportunity_id}", response_class=HTMLResponse)
def waterfall_page(
    opportunity_id: uuid.UUID,
    org: str = seed.DEFAULT_ORG,
    site: str = seed.DEFAULT_SITE,
    user: str = seed.DEFAULT_USER,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Read-only waterfall view used only as screenshot evidence."""

    ident = Identity(org_id=org, site_id=site, user_id=user)
    data = waterfall(db, ident, opportunity_id)
    stages_html = "".join(
        f"""<li class="stage {'is-current' if stage['key'] == data.current_stage else ''}">
             <span class="dot"></span>
             <div><strong>{html.escape(stage['label'])}</strong>
             <small>{html.escape(stage['key'])}</small></div>
           </li>"""
        for stage in data.stages
    )
    history_rows = "".join(
        f"""<tr>
             <td>{row.sequence}</td>
             <td>{html.escape(STAGE_LABELS.get(row.from_stage, row.from_stage))}</td>
             <td>{html.escape(STAGE_LABELS.get(row.to_stage, row.to_stage))}</td>
             <td>{html.escape(row.operator_id)}</td>
             <td>{row.occurred_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
             <td>{html.escape(row.reason or '-')}</td>
           </tr>"""
        for row in data.history
    ) or "<tr><td colspan='6' class='empty'>暂无推进留痕</td></tr>"

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>商机瀑布流 · 演示数据</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f5f6f8; color: #1f2329; }}
    header {{ padding: 20px 32px; background: #fff; border-bottom: 1px solid #e7e9ec; }}
    header h1 {{ margin: 0 0 6px; font-size: 20px; font-weight: 600; }}
    header p {{ margin: 0; color: #6b7280; font-size: 13px; }}
    main {{ padding: 24px 32px 40px; }}
    .card {{ background: #fff; border: 1px solid #e7e9ec; border-radius: 10px;
             padding: 20px 24px; margin-bottom: 20px; }}
    .card h2 {{ margin: 0 0 16px; font-size: 15px; font-weight: 600; }}
    .meta {{ display: flex; gap: 32px; flex-wrap: wrap; font-size: 13px; color: #4b5563; }}
    ul.stages {{ display: flex; gap: 12px; list-style: none; padding: 0; margin: 0; }}
    ul.stages li.stage {{ flex: 1; display: flex; align-items: center; gap: 10px;
        padding: 14px; border-radius: 8px; background: #f7f8fa; border: 1px solid #ebedf0; }}
    li.stage .dot {{ width: 10px; height: 10px; border-radius: 50%; background: #c7ccd4; }}
    li.stage.is-current {{ background: #e8f1ff; border-color: #2f6bff; }}
    li.stage.is-current .dot {{ background: #2f6bff; }}
    li.stage div strong {{ display: block; font-size: 14px; }}
    li.stage div small {{ color: #8a9099; font-size: 11px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #eef0f2; }}
    th {{ color: #6b7280; font-weight: 500; background: #fafbfc; }}
    td.empty {{ color: #9aa0a6; text-align: center; }}
    footer {{ color: #9aa0a6; font-size: 12px; padding: 0 32px 32px; }}
  </style>
</head>
<body>
  <header>
    <h1>商机瀑布流</h1>
    <p>演示数据 · 仅用于回归测试截图，不含真实企业与个人信息</p>
  </header>
  <main>
    <section class="card">
      <h2>{html.escape(data.status)} · {html.escape(STAGE_LABELS.get(data.current_stage, data.current_stage))}</h2>
      <div class="meta">
        <span>商机 ID：{data.opportunity_id}</span>
        <span>推进次数：{len(data.history)}</span>
      </div>
    </section>
    <section class="card">
      <h2>阶段</h2>
      <ul class="stages">{stages_html}</ul>
    </section>
    <section class="card">
      <h2>推进留痕（操作人 / 时间 / 前后阶段）</h2>
      <table>
        <thead>
          <tr><th>#</th><th>原阶段</th><th>新阶段</th><th>操作人</th><th>时间（UTC）</th><th>备注</th></tr>
        </thead>
        <tbody>{history_rows}</tbody>
      </table>
    </section>
  </main>
  <footer>虚构数据 · 参考实现 · 仅本地回归使用</footer>
</body>
</html>"""
    return HTMLResponse(page)
