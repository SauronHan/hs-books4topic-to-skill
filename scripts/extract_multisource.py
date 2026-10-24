#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_multisource.py - 多源文档独立提取引擎 (hs-books4topic-to-skill 专用)

功能：
- 纯独立提取，零外部技能依赖；
- 原生支持 PDF, EPUB, Markdown, TXT, DOCX, HTML/HTM, RTF；
- MOBI/AZW/AZW3 通过 Calibre ebook-convert 中转支持；
- 支持传入 1~N 个文件路径或目录；
- 输出双层结构：
  - 索引层 (all_sources_index.json)：章节标题/摘要/统计，Agent 可全量读取
  - 分片层 (chunks/)：每个章节独立 JSON 文件，Agent 按需精准读取

安全特性：
- 路径边界检查：拒绝工作区/用户目录以外的路径
- 最大文件数限制（默认 50）
- 符号链接安全解析
"""

import os
import sys
import json
import argparse
import re
import posixpath
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import unquote

# ---------------------------------------------------------------------------
# 安全常量
# ---------------------------------------------------------------------------
MAX_FILES_DEFAULT = 50
MAX_SUMMARY_CHARS = 500  # 索引层中每章节摘要的最大字符数

# ---------------------------------------------------------------------------
# PDF 引擎检测与加载
# ---------------------------------------------------------------------------
PDF_ENGINE = None
try:
    import fitz  # PyMuPDF
    PDF_ENGINE = "fitz"
except ImportError:
    try:
        import pypdf
        PDF_ENGINE = "pypdf"
    except ImportError:
        PDF_ENGINE = None

# EPUB / HTML 解析检测
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

import zipfile
import xml.etree.ElementTree as ET

# DOCX 解析检测
try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False


# ===========================================================================
# 安全工具
# ===========================================================================

def is_safe_path(filepath: str) -> bool:
    """检查路径是否在安全边界内（工作目录或用户目录下）"""
    try:
        resolved = Path(filepath).resolve()
        cwd = Path.cwd().resolve()
        home = Path.home().resolve()
        return (
            resolved == cwd
            or resolved == home
            or _is_relative_to(resolved, cwd)
            or _is_relative_to(resolved, home)
        )
    except (OSError, ValueError):
        return False


def _is_relative_to(path: Path, base: Path) -> bool:
    """兼容 Python 3.8 的 is_relative_to 替代实现"""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


# ===========================================================================
# 文本清洗
# ===========================================================================

def clean_text(text: str) -> str:
    """清洗文本空白字符与杂乱控制符"""
    if not text:
        return ""
    # 替换不可见控制字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # 替换多余空行，最多连续保留两行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def make_summary(text: str, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    """生成章节摘要（截取前 N 个字符），用于索引层"""
    if not text:
        return ""
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    # 尽量在句号或换行处截断
    truncated = clean[:max_chars]
    for sep in ['。', '.\n', '\n', '. ', '；', ';']:
        last_pos = truncated.rfind(sep)
        if last_pos > max_chars // 2:
            return truncated[:last_pos + len(sep)].strip() + "…"
    return truncated.strip() + "…"


# ===========================================================================
# 格式提取器
# ===========================================================================

def epub_href(opf_dir: str, href: str) -> str:
    """将 EPUB 内部相对链接归一化为与 spine 可比较的路径。"""
    path = unquote(href.split("#", 1)[0]).replace("\\", "/")
    return posixpath.normpath(posixpath.join(opf_dir, path) if opf_dir else path)


def local_tag(element: ET.Element) -> str:
    """返回 XML 标签的本地名称，忽略命名空间。"""
    return element.tag.split("}")[-1]


def epub_toc_titles(
    zf: zipfile.ZipFile,
    opf_dir: str,
    manifest: Dict[str, str],
    manifest_meta: Dict[str, Dict[str, str]],
) -> Dict[str, str]:
    """读取 NCX 或 EPUB3 nav，为 spine 条目恢复真实目录标题。"""
    titles: Dict[str, str] = {}

    ncx_ids = [
        item_id for item_id, meta in manifest_meta.items()
        if meta.get("media_type") == "application/x-dtbncx+xml"
    ]
    nav_ids = [
        item_id for item_id, meta in manifest_meta.items()
        if "nav" in meta.get("properties", "").split()
    ]

    for item_id in ncx_ids:
        toc_path = epub_href(opf_dir, manifest[item_id])
        try:
            toc = ET.fromstring(zf.read(toc_path))
        except (KeyError, ET.ParseError):
            continue
        for point in toc.iter():
            if local_tag(point) != "navPoint":
                continue
            label = next((
                text.text.strip()
                for node in point.iter() if local_tag(node) == "navLabel"
                for text in node.iter() if local_tag(text) == "text" and text.text and text.text.strip()
            ), "")
            content = next((
                node.attrib.get("src", "")
                for node in point.iter() if local_tag(node) == "content"
            ), "")
            if label and content:
                titles.setdefault(epub_href(posixpath.dirname(toc_path), content), label)

    for item_id in nav_ids:
        nav_path = epub_href(opf_dir, manifest[item_id])
        try:
            nav_bytes = zf.read(nav_path)
        except KeyError:
            continue
        if BS4_AVAILABLE:
            soup = BeautifulSoup(nav_bytes, "html.parser")
            for link in soup.find_all("a", href=True):
                label = link.get_text(" ", strip=True)
                if label:
                    titles.setdefault(epub_href(posixpath.dirname(nav_path), link["href"]), label)
        else:
            try:
                nav = ET.fromstring(nav_bytes)
            except ET.ParseError:
                continue
            for link in nav.iter():
                if local_tag(link) == "a" and link.attrib.get("href") and (link.text or "").strip():
                    titles.setdefault(
                        epub_href(posixpath.dirname(nav_path), link.attrib["href"]),
                        link.text.strip(),
                    )

    return titles

def extract_pdf(filepath: str) -> Dict[str, Any]:
    """提取 PDF 文档内容与章节结构"""
    filepath = os.path.abspath(filepath)
    filename = os.path.basename(filepath)
    chapters = []
    total_chars = 0
    title = Path(filepath).stem

    if PDF_ENGINE == "fitz":
        doc = fitz.open(filepath)
        title = doc.metadata.get("title") or title
        toc = doc.get_toc()  # [[lvl, title, page], ...]
        page_count = len(doc)

        if toc:
            # 依据目录书签切分章节
            for idx, item in enumerate(toc):
                lvl, c_title, p_num = item
                # 确定结束页
                end_page = page_count
                if idx + 1 < len(toc):
                    end_page = toc[idx + 1][2]

                # 提取起止页内容 (页码为1-indexed)
                p_start = max(0, p_num - 1)
                p_end = min(page_count, end_page)
                ch_text = []
                for p in range(p_start, p_end):
                    ch_text.append(doc[p].get_text())

                content = clean_text("\n".join(ch_text))
                c_len = len(content)
                total_chars += c_len
                chapters.append({
                    "title": c_title.strip(),
                    "level": lvl,
                    "page_start": p_num,
                    "page_end": end_page,
                    "char_count": c_len,
                    "content": content
                })
        else:
            # 无书签时按页提取整书
            full_text = []
            for p in range(page_count):
                full_text.append(doc[p].get_text())
            content = clean_text("\n".join(full_text))
            total_chars = len(content)
            chapters.append({
                "title": "Full Document",
                "level": 1,
                "page_start": 1,
                "page_end": page_count,
                "char_count": total_chars,
                "content": content
            })
        doc.close()

    elif PDF_ENGINE == "pypdf":
        reader = pypdf.PdfReader(filepath)
        page_count = len(reader.pages)
        full_text = []
        for p in reader.pages:
            t = p.extract_text()
            if t:
                full_text.append(t)
        content = clean_text("\n".join(full_text))
        total_chars = len(content)
        chapters.append({
            "title": "Full Document",
            "level": 1,
            "page_start": 1,
            "page_end": page_count,
            "char_count": total_chars,
            "content": content
        })
    else:
        raise RuntimeError("未检测到可用的 PDF 引擎 (PyMuPDF 或 pypdf)")

    return {
        "source_file": filepath,
        "format": "pdf",
        "title": title,
        "total_chars": total_chars,
        "chapter_count": len(chapters),
        "chapters": chapters
    }


def extract_epub(filepath: str) -> Dict[str, Any]:
    """提取 EPUB 电子书内容与章节"""
    filepath = os.path.abspath(filepath)
    title = Path(filepath).stem
    chapters = []
    total_chars = 0

    # 定义 OPF/OPF 命名空间
    OPF_NS = {'opf': 'http://www.idpf.org/2007/opf',
              'dc': 'http://purl.org/dc/elements/1.1/',
              'container': 'urn:oasis:names:tc:opendocument:xmlns:container'}

    with zipfile.ZipFile(filepath, 'r') as zf:
        # 查找 container.xml
        try:
            container_xml = zf.read("META-INF/container.xml")
            tree = ET.fromstring(container_xml)
            rootfile_path = ""
            # 使用 namespace 通配或显式查找
            for elem in tree.iter():
                tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if tag_local == "rootfile" and "full-path" in elem.attrib:
                    rootfile_path = elem.attrib["full-path"]
                    break
        except Exception:
            rootfile_path = ""

        if not rootfile_path:
            # 备选遍历寻找 opf
            for name in zf.namelist():
                if name.endswith(".opf"):
                    rootfile_path = name
                    break

        if not rootfile_path:
            raise ValueError(f"无法在 EPUB 中解析 OPF 元数据: {filepath}")

        opf_dir = os.path.dirname(rootfile_path)
        opf_data = zf.read(rootfile_path)
        opf_tree = ET.fromstring(opf_data)

        # 提取标题
        for elem in opf_tree.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local == "title" and elem.text:
                title = elem.text.strip()
                break

        # 建立 manifest 字典 id -> href
        manifest = {}
        manifest_meta = {}
        for elem in opf_tree.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local == "item" and "id" in elem.attrib and "href" in elem.attrib:
                manifest[elem.attrib["id"]] = elem.attrib["href"]
                manifest_meta[elem.attrib["id"]] = {
                    "media_type": elem.attrib.get("media-type", ""),
                    "properties": elem.attrib.get("properties", ""),
                }

        # 解析 spine 阅读顺序
        spine_hrefs = []
        for elem in opf_tree.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local == "itemref" and "idref" in elem.attrib:
                idref = elem.attrib["idref"]
                if idref in manifest:
                    full_href = epub_href(opf_dir, manifest[idref])
                    spine_hrefs.append(full_href)

        toc_titles = epub_toc_titles(zf, opf_dir, manifest, manifest_meta)

        # 依次读取章节 HTML 并提取文本
        for idx, href in enumerate(spine_hrefs):
            try:
                html_bytes = zf.read(href)
            except KeyError:
                continue

            if BS4_AVAILABLE:
                soup = BeautifulSoup(html_bytes, "html.parser")
                # 优先使用目录标题；页面标题经常只是书名，不能覆盖真实章节名。
                ch_title = toc_titles.get(href, "")
                if not ch_title:
                    continuation = re.sub(r'_split_\d+(\.[^.]+)$', r'_split_000\1', href)
                    ch_title = toc_titles.get(continuation, "")
                if not ch_title:
                    header = soup.find(["h1", "h2", "h3", "title"])
                    if header and header.text:
                        ch_title = header.text.strip()
                if not ch_title:
                    ch_title = f"Section {idx + 1}"
                text = clean_text(soup.get_text())
            else:
                # 简易正则去标签
                raw_str = html_bytes.decode('utf-8', errors='ignore')
                text = clean_text(re.sub(r'<[^>]+>', ' ', raw_str))
                ch_title = f"Section {idx + 1}"

            c_len = len(text)
            if c_len < 30:  # 忽略极小空白占位节
                continue

            total_chars += c_len
            chapters.append({
                "title": ch_title,
                "level": 1,
                "href": href,
                "char_count": c_len,
                "content": text
            })

    return {
        "source_file": filepath,
        "format": "epub",
        "title": title,
        "total_chars": total_chars,
        "chapter_count": len(chapters),
        "chapters": chapters
    }


def extract_markdown_or_txt(filepath: str) -> Dict[str, Any]:
    """提取 Markdown 或纯文本文件"""
    filepath = os.path.abspath(filepath)
    title = Path(filepath).stem
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    lines = content.splitlines()
    chapters = []
    current_title = "Introduction"
    current_lines = []
    current_level = 1

    for line in lines:
        match = re.match(r'^(#{1,3})\s+(.+)$', line)
        if match:
            if current_lines:
                ch_text = clean_text("\n".join(current_lines))
                if ch_text:
                    chapters.append({
                        "title": current_title,
                        "level": current_level,
                        "char_count": len(ch_text),
                        "content": ch_text
                    })
                current_lines = []
            current_level = len(match.group(1))
            current_title = match.group(2).strip()
        else:
            current_lines.append(line)

    if current_lines:
        ch_text = clean_text("\n".join(current_lines))
        if ch_text:
            chapters.append({
                "title": current_title,
                "level": current_level,
                "char_count": len(ch_text),
                "content": ch_text
            })

    if not chapters:
        c_clean = clean_text(content)
        chapters.append({
            "title": title,
            "level": 1,
            "char_count": len(c_clean),
            "content": c_clean
        })

    total_chars = sum(ch["char_count"] for ch in chapters)
    return {
        "source_file": filepath,
        "format": "markdown/txt",
        "title": title,
        "total_chars": total_chars,
        "chapter_count": len(chapters),
        "chapters": chapters
    }


def extract_docx(filepath: str) -> Dict[str, Any]:
    """提取 DOCX 文档内容"""
    if not DOCX_AVAILABLE:
        raise RuntimeError("未检测到 python-docx 模块")
    filepath = os.path.abspath(filepath)
    title = Path(filepath).stem
    doc = docx.Document(filepath)

    chapters = []
    current_title = "Document"
    current_lines = []
    current_level = 1

    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        if p.style.name.startswith("Heading"):
            if current_lines:
                ch_text = clean_text("\n".join(current_lines))
                if ch_text:
                    chapters.append({
                        "title": current_title,
                        "level": current_level,
                        "char_count": len(ch_text),
                        "content": ch_text
                    })
                current_lines = []
            try:
                current_level = int(p.style.name.replace("Heading", "").strip())
            except ValueError:
                current_level = 1
            current_title = txt
        else:
            current_lines.append(txt)

    if current_lines:
        ch_text = clean_text("\n".join(current_lines))
        if ch_text:
            chapters.append({
                "title": current_title,
                "level": current_level,
                "char_count": len(ch_text),
                "content": ch_text
            })

    total_chars = sum(ch["char_count"] for ch in chapters)
    return {
        "source_file": filepath,
        "format": "docx",
        "title": title,
        "total_chars": total_chars,
        "chapter_count": len(chapters),
        "chapters": chapters
    }


def extract_html(filepath: str) -> Dict[str, Any]:
    """提取 HTML / HTM 网页电子书"""
    filepath = os.path.abspath(filepath)
    title = Path(filepath).stem
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        raw_html = f.read()

    if BS4_AVAILABLE:
        soup = BeautifulSoup(raw_html, "html.parser")
        t_tag = soup.find(["title", "h1"])
        if t_tag and t_tag.text:
            title = t_tag.text.strip()
        text = clean_text(soup.get_text())
    else:
        text = clean_text(re.sub(r'<[^>]+>', ' ', raw_html))

    chapters = [{
        "title": title,
        "level": 1,
        "char_count": len(text),
        "content": text
    }]

    return {
        "source_file": filepath,
        "format": "html",
        "title": title,
        "total_chars": len(text),
        "chapter_count": 1,
        "chapters": chapters
    }


def extract_rtf(filepath: str) -> Dict[str, Any]:
    """提取 RTF 富文本文档（实验性支持，复杂 RTF 建议先转为 DOCX）"""
    filepath = os.path.abspath(filepath)
    title = Path(filepath).stem

    # 优先使用 striprtf 库（更可靠）
    try:
        from striprtf.striprtf import rtf_to_text
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        text = clean_text(rtf_to_text(content))
    except ImportError:
        # 回退到简易正则（仅适用于简单 RTF）
        print("[提示] 未安装 striprtf 库，使用简易正则提取 RTF（复杂格式可能丢失内容）", file=sys.stderr)
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        text = re.sub(r'\{\*?\\[^{}]+?\}', '', content)
        text = re.sub(r'\\[a-zA-Z0-9]+ ?', '', text)
        text = re.sub(r'[{}]', '', text)
        text = clean_text(text)

    chapters = [{
        "title": title,
        "level": 1,
        "char_count": len(text),
        "content": text
    }]

    return {
        "source_file": filepath,
        "format": "rtf",
        "title": title,
        "total_chars": len(text),
        "chapter_count": 1,
        "chapters": chapters
    }


def extract_kindle_via_calibre(filepath: str) -> Optional[Dict[str, Any]]:
    """若检测到 Calibre ebook-convert，自动将 mobi/azw 临时转为 epub 提取"""
    import shutil
    import subprocess
    import tempfile

    convert_bin = shutil.which("ebook-convert")
    if not convert_bin:
        print(f"[提示] 未在 PATH 检测到 Calibre 的 'ebook-convert' 工具。"
              f"如需直接读取 MOBI/AZW3 文件，请安装 Calibre，"
              f"或先将书籍另存为 EPUB: {filepath}", file=sys.stderr)
        return None

    filepath = os.path.realpath(filepath)
    if not os.path.isfile(filepath):
        print(f"[错误] 文件不存在或不是常规文件: {filepath}", file=sys.stderr)
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_epub = os.path.join(tmp_dir, "converted.epub")
        try:
            # 使用 -- 分隔符防止文件名被误解析为选项
            res = subprocess.run(
                [convert_bin, "--", filepath, temp_epub],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            if os.path.exists(temp_epub):
                data = extract_epub(temp_epub)
                data["source_file"] = filepath
                data["format"] = "mobi/azw (via calibre)"
                return data
        except Exception as e:
            print(f"[错误] 调用 ebook-convert 转换失败: {e}", file=sys.stderr)
            return None


def parse_source(filepath: str) -> Optional[Dict[str, Any]]:
    """统一调度多格式分发器"""
    if not os.path.exists(filepath):
        print(f"[警告] 文件不存在: {filepath}", file=sys.stderr)
        return None

    lower_path = filepath.lower()
    if lower_path.endswith(".pdf"):
        return extract_pdf(filepath)
    elif lower_path.endswith(".epub"):
        return extract_epub(filepath)
    elif lower_path.endswith((".md", ".markdown", ".txt")):
        return extract_markdown_or_txt(filepath)
    elif lower_path.endswith(".docx"):
        return extract_docx(filepath)
    elif lower_path.endswith((".html", ".htm")):
        return extract_html(filepath)
    elif lower_path.endswith(".rtf"):
        return extract_rtf(filepath)
    elif lower_path.endswith((".mobi", ".azw", ".azw3")):
        return extract_kindle_via_calibre(filepath)
    else:
        print(f"[跳过] 暂不支持的文件格式: {filepath}", file=sys.stderr)
        return None


# ===========================================================================
# 输出层：索引 + 分片
# ===========================================================================

def write_chunk_files(out_dir: Path, book_idx: int, book_slug: str,
                      doc_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """将单本书的章节写入独立分片文件，返回索引条目列表"""
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(exist_ok=True)

    chapter_index_entries = []
    for ch_idx, chapter in enumerate(doc_data.get("chapters", []), 1):
        chunk_filename = f"b{book_idx:02d}_ch{ch_idx:02d}_{book_slug}.json"
        chunk_path = chunks_dir / chunk_filename

        # 写入分片文件（含全文内容）
        chunk_data = {
            "book_title": doc_data.get("title", ""),
            "book_index": book_idx,
            "chapter_index": ch_idx,
            "chapter_title": chapter.get("title", ""),
            "level": chapter.get("level", 1),
            "char_count": chapter.get("char_count", 0),
            "content": chapter.get("content", "")
        }
        with open(chunk_path, "w", encoding="utf-8") as f:
            json.dump(chunk_data, f, ensure_ascii=False, indent=2)

        # 生成索引条目（不含全文，只含摘要）
        chapter_index_entries.append({
            "chapter_index": ch_idx,
            "title": chapter.get("title", ""),
            "level": chapter.get("level", 1),
            "char_count": chapter.get("char_count", 0),
            "summary": make_summary(chapter.get("content", "")),
            "chunk_file": f"chunks/{chunk_filename}"
        })

    return chapter_index_entries


# ===========================================================================
# 主入口
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="多源文档独立提取引擎 (hs-books4topic-to-skill)")
    parser.add_argument("--sources", "-s", nargs="+", required=True,
                        help="1~N 个源文件路径或目录")
    parser.add_argument("--output-dir", "-o", required=True,
                        help="结构化结果输出目录")
    parser.add_argument("--topic", "-t", default="",
                        help="可选：本次合成的主题标签")
    parser.add_argument("--max-files", type=int, default=MAX_FILES_DEFAULT,
                        help=f"最大源文件数量限制（默认 {MAX_FILES_DEFAULT}）")
    args = parser.parse_args()

    out_dir = Path(os.path.abspath(args.output_dir))
    skill_dir = Path(__file__).resolve().parents[1]
    if out_dir.is_relative_to(skill_dir):
        parser.error("提取输出目录必须位于元 Skill 目录之外")
    for src in args.sources:
        source_dir = Path(src).resolve()
        if source_dir.is_dir() and out_dir.is_relative_to(source_dir):
            parser.error("提取输出目录不能位于输入书籍目录内")
    out_dir.mkdir(parents=True, exist_ok=True)

    SUPPORTED_EXTS = [
        ".pdf", ".epub", ".docx", ".html", ".htm",
        ".md", ".markdown", ".txt", ".rtf",
        ".mobi", ".azw", ".azw3"
    ]

    collected_sources = []
    skipped_unsafe = []

    # 展开目录与路径，带安全检查
    for src in args.sources:
        p = Path(src)
        if p.is_dir():
            # 安全检查：目录本身
            if not is_safe_path(str(p)):
                skipped_unsafe.append(str(p))
                print(f"[安全] 拒绝访问工作区外目录: {p}", file=sys.stderr)
                continue
            for f in sorted(p.glob("**/*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                    if len(collected_sources) >= args.max_files:
                        print(f"[警告] 达到最大文件数限制 ({args.max_files})，"
                              f"停止收集", file=sys.stderr)
                        break
                    collected_sources.append(str(f))
        elif p.is_file():
            if not is_safe_path(str(p)):
                skipped_unsafe.append(str(p))
                print(f"[安全] 拒绝访问工作区外文件: {p}", file=sys.stderr)
                continue
            if len(collected_sources) >= args.max_files:
                print(f"[警告] 达到最大文件数限制 ({args.max_files})，"
                      f"停止收集", file=sys.stderr)
                break
            collected_sources.append(str(p))
        else:
            print(f"[警告] 路径不存在: {src}", file=sys.stderr)

    # 去重（保持顺序）
    collected_sources = list(dict.fromkeys(str(Path(source).resolve()) for source in collected_sources))

    if not collected_sources:
        print("[错误] 未收集到任何有效源文件", file=sys.stderr)
        sys.exit(1)

    print(f"[*] 准备提取 {len(collected_sources)} 个源文档...")
    if skipped_unsafe:
        print(f"[*] 已跳过 {len(skipped_unsafe)} 个不安全路径")

    # ---- 提取 & 输出 ----
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    source_index_entries = []
    failures: List[Dict[str, str]] = []
    summary_lines = [
        "# 多源提取资产汇总报告",
        f"- **主题目标**: {args.topic if args.topic else '未指定'}",
        f"- **源文件数量**: {len(collected_sources)}",
        f"- **生成时间**: {now_str}\n",
        "| 书籍/文档名称 | 格式 | 章节数 | 总字符数 | 原始路径 |",
        "| :--- | :---: | :---: | :---: | :--- |"
    ]

    total_books_chars = 0
    for idx, filepath in enumerate(collected_sources, 1):
        print(f"[{idx}/{len(collected_sources)}] 正在提取: {filepath}")
        try:
            doc_data = parse_source(filepath)
            if not doc_data:
                failures.append({"source_file": filepath, "reason": "提取器未返回文档数据"})
                continue
            if not doc_data.get("total_chars") or not doc_data.get("chapters"):
                failures.append({"source_file": filepath, "reason": "提取结果为空或没有可用分片"})
                continue

            total_books_chars += doc_data["total_chars"]
            summary_lines.append(
                f"| **{doc_data['title']}** | {doc_data['format']} "
                f"| {doc_data['chapter_count']} "
                f"| {doc_data['total_chars']:,} | `{filepath}` |"
            )

            # 写入分片文件 + 生成索引条目
            book_slug = re.sub(r'[^\w\-_]', '_', Path(filepath).stem)[:50]
            chapter_entries = write_chunk_files(
                out_dir, idx, book_slug, doc_data)

            source_index_entries.append({
                "book_index": idx,
                "title": doc_data["title"],
                "format": doc_data["format"],
                "source_file": filepath,
                "total_chars": doc_data["total_chars"],
                "chapter_count": doc_data["chapter_count"],
                "chapters": chapter_entries  # 索引层：标题+摘要+路径
            })
        except Exception as e:
            failures.append({"source_file": filepath, "reason": str(e)})
            print(f"[错误] 提取失败 {filepath}: {e}", file=sys.stderr)

    # ---- 写入索引层 JSON（不含全文内容，Agent 可安全全量读取） ----
    index_file = out_dir / "all_sources_index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({
            "topic": args.topic,
            "generated_at": now_str,
            "requested_sources": len(collected_sources),
            "total_sources": len(source_index_entries),
            "total_chars": total_books_chars,
            "sources": source_index_entries,
            "failed_sources": failures,
        }, f, ensure_ascii=False, indent=2)

    # ---- 写入 Markdown 汇总报告 ----
    summary_lines.append(f"\n- **总计全库字符数**: {total_books_chars:,} 字符")
    if failures:
        summary_lines.append("\n## 提取失败（阻断后续全量合成）\n")
        for failure in failures:
            summary_lines.append(f"- `{failure['source_file']}`：{failure['reason']}")
    summary_lines.append(f"\n## 输出结构说明\n")
    summary_lines.append(
        "- `all_sources_index.json`：索引层，包含每本书的章节标题、摘要与统计。"
        "Agent 应首先读取此文件获取全局视图。")
    summary_lines.append(
        "- `chunks/`：分片层，每个章节一个独立 JSON 文件。"
        "Agent 按需读取特定章节的全文内容。")
    summary_file = out_dir / "extraction_summary.md"
    with open(summary_file, "w", encoding="utf-8") as sf:
        sf.write("\n".join(summary_lines) + "\n")

    print(f"\n[✓] 提取完成！")
    print(f"    - 索引文件: {index_file}")
    print(f"    - 分片目录: {out_dir / 'chunks/'}")
    print(f"    - 概览报告: {summary_file}")
    print(f"    - 总字数规模: {total_books_chars:,} 字符")
    if failures:
        print(f"[错误] {len(failures)} 个来源提取失败或为空；索引和报告已保留以供诊断。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
