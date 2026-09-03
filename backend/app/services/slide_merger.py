"""PPTX 页面级合并：从原始 .pptx 中抽取指定页，合并为一份新 .pptx。

保持原始页面的一切样式（版式/母版/主题/媒体/备注/图表/嵌入对象），
输出为可编辑的原生 PPT 页面（非图片）。

策略：
1. 宿主 = 第一个选中页所在文件：其全部 part 作为基底
2. 其他文件：整体搬迁资源目录（media/charts/embeddings/diagrams/tags/
   slideLayouts/slideMasters/theme/notesMasters/notesSlides），重名加后缀
   （_f1/_f2...），选中页 slide 重新编号；所有搬入 part 的 rels 按改名映射重写
3. 重建 presentation.xml：sldIdLst 按勾选顺序；sldSz 保持宿主；搬入的
   slideMaster 注册进 sldMasterIdLst + rels
4. 合并 [Content_Types].xml（Override 按新路径、Default 按扩展名）
"""
import zipfile
from pathlib import Path

from lxml import etree

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}

REL_SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
REL_LAYOUT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
REL_MASTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
REL_THEME = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
REL_NOTES_MASTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster"

# 需要整体搬迁的资源目录（相对 ppt/）
RESOURCE_DIRS = [
    "media", "charts", "embeddings", "diagrams", "tags", "queries",
    "slideLayouts", "slideMasters", "theme", "notesMasters", "notesSlides",
]


class MergeError(Exception):
    pass


# ---------- 工具 ----------

import posixpath


def _norm_part(path: str, base: str = "/") -> str:
    """rels 相对 Target -> 绝对 part 路径。
    base: rels 所在 part 的目录（如 /ppt、/ppt/slides）。
    """
    if path.startswith("/"):
        return posixpath.normpath(path)
    return posixpath.normpath(posixpath.join(base, path))


def _parse(data: bytes):
    return etree.fromstring(data)


def _rels_of(zf: zipfile.ZipFile, part: str):
    """读 part 的 rels XML（可能为 None）"""
    rels_name = _rels_name(part)
    if rels_name in zf.namelist():
        return _parse(zf.read(rels_name))
    return None


def _rels_name(part: str) -> str:
    """part 对应的 rels 文件路径（zip 内路径）"""
    p = part.lstrip("/")
    return f"{posixpath.dirname(p)}/_rels/{Path(p).name}.rels"


def _iter_rels(root):
    for el in root:
        if etree.QName(el).localname == "Relationship":
            yield el


def _slide_order(zf: zipfile.ZipFile):
    """显示顺序的 slide part 列表（绝对路径）"""
    prs = _parse(zf.read("ppt/presentation.xml"))
    rels = _parse(zf.read("ppt/_rels/presentation.xml.rels"))
    # presentation.xml.rels 位于 ppt/_rels/，Target 相对 ppt/
    rmap = {r.get("Id"): _norm_part(r.get("Target"), base="/ppt") for r in _iter_rels(rels)}
    order = []
    lst = prs.find(".//p:sldIdLst", NS)
    if lst is not None:
        for sld in lst:
            rid = sld.get(f"{{{NS['r']}}}id")
            if rid in rmap:
                order.append(rmap[rid])
    return order


def _slide_size(zf: zipfile.ZipFile):
    prs = _parse(zf.read("ppt/presentation.xml"))
    sz = prs.find(".//p:sldSz", NS)
    return (sz.get("cx"), sz.get("cy")) if sz is not None else None


# ---------- 主入口 ----------

