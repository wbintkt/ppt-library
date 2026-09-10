"""slide_merger 合并测试：验证原始页面抽取、样式/尺寸保持、可编辑性"""
import io
import os
import sys
import zipfile

import pytest
from pptx import Presentation
from pptx.util import Emu

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.slide_merger import merge_pages, MergeError
from app.services.ppt_parser import extract_native_texts

# 真实原始文件（测试环境固定路径）
ORIG1 = "/data/ppt-library/originals/ppt_000001.pptx"
ORIG2 = "/data/ppt-library/originals/ppt_000002.pptx"


def _mk_pptx(n_slides=2, size=(12192000, 6858000), label="test"):
    """用 python-pptx 造一个小文件（含文字框 + 形状，验证可编辑性）"""
    buf = io.BytesIO()
    prs = Presentation()
    prs.slide_width = Emu(size[0])
    prs.slide_height = Emu(size[1])
    for i in range(n_slides):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        tb = slide.shapes.add_textbox(Emu(100000), Emu(100000), Emu(3000000), Emu(500000))
        tb.text_frame.text = f"{label}-page{i+1}"
        slide.shapes.add_shape(1, Emu(500000), Emu(2000000), Emu(2000000), Emu(1000000))
    prs.save(buf)
    buf.seek(0)
    return buf


def _mk_pptx_with_media(n_slides=3):
    """造一个多页文件，仅最后一页带图片（其余页不含媒体）"""
    buf = io.BytesIO()
    prs = Presentation()
    prs.slide_width = Emu(12192000)
    prs.slide_height = Emu(6858000)
    for i in range(n_slides):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        tb = slide.shapes.add_textbox(Emu(100000), Emu(100000), Emu(3000000), Emu(500000))
        tb.text_frame.text = f"media-page{i+1}"
        if i == n_slides - 1:
            # 1x1 透明 PNG
            import base64
            png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
            )
            slide.shapes.add_picture(io.BytesIO(png), Emu(100000), Emu(100000))
    prs.save(buf)
    buf.seek(0)
    return buf


@pytest.fixture(scope="module")
def tmp_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("ppt_src")
    f1 = d / "a.pptx"
    f2 = d / "b.pptx"
    f1.write_bytes(_mk_pptx(2, (12192000, 6858000), "A").getvalue())
    f2.write_bytes(_mk_pptx(3, (12192000, 6858000), "B").getvalue())
    return f1, f2


def test_merge_single_file_pages(tmp_files, tmp_path):
    """同一文件抽取 2 页（含乱序页码），顺序保持勾选顺序"""
    f1, _ = tmp_files
    out = tmp_path / "out1.pptx"
    merge_pages([{"path": str(f1), "pages": [2, 1]}], out)

    prs = Presentation(str(out))
    assert len(prs.slides) == 2
    # 验证内容可编辑：第一页应是原第 2 页（"A-page2"）
    texts = []
    for slide in prs.slides:
        for sh in slide.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                texts.append(sh.text_frame.text)
    assert texts == ["A-page2", "A-page1"], texts


def test_prune_orphan_media_on_single_page_export(tmp_path):
    """只导 1 页时，未选中页的媒体应被剪除（瘦身）"""
    f = tmp_path / "media.pptx"
    f.write_bytes(_mk_pptx_with_media(3).getvalue())

    # 全量导出（3 页）：媒体保留
    out_all = tmp_path / "all.pptx"
    merge_pages([{"path": str(f), "pages": [1, 2, 3]}], out_all)
    with zipfile.ZipFile(out_all) as zf:
        media_all = [n for n in zf.namelist() if n.startswith("ppt/media/")]
        assert media_all, "全量导出应保留媒体"

    # 只导第 1 页：媒体（仅在第 3 页）应被剪除
    out_one = tmp_path / "one.pptx"
    merge_pages([{"path": str(f), "pages": [1]}], out_one)
    with zipfile.ZipFile(out_one) as zf:
        media_one = [n for n in zf.namelist() if n.startswith("ppt/media/")]
        assert media_one == [], f"单页导出不应携带其他页媒体: {media_one}"
        assert "ppt/slides/slide2.xml" not in zf.namelist()
        assert "ppt/slides/slide3.xml" not in zf.namelist()
    prs = Presentation(str(out_one))
    assert len(prs.slides) == 1
    assert prs.slides[0].shapes[0].has_text_frame
    with zipfile.ZipFile(out_one) as zf:
        assert zf.testzip() is None

    # 只导第 3 页：媒体应保留（该页引用）
    out_media = tmp_path / "media_only.pptx"
    merge_pages([{"path": str(f), "pages": [3]}], out_media)
    with zipfile.ZipFile(out_media) as zf:
        media_m = [n for n in zf.namelist() if n.startswith("ppt/media/")]
        assert len(media_m) == 1, media_m
    prs = Presentation(str(out_media))
    assert len(prs.slides) == 1
    assert len(prs.slides[0].shapes) >= 2  # 文字 + 图片
    # 尺寸保持
    assert prs.slide_width == Emu(12192000)
    assert prs.slide_height == Emu(6858000)
    # 形状仍为原生（非图片）
    for slide in prs.slides:
        assert any(sh.shape_type != 13 for sh in slide.shapes)


