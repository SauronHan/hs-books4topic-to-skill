#!/usr/bin/env python3
"""Create an honest, unclassified project ledger from an extraction index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="从多书提取索引建立主题 Skill 项目草稿")
    parser.add_argument("index", type=Path, help="all_sources_index.json")
    parser.add_argument("output_root", type=Path, help="新的项目根目录")
    parser.add_argument("--books-dir", type=Path, required=True, help="用户本次明确指定的书籍目录")
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    books_dir = args.books_dir.resolve()
    if not books_dir.is_dir():
        parser.error(f"书籍目录不存在：{books_dir}")
    index_path = args.index.resolve()
    if index_path.is_relative_to(skill_dir):
        parser.error("提取索引不能位于元 Skill 目录内")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if data.get("failed_sources"):
        parser.error("提取索引含失败来源；先修复提取再建立完整项目")
    sources = data.get("sources", [])
    if not sources:
        parser.error("提取索引没有成功来源")

    root = args.output_root.resolve()
    if root.is_relative_to(skill_dir):
        parser.error("项目输出目录必须位于元 Skill 目录之外")
    if root.is_relative_to(books_dir):
        parser.error("项目输出目录不能位于输入书籍目录内")
    for source in sources:
        source_path = Path(source.get("source_file", "")).resolve()
        if not source_path.is_relative_to(books_dir):
            parser.error(f"索引来源不属于用户指定书籍目录：{source_path}")
    ledger = root / "corpus-audit" / "books.json"
    if ledger.exists():
        parser.error(f"项目清单已存在，不覆盖：{ledger}")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(exist_ok=True)
    (root / "corpus-audit" / "books").mkdir(exist_ok=True)

    books = []
    for source in sources:
        number = source["book_index"]
        books.append({
            "book_index": number,
            "title": source["title"],
            "source_file": source["source_file"],
            "primary_theme": None,
            "reading_status": "indexed",
            "overview": f"corpus-audit/books/b{number:02d}-overview.md",
            "coverage": f"corpus-audit/books/b{number:02d}-coverage.md",
        })

    ledger.write_text(json.dumps({
        "schema_version": 1,
        "source_index": str(index_path),
        "books_dir": str(books_dir),
        "themes": [],
        "books": books,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "corpus-audit" / "theme-map.md").write_text(
        "# 主题分类审计\n\n分类须由逐书概览支持；记录每次主题拆分、合并及边界理由。\n",
        encoding="utf-8",
    )
    (root / "corpus-audit" / "coverage.md").write_text(
        "# 逐书方法覆盖审计\n\n逐书列关键方法、来源定位及进入哪个主题 Skill 的去向。\n",
        encoding="utf-8",
    )
    print(f"已建立草稿：{ledger}（{len(books)} 本书，0 个已确认主题）")
    print("阅读与分类状态均未自动完成；正式交付须运行 verify_skill_output.py。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
