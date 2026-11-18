# S4-E2E-019 · 商机推进到成交记录（不含资金字段）E2E 用例集

本仓库是工单 **S4-E2E-019** 的交付物：一套 `pytest + httpx` 端到端用例，覆盖
「对接转商机 → 瀑布流阶段推进 → 成交记录（仅统计字段）→ 关闭商机 → 需求置为 fulfilled 并下架」的闭环，
并附 Playwright 瀑布流页面截图、运行报告与 README。

- 公开仓库：https://github.com/PikachuGits/s4-e2e-019-opportunity-closure
- 默认分支：`main`（提交号以仓库页面为准，文档不固定引用，避免与仓库漂移）
- 本次运行：`25 passed`（SQLite 与 PostgreSQL 16.16 各跑一遍），覆盖率以对应报告为准
- 报告：`evidence/test-results.txt`（SQLite，87%–88%）、`evidence/test-results-postgres.txt`（PostgreSQL 16.16，86%）；`--cov=app`、`branch = true`，截图用例在子进程里执行，统计边界会让数值在 86%–88% 间波动，正文不写死固定值

> **边界声明（先读）**
>
> 1. 客户真实产品代码与 S3-MATCH（供需 / 匹配 / 商机）服务不在本仓库内。仓库内 `app/` 是**接口桩（参考实现）**，
>    用于让用例可独立复现，不声称它是客户最终实现。
> 2. 本单要求「依赖其他工单时用接口桩或 mock 先行，并在 README 写明对接点」，因此桩实现与用例是分开的：
>    用例只通过 HTTP 调用，把 `BASE_URL` 指向真实服务即可复用（见「复用到真实服务」）。
> 3. 全部数据为虚构数据，不含客户名称、真实企业或个人信息。
> 4. 状态语义：本仓库产出的是「用例 + 证据」，**不代表买方验收或结算**。

---

## 1. 验收映射

| 验收标准（原文） | 用例文件 | 可观察断言 |
|---|---|---|
| ① 阶段推进留痕条数等于推进次数 | `tests/test_e2e_opportunity_audit.py` | 推进 3 次 → `stage_history` 恰 3 条；`sequence=1..3`；每条含 `operator_id`、`occurred_at`（带时区）、`from_stage`/`to_stage`；相邻记录首尾相接；重复推进 / 跨阶段推进 / 并发推进均不增加留痕 |
| ② 提交收付款类字段返回 422 | `tests/test_e2e_no_fund_fields.py` | `amount_paid`、`payment_account`、`paid_amount`、`received_amount` 等（含嵌套对象、数组元素、camelCase 变体）一律 **422 + `FUND_FIELDS_FORBIDDEN`**；合法请求 201 且响应只含 4 个统计字段；`test_physical_table_schema_has_no_fund_columns` 在建表后用 `inspect()` 读物理 schema（SQLite 下另查 DDL 文本），证明资金列在数据库层面也不存在 |
| ③ 未选择原因的未成交关闭被拒绝 | `tests/test_e2e_lost_requires_reason.py` | `outcome=lost` 且无 `reason` / 空串 / 纯空格 → **422 + `LOST_REASON_REQUIRED`**，商机仍 `open`、`close_reason` 为空；带原因 → 200 且写入 `close_reason`；关闭后推进被 409 拒绝 |
| ④ 需求状态 fulfilled，需求广场查不到 | `tests/test_e2e_demand_fulfilled.py` | 走完成交闭环后：`GET /api/v1/demands/{id}` → `status=fulfilled`；`GET /api/v1/demands` 列表不含该需求；`?include_all=true`（管理与审计视角）仍可读到，避免「查不到 = 数据丢失」 |
| 范围补充：商机转化率统计接口更新 | `tests/test_e2e_demand_fulfilled.py::test_conversion_rate_updates_after_won_and_lost` | 成交 1 个 + 在途 1 个 → `{"won":1,"total":2,"conversion_rate":0.5}`（成交商机 ÷ 商机总数） |
| 范围补充：瀑布流页面 Playwright 截图 | `tests/test_e2e_waterfall_screenshot.py` | 起真实进程（uvicorn）→ 浏览器打开 `/waterfall/{id}` → 截图 `docs/screenshots/waterfall.png` |

---

## 2. 运行

### 2.1 默认路径（零外部依赖，本仓库证据即在此路径产出）

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium     # 仅截图用例需要
./scripts/test.sh                          # = pytest -v --cov=app --cov-report=term-missing
```

- 默认数据库是**一次性 SQLite 文件**（`.data/e2e-*.sqlite3`），每次运行新建，不连接任何共享库。
- 不开 `AUTO_CREATE_SCHEMA` 时改用 Alembic：`alembic upgrade head`（迁移脚本 `alembic/versions/0001_*.py`）。
- 截图用例在缺少 Playwright / 浏览器时**跳过**；跳过不算通过，报告里会标注 skip 原因。

### 2.2 PostgreSQL 16（已实跑，见 `evidence/test-results-postgres.txt`）

数据库由 Alembic 建表，测试夹具**不会**在 PG 上 `create_all`。必须显式给出隔离测试库 URL：

```bash
docker compose -f docker-compose.test.yml up -d            # 或任意本机 PG16
export TEST_DATABASE_URL='postgresql+psycopg://e2e:e2e@127.0.0.1:55432/opportunity_e2e_test'
export DATABASE_URL="$TEST_DATABASE_URL"                   # alembic 复用同一 URL
export AUTO_CREATE_SCHEMA=0
alembic upgrade head
./scripts/test.sh
```

夹具内置三条护栏（`tests/conftest.py::_assert_isolated_pg`）：只接受 `postgresql://`；host 必须是
`127.0.0.1`/`localhost`/`::1`；库名必须含 `test` 或 `e2e`。任一不满足直接失败，不会连到共享库。

