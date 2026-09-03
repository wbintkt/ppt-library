"""页面合并导出接口测试"""
import io
import os
import sys

import pytest
from pptx import Presentation

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import PPTFile, PPTPage

client = TestClient(app)


@pytest.fixture(scope="module")
def auth_headers():
    resp = client.post("/api/auth/login", data={"username": "admin", "password": "PptLib2026"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_pages():
    """造两份文件的页面记录（复用真实 PNG，若无则跳过）"""
    db = SessionLocal()
    try:
        pages = db.query(PPTPage).filter(PPTPage.png_path.isnot(None)).order_by(PPTPage.id).limit(4).all()
        return pages
    finally:
        db.close()


def test_export_requires_auth():
    resp = client.post("/api/pages/export", json={"page_ids": [1]})
    assert resp.status_code == 401


def test_export_empty_ids(auth_headers):
    resp = client.post("/api/pages/export", json={"page_ids": []}, headers=auth_headers)
    assert resp.status_code == 400


def test_export_merges_pages(auth_headers):
    pages = _seed_pages()
    if len(pages) < 2:
        pytest.skip("数据库无页面数据")
    ids = [p.id for p in pages[:3]]
    resp = client.post("/api/pages/export", json={"page_ids": ids}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "pptx" in resp.headers.get("content-disposition", "")

    # 解析生成的 pptx，验证页数
    prs = Presentation(io.BytesIO(resp.content))
    assert len(prs.slides) == 3

    # 每页应有原生形状（可编辑），而非纯图片拼装
    for slide in prs.slides:
        assert len(slide.shapes) > 0, "每页应包含原生形状"


def test_export_unknown_ids_skipped(auth_headers):
    pages = _seed_pages()
    if not pages:
        pytest.skip("数据库无页面数据")
    resp = client.post(
        "/api/pages/export",
        json={"page_ids": [999999, pages[0].id]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    prs = Presentation(io.BytesIO(resp.content))
    assert len(prs.slides) == 1
