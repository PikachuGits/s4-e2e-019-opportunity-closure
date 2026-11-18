"""交付证据：Playwright 打开商机瀑布流页面并截图。

未安装 Playwright 或浏览器时跳过，并在测试报告中注明原因（跳过的 E2E 不算通过）。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT = REPO_ROOT / "docs" / "screenshots" / "waterfall.png"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_health(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.3)
    raise RuntimeError("参考服务在 30 秒内未就绪")


def test_waterfall_page_screenshot(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        pytest.skip("playwright 未安装：跳过截图用例")

    database_url = f"sqlite+pysqlite:///{tmp_path / 'screenshot.sqlite3'}"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "AUTO_CREATE_SCHEMA": "1",
        "SEED_DEMO_DATA": "1",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_health(base_url)

        engine = create_engine(database_url)
        with engine.connect() as conn:
            match_hex = conn.execute(text("select id from match_records limit 1")).scalar()
        engine.dispose()
        assert match_hex, "夹具未生成已举行的对接"
        match_id = str(uuid.UUID(str(match_hex)))

        headers = {"X-Org-ID": "demo-org", "X-Site-ID": "demo-site", "X-User-ID": "demo-sales-01"}
        with httpx.Client(base_url=base_url, headers=headers, timeout=10.0) as client:
            opportunity_id = client.post(f"/api/v1/matches/{match_id}/convert").json()["id"]
            for stage in ("solution_discussion", "business_negotiation", "deal_closure"):
                response = client.post(
                    f"/api/v1/opportunities/{opportunity_id}/advance",
                    json={"to_stage": stage, "reason": "演示推进留痕"},
                )
                assert response.status_code == 200, response.text

        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(
                f"{base_url}/waterfall/{opportunity_id}?org=demo-org&site=demo-site&user=demo-sales-01",
                wait_until="networkidle",
            )
            assert "商机瀑布流" in page.title() or "商机瀑布流" in page.inner_text("body")
            page.screenshot(path=str(SCREENSHOT), full_page=True)
            browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()

    assert SCREENSHOT.exists()
    assert SCREENSHOT.stat().st_size > 0