**本次实测**（2026-11-18）：PostgreSQL 16.16（Homebrew，独立 cluster，端口 55433，数据库
`opportunity_e2e_test`）→ `alembic upgrade head` 建 6 张表（5 业务表 + `alembic_version`）→
**25 passed，覆盖率 86%**。SQLite 路径同期 25 passed / 87%–88%（截图用例在子进程，覆盖率随进程边界小幅波动，以报告为准）。

---

## 3. 交付物

| 文件 | 说明 |
|---|---|
| `tests/test_e2e_opportunity_audit.py` | AC-1 留痕条数、字段完整性、重复/越级/并发 |
| `tests/test_e2e_no_fund_fields.py` | AC-2 收付款字段拦截（顶层 / 嵌套 / 数组 / camelCase） |
| `tests/test_e2e_lost_requires_reason.py` | AC-3 未成交关闭必须选原因 |
| `tests/test_e2e_demand_fulfilled.py` | AC-4 需求 fulfilled 且广场下架 + 转化率 |
| `tests/test_e2e_waterfall_screenshot.py` | Playwright 截图 |
| `tests/conftest.py` | 夹具：每例独立清库，并用夹具构造「已举行的对接」前置数据 |
| `app/` | S3-MATCH 接口桩 + 商机闭环参考实现（仅用于让用例可运行） |
| `alembic/versions/0001_opportunity_closure_chain.py` | 表结构迁移（5 张表，含软删除与租户字段） |
| `docs/screenshots/waterfall.png` | 瀑布流页面截图（虚构数据） |
| `evidence/test-results.txt` | SQLite 路径运行报告（`25 passed`，绝对路径已脱敏为 `.`） |
| `evidence/test-results-postgres.txt` | PostgreSQL 16.16 路径运行报告（`25 passed`，覆盖率 86%） |
| `docker-compose.test.yml` | PG16（pgvector）+ Redis 7，仅绑定 127.0.0.1 |

---

## 4. 接口契约（桩实现口径，对接时以真实服务为准）