def test_merge_cross_files(tmp_files, tmp_path):
    """跨文件合并：A 第 1 页 + B 第 3 页"""
    f1, f2 = tmp_files
    out = tmp_path / "out2.pptx"
    merge_pages([{"path": str(f1), "pages": [1]}, {"path": str(f2), "pages": [3]}], out)

    prs = Presentation(str(out))
    assert len(prs.slides) == 2
    texts = []
    for slide in prs.slides:
        for sh in slide.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                texts.append(sh.text_frame.text)
    assert texts == ["A-page1", "B-page3"], texts


@pytest.mark.parametrize("hidden_value", ["0", "false"])
def test_export_visible_pages_matches_preview_text(tmp_path, hidden_value):
    """首部/中间/末尾隐藏页不占预览页码，单页下载也必须取到可见页。"""
    src = tmp_path / "hidden.pptx"
    prs = Presentation(_mk_pptx(5, label="visible"))
    for index in (0, 2, 4):
        prs.slides[index]._element.set("show", hidden_value)
    prs.save(src)
    assert extract_native_texts(str(src)) == ["visible-page2", "visible-page4"]

    for pages in ([1], [2], [2, 1]):
        out = tmp_path / "visible.pptx"
        merge_pages([{"path": str(src), "pages": pages, "page_count": 2}], out)
        slides = Presentation(out).slides
        assert [s.shapes[0].text for s in slides] == [
            extract_native_texts(str(src))[p - 1] for p in pages
        ]
        assert all(s._element.get("show") not in {"0", "false"} for s in slides)

    with pytest.raises(MergeError, match="页码越界"):
        merge_pages([{"path": str(src), "pages": [3]}], tmp_path / "bad.pptx")
    with pytest.raises(MergeError, match="预览不一致"):
        merge_pages([{"path": str(src), "pages": [1], "page_count": 5}],
                    tmp_path / "stale.pptx")


def test_interleaved_sources_with_hidden_slides(tmp_path):
    paths = []
    for label in ("A", "B"):
        path = tmp_path / f"{label}.pptx"
        prs = Presentation(_mk_pptx(4, label=label))
        prs.slides[0]._element.set("show", "0")
        prs.slides[2]._element.set("show", "0")
        prs.save(path)
        paths.append(path)
    a, b = paths
    out = tmp_path / "interleaved.pptx"
    merge_pages([
        {"path": a, "pages": [2]}, {"path": b, "pages": [1]},
        {"path": a, "pages": [1]}, {"path": b, "pages": [2]},
    ], out)
    assert [s.shapes[0].text for s in Presentation(out).slides] == [
        "A-page4", "B-page2", "A-page2", "B-page4",
    ]
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None


def test_merge_size_mismatch_rejected(tmp_files, tmp_path):
    """尺寸不一致应报错"""
    d = tmp_path
    f1, _ = tmp_files
    f3 = d / "c.pptx"
    f3.write_bytes(_mk_pptx(1, (9144000, 6858000), "C").getvalue())  # 4:3
    out = d / "out3.pptx"
    with pytest.raises(MergeError, match="尺寸"):
        merge_pages([{"path": str(f1), "pages": [1]}, {"path": str(f3), "pages": [1]}], out)


def test_merge_real_files(tmp_path):
    """真实库文件（公司介绍.pptx，16:9）抽取 2 页，验证可编辑且尺寸正确"""
    if not os.path.exists(ORIG2):
        pytest.skip("真实原始文件不存在")
    out = tmp_path / "real.pptx"
    merge_pages([{"path": ORIG2, "pages": [1, 3]}], out)

    prs = Presentation(str(out))
    assert len(prs.slides) == 2
    assert prs.slide_width == Emu(12192000)
    assert prs.slide_height == Emu(6858000)
    # 检查有原生文本/形状（可编辑性）
    shape_counts = [len(slide.shapes) for slide in prs.slides]
    assert all(c > 0 for c in shape_counts)
    # zip 完整性
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None


def test_merge_real_cross_files_size_mismatch(tmp_path):
    """真实跨文件合并：两个原始文件尺寸不同（4:3 vs 16:9），应报错"""
    if not (os.path.exists(ORIG1) and os.path.exists(ORIG2)):
        pytest.skip("真实原始文件不存在")
    out = tmp_path / "real_cross.pptx"
    with pytest.raises(MergeError, match="尺寸"):
        merge_pages(
            [{"path": ORIG1, "pages": [1]}, {"path": ORIG2, "pages": [2]}],
            out,
        )