def merge_pages(sources: list[dict], out_path: str | Path):
    """sources: [{"path": str, "pages": [1,3]}]，pages 为显示页码（按勾选顺序）"""
    if not sources:
        raise MergeError("没有可合并的页面")

    # 1. 解析各源文件
    parsed = []
    for src in sources:
        path = Path(src["path"])
        if not path.exists():
            raise MergeError(f"源文件不存在: {path.name}")
        try:
            with zipfile.ZipFile(path) as zf:
                order = _slide_order(zf)
                size = _slide_size(zf)
        except Exception as e:
            raise MergeError(f"无法解析 {path.name}: {e}")
        if not order:
            raise MergeError(f"无法解析 {path.name} 的页面结构")
        parsed.append({"path": path, "order": order, "size": size, "pages": src["pages"]})

    # 2. 尺寸一致性（保证原始比例）
    base_size = parsed[0]["size"]
    for p in parsed[1:]:
        if p["size"] != base_size:
            raise MergeError(
                "所选页面来自不同页面尺寸的 PPT（如 16:9 与 4:3），"
                "无法合并为一份保持原始比例的文件，请按比例分开导出。"
            )

    # 3. 宿主基底：第一个文件的全部 part
    host_path = parsed[0]["path"]
    parts: dict[str, bytes] = {}  # 绝对 part -> bytes
    with zipfile.ZipFile(host_path) as zf:
        for name in zf.namelist():
            if not name.endswith("/"):
                parts["/" + name] = zf.read(name)

    # 4. 搬迁
    next_slide = max(
        (int(Path(p).stem.replace("slide", "")) for p in parts
         if p.startswith("/ppt/slides/slide") and p.endswith(".xml")),
        default=0,
    ) + 1

    new_slides = []  # [(目标 slide part, 源文件索引)]
    mapping: dict[str, str] = {}  # 源绝对 part -> 目标绝对 part（跨文件汇总）

    for fi, src in enumerate(parsed):
        if fi == 0:
            for page_no in src["pages"]:
                if not (1 <= page_no <= len(src["order"])):
                    raise MergeError(f"页码越界: {page_no}")
                new_slides.append((src["order"][page_no - 1], 0))
            continue

        with zipfile.ZipFile(src["path"]) as zf:
            names = set(zf.namelist())
            file_mapping = {}

            # 4a. 资源目录整体搬迁
            prefix = f"_f{fi}"
            for d in RESOURCE_DIRS:
                for name in names:
                    if not (name.startswith(f"ppt/{d}/") and not name.endswith("/")):
                        continue
                    src_part = "/" + name
                    fname = Path(name).name
                    new_name = f"ppt/{d}/{fname}"
                    # 重名冲突（宿主或其他文件已占用）
                    if ("/" + new_name) in parts or any(
                        v == "/" + new_name for v in file_mapping.values()
                    ):
                        stem, ext = Path(fname).stem, Path(fname).suffix
                        new_name = f"ppt/{d}/{stem}{prefix}{ext}"
                    file_mapping[src_part] = "/" + new_name

            # 4b. 选中页 slide
            for page_no in src["pages"]:
                if not (1 <= page_no <= len(src["order"])):
                    raise MergeError(f"页码越界: {page_no}")
                src_slide = src["order"][page_no - 1]
                dst_slide = f"/ppt/slides/slide{next_slide}.xml"
                next_slide += 1
                file_mapping[src_slide] = dst_slide
                new_slides.append((dst_slide, fi))

            # 4c. 写入文件内容（二进制/XML 原样），并重写 rels
            for src_part, dst_part in file_mapping.items():
                name = src_part.lstrip("/")
                if name not in names:
                    continue
                parts[dst_part] = zf.read(name)
                # 该 part 若有 rels，也搬 + 重写 Target
                src_rels = _rels_name(src_part)
                if src_rels in names:
                    rels_root = _parse(zf.read(src_rels))
                    base_dir = posixpath.dirname(src_part)  # rels Target 相对 part 所在目录
                    for rel in _iter_rels(rels_root):
                        t = rel.get("Target", "")
                        if t.startswith(("http://", "https://", "mailto:")):
                            continue
                        abs_t = _norm_part(t, base=base_dir)
                        if abs_t in file_mapping:
                            rel.set("Target", file_mapping[abs_t])
                        else:
                            # 引用宿主已有资源：转绝对路径
                            rel.set("Target", abs_t)
                    parts[_rels_name(dst_part)] = etree.tostring(
                        rels_root, xml_declaration=True, encoding="UTF-8", standalone=True
                    )

            mapping.update(file_mapping)

    # 5. 重建 presentation.xml + rels + Content_Types
    _rebuild(parts, new_slides)

    # 5b. 剪除孤儿 part（未选中页的 slide/媒体等），瘦身输出包
    _prune_orphans(parts)

    # 6. 打包
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for part, data in sorted(parts.items()):
            zout.writestr(part.lstrip("/"), data)