统一身份头：`X-Org-ID` / `X-Site-ID` / `X-User-ID`（由可信身份中间件注入，服务本身不做登录；
缺任一头 → 401 `IDENTITY_REQUIRED`）。所有查询按 `org_id` 隔离，跨组织访问按不存在处理（404）。

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/matches/{match_id}/convert` | 对接转商机（仅 `status=held` 的对接可转，重复转换 409） |
| GET | `/api/v1/opportunities/{id}` | 商机详情（含 `stage_history` / `deal_records`） |
| GET | `/api/v1/opportunities/{id}/waterfall` | 瀑布流：阶段定义 + 当前阶段 + 留痕 |
| POST | `/api/v1/opportunities/{id}/advance` | 阶段推进，body `{to_stage, reason?}` |
| POST | `/api/v1/opportunities/{id}/deals` | 成交记录，body 仅 4 个统计字段 |
| POST | `/api/v1/opportunities/{id}/close` | 关闭商机，body `{outcome: won\|lost, reason?}` |
| GET | `/api/v1/stats/opportunity-conversion` | 商机转化率（成交 ÷ 总数） |
| GET | `/api/v1/demands` `/api/v1/demands/{id}` | 需求广场列表 / 需求详情 |
| GET | `/waterfall/{id}` | 只读瀑布流页面（截图取证用） |

**阶段枚举**：`initial_contact`（初步接触）→ `solution_discussion`（方案沟通）→
`business_negotiation`（商务谈判）→ `deal_closure`（成交）。只能逐级推进，越级 422 `ILLEGAL_STAGE_TRANSITION`，
重复推进 409 `DUPLICATE_STAGE_ADVANCE`，并发推进只有一个成功（乐观锁 `version`）。

**成交记录字段（仅统计）**：`deal_type`（`new_business` / `renewal` / `expansion`）、`deal_date`、
`confirmation_method`（`written_contract` / `email_confirmation` / `meeting_minutes` / `platform_message`）、
`scale_range`（`scale_lt_100k` / `scale_100k_500k` / `scale_500k_2m` / `scale_gte_2m`，单位为「分」的区间标签）。

**收付款字段拦截**：对请求 JSON **整棵树**递归扫描键名（忽略大小写与 `_`/`-`），命中即
**422 `FUND_FIELDS_FORBIDDEN`**，覆盖 `amount_paid`、`payment_account`、`paid_amount`、
`received_amount`、`receiving_account`、`bank_account`、`payee`、`payer`、`transfer_amount`、
`currency`、`amount`、`price` 等（清单见 `app/fund_guard.py::FUND_FIELD_TOKENS`）。
成交记录表也只有统计列，物理上不存金额。未知非资金字段（如 `remark`）同样拒绝，避免字段悄悄落库。

**关闭规则**：`lost` 必填非空 `reason`（否则 422 `LOST_REASON_REQUIRED`）；`won` 必须已推进到
`deal_closure` 且存在成交记录（否则 409 `DEAL_RECORD_REQUIRED`），成功后对应需求 `status=fulfilled` 并从广场下架。

---

## 5. 假设与待确认项（原文未规定，已固化为可复现默认值）

| # | 假设 | 影响面 | 若买方口径不同 |
|---|---|---|---|
| 1 | 阶段键名与端点路径采用上表口径 | 全量用例路径 | 改 `app/schemas.py` 枚举 + 用例常量，一处改完 |
| 2 | 「成交」作为一个阶段，关闭时再区分 `won`/`lost` | 推进与关闭顺序 | 若成交/未成交本身就是两个并列阶段，需改 `advance` 的迁移表 |
| 3 | 成交记录只有 4 个统计字段，其余字段一律拒绝 | AC-2 之外的行为 | 若允许备注类字段，把白名单加进 `DealRecordRequest` 并从资金清单剔除 |
| 4 | 需求置 `fulfilled` 的触发点是「按成交关闭成功」 | AC-4 | 若改为「填成交记录即置 fulfilled」，改 `create_deal_record` 一处 |
| 5 | 需求广场仅隐藏 `fulfilled`/`closed`，管理视角可查 | AC-4 | 若广场要求对已成交需求返回 404，需要额外接口区分视角 |
| 6 | 转化率 = 成交商机 ÷ 商机总数（含在途与未成交） | 统计接口 | 若分母只算已关闭商机，改 `conversion_rate` 一处 |
| 7 | 并发推进用乐观锁版本号，冲突 409 | AC-1 并发用例 | 若按「串行排队」语义，用例期望需同步调整 |

**需要澄清的问题**（不改也能交付，接入时一次确认即可）：

1. 真实 S3-MATCH 的「对接」实体与「已举行」判定字段（本桩用 `status=held` + `held_at`）。
2. 真实服务的鉴权与身份头名称；本桩沿用项目内的 `X-Org-ID/X-Site-ID/X-User-ID` 约定。
3. 成交类型、双方确认方式、成交规模区间的正式枚举值（当前是按语义起的占位值）。
4. 未被要求但相关的行为：成交后是否允许「撤销成交」、是否允许一个对接生成多个商机（本桩为 1:1）。

---

## 6. 复用到真实服务

用例只依赖 HTTP，改造点只有一处：`tests/conftest.py` 里的 `ASGITransport` 换成真实地址，并把夹具构造
前置数据改为调用真实接口（或由被测环境预置）。

```python
AsyncClient(base_url=os.environ["BASE_URL"], headers=identity_headers)
```

对应关系：夹具 `seed.seed_held_match` ↔ 真实 S3-MATCH 的「创建需求 + 记录一次已举行对接」；
`seed.seed_extra_opportunity` ↔ 真实服务的第二个在途商机（转化率断言需要）。
Readme 中「假设与待确认项」同时就是对接清单。

## 7. 数据与保密

- 测试数据全部虚构（`虚构企业甲公司`、`demo-org`、`demo-site`、`demo-sales-01`）。
- 仓库不含客户名称、真实企业/个人信息、任何凭据或密钥；配置只从环境变量读取。
- 不引入任何会向境外发送数据的第三方 SDK；用例不发外部网络请求（截图用例只访问本机 uvicorn）。
- 数据库端口仅绑定 `127.0.0.1`，仅供本机联调。

## 8. 不做（修改边界）

- 不改客户前端业务页面：瀑布流页面只是桩里的只读展示页，用于截图取证。
- 不接真实外部服务（通知、IAM、S3-MATCH 线上实例），跨模块用桩并在上文标注对接点。
- 不覆盖资金结算、发票、合同文本、权限矩阵等其他工单范围。
- 不提供生产部署脚本；`docker-compose.test.yml` 仅测试用途。

## 9. 已知限制

- PostgreSQL 路径已实际运行（16.16，独立 cluster，见 §2.2 与 `evidence/test-results-postgres.txt`）；若客户环境是 16.x 的其他小版本，迁移与断言逻辑不变，仍建议在目标库复跑一次。
- 截图用例起真实 uvicorn 进程（约 3 秒）；CI 未安装浏览器时会 skip，报告会标注。
- 覆盖率以两份报告为准（`branch = true`，口径 `--cov=app`）：SQLite 87%–88%、PostgreSQL 86%（PG 走真实 schema，SQLite 专有的 DDL 文本断言分支不执行）；截图用例在子进程运行，统计随进程边界波动，正文不固定引用单一数值。
