"""PPT 解析服务：LibreOffice 转换 + 文本提取

流程：pptx/ppt --(soffice)--> pdf --(pdftoppm)--> 每页 png
      --(pdftotext)--> 每页文本
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import settings


class PPTParseError(Exception):
    pass


def _run(cmd: list, timeout: int = 300) -> None:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise PPTParseError(f"命令超时: {' '.join(cmd[:4])}...")
    if proc.returncode != 0:
        raise PPTParseError(
            f"命令失败({proc.returncode}): {' '.join(cmd[:4])}...\n{proc.stderr[-500:]}"
        )


def _find_soffice() -> str:
    for cand in ("/usr/bin/libreoffice", "/usr/bin/soffice", "/opt/libreoffice*/program/soffice"):
        import glob
        hits = glob.glob(cand)
        if hits:
            return hits[0]
    raise PPTParseError("未找到 LibreOffice，无法解析 PPT")


def convert_to_pdf(src_path: str, out_dir: str) -> str:
    """PPT -> PDF，返回 pdf 路径"""
    soffice = _find_soffice()
    profile = tempfile.mkdtemp(prefix="lo_profile_")
    _run([
        soffice, "--headless",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to", "pdf",
        "--outdir", out_dir,
        src_path,
    ], timeout=600)
    shutil.rmtree(profile, ignore_errors=True)
    base = Path(src_path).stem
    pdf = Path(out_dir) / f"{base}.pdf"
    if not pdf.exists():
        # 尝试找任意生成的 pdf
        pdfs = list(Path(out_dir).glob("*.pdf"))
        if not pdfs:
            raise PPTParseError("LibreOffice 转换失败：未生成 PDF")
        pdf = pdfs[0]
    return str(pdf)


def pdf_to_pngs(pdf_path: str, out_dir: str, dpi: int = 130) -> int:
    """PDF -> 每页 PNG（page_001.png 起），返回页数"""
    prefix = str(Path(out_dir) / "page")
    _run(["pdftoppm", "-png", "-r", str(dpi), pdf_path, prefix], timeout=300)
    # 重命名为 page_001.png 格式
    files = sorted(Path(out_dir).glob("page-*.png"))
    for i, f in enumerate(files, start=1):
        f.rename(Path(out_dir) / f"page_{i:03d}.png")
    return len(files)


def extract_page_text(pdf_path: str, page_no: int) -> str:
    """提取 PDF 指定页文本"""
    proc = subprocess.run(
        ["pdftotext", "-f", str(page_no), "-l", str(page_no), "-layout", pdf_path, "-"],
        capture_output=True, text=True, timeout=120,
    )
    text = proc.stdout or ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def guess_title(text: str) -> str:
    """从文本推断页面标题：取第一段短文本"""
    if not text:
        return ""
    for line in text.split("\n"):
        line = line.strip()
        if line and len(line) <= 60:
            return line
    return text.split("\n")[0].strip()[:60]


def parse_ppt(src_path: str, work_dir: str) -> dict:
    """完整解析一个 PPT：
    返回 { page_count, pages: [{page_no, png_path, text, title}] }
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    png_dir = work_dir / "pngs"
    png_dir.mkdir(exist_ok=True)

    # 1. 转 PDF
    pdf_path = convert_to_pdf(src_path, str(work_dir))
    # 2. 生成每页 PNG
    page_count = pdf_to_pngs(pdf_path, str(png_dir))
    if page_count == 0:
        raise PPTParseError("PDF 页数为 0")

    # 3. 提取每页文本 + 标题
    pages = []
    for no in range(1, page_count + 1):
        text = extract_page_text(pdf_path, no)
        title = guess_title(text)
        png = png_dir / f"page_{no:03d}.png"
        pages.append({
            "page_no": no,
            "png_path": str(png),
            "text": text,
            "title": title,
        })

    # 清理中间 pdf（保留 pngs）
    try:
        Path(pdf_path).unlink()
    except OSError:
        pass

    return {"page_count": page_count, "pages": pages}