def _prune_orphans(parts: dict[str, bytes]):
    """剪除展示图之外的孤儿 part，瘦身输出包。

    宿主基底是整份源文件（含未选中页及其媒体），
    重建后的 presentation 图只引用选中页；从包级 rels + presentation.xml
    出发沿 rels 递归可达的 part 全部保留，其余（未选中页的 slide、
    layout、notes、media、embeddings 等）删除。
    同时清理 [Content_Types].xml 中指向已删 part 的 Override。
    """
    keep = {"/[Content_Types].xml"}
    if "/docProps/thumbnail.jpeg" in parts:
        keep.add("/docProps/thumbnail.jpeg")
    queue = ["/_rels/.rels", "/ppt/presentation.xml"]
    while queue:
        part = queue.pop()
        if part in keep:
            continue
        keep.add(part)
        rn = "/" + _rels_name(part)  # parts key 带前导斜杠
        if rn not in parts:
            continue
        root = _parse(parts[rn])
        base = posixpath.dirname(part)  # rels Target 相对 part 所在目录
        for rel in _iter_rels(root):
            t = rel.get("Target", "")
            if t.startswith(("http://", "https://", "mailto:", "ftp://")):
                continue
            target = _norm_part(t, base=base)
            if target not in keep:
                queue.append(target)

    # part 的 rels 文件随 part 保留
    for part in list(keep):
        rn = "/" + _rels_name(part)
        if rn in parts:
            keep.add(rn)

    removed = [p for p in parts if p not in keep]
    for p in removed:
        del parts[p]

    if removed:
        ct = _parse(parts["/[Content_Types].xml"])
        for el in list(ct):
            if (
                etree.QName(el).localname == "Override"
                and el.get("PartName") in removed
            ):
                ct.remove(el)
        parts["/[Content_Types].xml"] = etree.tostring(
            ct, xml_declaration=True, encoding="UTF-8", standalone=True
        )


