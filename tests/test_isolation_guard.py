"""守卫测试：隔离护栏本身必须拒绝远程、缺 host 与非 PG 的连接串。

这些用例不连数据库，只验证 ``_assert_isolated_pg`` 的判定，防止护栏被后续改动悄悄放宽。
"""

from __future__ import annotations

import pytest

from tests.conftest import _assert_isolated_pg


@pytest.mark.parametrize(
    "url, reason",
    [
        ("postgresql+psycopg://e2e@db.example.com:5432/opportunity_e2e_test", "远程主机"),
        ("postgresql+psycopg://e2e@10.0.0.5:5432/opportunity_e2e_test", "内网地址"),
        ("postgresql+psycopg://e2e@127.0.0.1:5432/opportunity_prod", "库名不含 test/e2e"),
        ("postgresql+psycopg:///opportunity_e2e_test", "省略 host（Unix socket）"),
        ("sqlite+pysqlite:///./.data/e2e.sqlite3", "非 PostgreSQL"),
    ],
)
def test_guard_rejects_non_isolated_targets(url, reason):
    with pytest.raises(RuntimeError) as excinfo:
        _assert_isolated_pg(url)
    message = str(excinfo.value)
    assert any(word in message for word in ("拒绝", "必须", "只接受")), f"{reason}: {message}"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://e2e@127.0.0.1:55433/opportunity_e2e_test",
        "postgresql+psycopg://e2e@localhost:55433/app_test",
        "postgresql+psycopg://e2e@[::1]:55433/opportunity_e2e",
    ],
)
def test_guard_accepts_local_test_databases(url):
    _assert_isolated_pg(url)
