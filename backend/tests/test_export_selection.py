"""Offline API regression: the downloaded slides must match selection exactly."""
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.util import Inches

from app.main import app
from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import PPTFile, PPTPage


@pytest.fixture
def export_client(tmp_path, monkeypatch):
    files, pages = [], []
    for fid in (1, 2):
        prs = Presentation()
        for native_index in range(4):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = (
                f"file{fid}-native{native_index + 1}"
            )
            if native_index in (0, 2):
                slide._element.set("show", "0")
        path = tmp_path / f"{fid}.pptx"
        prs.save(path)
        files.append(SimpleNamespace(id=fid, file_path=str(path), page_count=2))
        pages.extend(SimpleNamespace(id=fid * 10 + n, file_id=fid, page_no=n)
                     for n in (1, 2))
    db = MagicMock()
    def query(model):
        q = MagicMock()
        if model is PPTPage:
            q.filter.return_value.all.return_value = pages
        elif model is PPTFile:
            q.all.return_value = files
        return q
    db.query.side_effect = query
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: "test"
    try:
        yield TestClient(app), files
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)


@pytest.mark.parametrize("ids,expected", [
    ([12], ["file1-native4"]),
    ([12, 21, 11, 22], ["file1-native4", "file2-native2", "file1-native2", "file2-native4"]),
    ([12, 12], ["file1-native4"]),
])
def test_export_selected_content_and_order(export_client, ids, expected):
    client, _ = export_client
    response = client.post("/api/pages/export", json={"page_ids": ids})
    assert response.status_code == 200, response.text
    deck = Presentation(io.BytesIO(response.content))
    assert [s.shapes[0].text for s in deck.slides] == expected


@pytest.mark.parametrize("ids", [[999, 11], [999]])
def test_no_silent_missing_selection(export_client, ids):
    client, _ = export_client
    assert client.post("/api/pages/export", json={"page_ids": ids}).status_code == 404


def test_no_silent_missing_file(export_client):
    client, files = export_client
    files[1].file_path += ".missing"
    assert client.post("/api/pages/export", json={"page_ids": [11, 21]}).status_code == 404


def test_stale_preview_is_rejected(export_client):
    client, files = export_client
    files[0].page_count = 4
    response = client.post("/api/pages/export", json={"page_ids": [11]})
    assert response.status_code == 400
    assert "预览不一致" in response.json()["detail"]


@pytest.mark.parametrize("ids", [[True], ["11"], [[11]], [-1]])
def test_invalid_selection(export_client, ids):
    client, _ = export_client
    assert client.post("/api/pages/export", json={"page_ids": ids}).status_code == 400