def _rebuild(parts: dict[str, bytes], new_slides: list):
    """重建 presentation.xml、presentation.xml.rels、[Content_Types].xml"""
    prs = _parse(parts["/ppt/presentation.xml"])
    prs_rels = _parse(parts["/ppt/_rels/presentation.xml.rels"])

    # --- presentation.xml.rels：保留非 slide 关系，slide 关系按新列表重建 ---
    for rel in list(_iter_rels(prs_rels)):
        if rel.get("Type") == REL_SLIDE:
            prs_rels.remove(rel)

    rid = 1000
    slide_rid: dict[str, str] = {}
    for slide_part, _fi in new_slides:
        rid += 1
        r = etree.SubElement(prs_rels, f"{{{NS['pr']}}}Relationship")
        r.set("Id", f"rId{rid}")
        r.set("Type", REL_SLIDE)
        r.set("Target", slide_part[len("/ppt/"):])  # 相对 ppt/
        slide_rid[slide_part] = f"rId{rid}"

    # --- presentation.xml：sldIdLst 按勾选顺序 ---
    old_lst = prs.find(".//p:sldIdLst", NS)
    if old_lst is not None:
        prs.remove(old_lst)
    new_lst = etree.Element(f"{{{NS['p']}}}sldIdLst")
    # 插到 sldMasterIdLst 之后（若无则最前）
    master_lst = prs.find(".//p:sldMasterIdLst", NS)
    if master_lst is not None:
        master_lst.addnext(new_lst)
    else:
        prs.insert(0, new_lst)

    sid = 256
    for slide_part, _fi in new_slides:
        sid += 1
        r = etree.SubElement(new_lst, f"{{{NS['p']}}}sldId")
        r.set("id", str(sid))
        r.set(f"{{{NS['r']}}}id", slide_rid.get(slide_part, ""))

    # --- 注册搬入的 slideMaster（若有）到 sldMasterIdLst ---
    # 找出 /ppt/slideMasters/ 下所有 master，确保它们在 rels 中
    master_targets = {r.get("Target") for r in _iter_rels(prs_rels) if r.get("Type") == REL_MASTER}
    master_lst_el = prs.find(".//p:sldMasterIdLst", NS)
    existing_master_ids = set()
    if master_lst_el is not None:
        for m in master_lst_el:
            if etree.QName(m).localname == "sldMasterId":
                existing_master_ids.add(m.get("id"))
    next_mid = 2147483648
    for part in list(parts):
        if part.startswith("/ppt/slideMasters/slideMaster") and part.endswith(".xml"):
            t = part[len("/ppt/"):]
            if t not in master_targets:
                rid += 1
                r = etree.SubElement(prs_rels, f"{{{NS['pr']}}}Relationship")
                r.set("Id", f"rId{rid}")
                r.set("Type", REL_MASTER)
                r.set("Target", t)
                master_targets.add(t)
                # 加入 sldMasterIdLst（若存在该元素）
                if master_lst_el is not None:
                    while str(next_mid) in existing_master_ids:
                        next_mid += 1
                    m = etree.SubElement(master_lst_el, f"{{{NS['p']}}}sldMasterId")
                    m.set("id", str(next_mid))
                    m.set(f"{{{NS['r']}}}id", f"rId{rid}")
                    existing_master_ids.add(str(next_mid))

    prs_bytes = etree.tostring(prs, xml_declaration=True, encoding="UTF-8", standalone=True)
    rels_bytes = etree.tostring(prs_rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    parts["/ppt/presentation.xml"] = prs_bytes
    parts["/ppt/_rels/presentation.xml.rels"] = rels_bytes

    # --- [Content_Types].xml：合并 ---
    ct = _parse(parts["/[Content_Types].xml"])
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    # 收集已有 Default 扩展名 和 Override part 名
    default_exts = {
        el.get("Extension").lower()
        for el in ct if etree.QName(el).localname == "Default" and el.get("Extension")
    }
    override_parts = {
        el.get("PartName")
        for el in ct if etree.QName(el).localname == "Override" and el.get("PartName")
    }

    def _ensure_override(part: str, content_type: str):
        pname = "/" + part.lstrip("/")
        if pname in override_parts:
            return
        el = etree.SubElement(ct, f"{{{ct_ns}}}Override")
        el.set("PartName", pname)
        el.set("ContentType", content_type)
        override_parts.add(pname)

    def _ensure_default(ext: str, content_type: str):
        if ext.lower() in default_exts:
            return
        el = etree.SubElement(ct, f"{{{ct_ns}}}Default")
        el.set("Extension", ext)
        el.set("ContentType", content_type)
        default_exts.add(ext.lower())

    # slide / layout / master / theme / notes 的 content types（固定映射，key 为 part 顶层目录）
    CT_FIXED = {
        "slides": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
        "slideLayouts": "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
        "slideMasters": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
        "theme": "application/vnd.openxmlformats-officedocument.theme+xml",
        "notesSlides": "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml",
        "notesMasters": "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml",
        "charts": "application/vnd.openxmlformats-officedocument.drawingml.chart+xml",
        "diagrams": "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml",
        "tags": "application/vnd.openxmlformats-officedocument.presentationml.tags+xml",
    }
    for part in list(parts):
        if not part.startswith("/ppt/") or part.endswith(".rels"):
            continue
        rel = part[len("/ppt/"):]
        top = rel.split("/")[0]
        if top in CT_FIXED:
            _ensure_override(part, CT_FIXED[top])
        elif top == "media":
            ext = Path(part).suffix.lstrip(".").lower()
            mime = {
                "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
                "gif": "image/gif", "bmp": "image/bmp", "tiff": "image/tiff",
                "emf": "image/x-emf", "wmf": "image/x-wmf", "webp": "image/webp",
                "wdp": "image/vnd.ms-photo", "svg": "image/svg+xml",
                "mp4": "video/mp4", "mov": "video/quicktime", "avi": "video/x-msvideo",
                "wmv": "video/x-ms-wmv", "mp3": "audio/mpeg", "wav": "audio/wav",
                "m4a": "audio/mp4",
            }.get(ext)
            if mime:
                _ensure_default(ext, mime)
        elif top in ("embeddings", "queries"):
            ext = Path(part).suffix.lstrip(".").lower()
            _ensure_default(ext, "application/vnd.openxmlformats-officedocument.oleObject")

    parts["/[Content_Types].xml"] = etree.tostring(
        ct, xml_declaration=True, encoding="UTF-8", standalone=True
    )
