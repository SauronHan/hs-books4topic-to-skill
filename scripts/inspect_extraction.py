#!/usr/bin/env python3
"""Inspect a multisource extraction index without modifying source documents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


GENERIC_TITLES = {"full document", "section", "chapter", "untitled"}


def audit(index_path: Path) -> tuple[list[str], list[str], list[str]]:
    data = json.loads(index_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    for failed in data.get("failed_sources", []):
        errors.append(f"提取失败：{failed.get('source_file', '未知来源')}；{failed.get('reason', '未说明原因')}")

    for source in data.get("sources", []):
        label = f"B{source.get('book_index', 0):02d}《{source.get('title', '未命名来源')}》"
        chapters = source.get("chapters", [])
        chars = source.get("total_chars", 0)
        if not chars or not chapters:
            errors.append(f"{label}：没有有效文本或分片")
            continue

        titles = [str(chapter.get("title", "")).strip() for chapter in chapters]
        normalized = [title.casefold() for title in titles if title]
        unique_ratio = len(set(normalized)) / len(normalized) if normalized else 0
        if len(chapters) == 1:
            warnings.append(f"{label}：只有一个分片；正式融合前需按真实目录／页码重建定位")
        positions: dict[str, list[int]] = {}
        for index, title in enumerate(normalized):
            positions.setdefault(title, []).append(index)
        discontinuous = [
            title for title, indexes in positions.items()
            if indexes[-1] - indexes[0] + 1 != len(indexes)
        ]
        if discontinuous:
            preview = "、".join(discontinuous[:3])
            warnings.append(f"{label}：章节标题在 spine 中非连续回跳（如 {preview}）；需检查目录映射或阅读顺序")
        generic_count = sum(
            1 for title in normalized if title in GENERIC_TITLES or title.startswith("section ")
        )
        if len(chapters) >= 6 and generic_count / len(chapters) > 0.5:
            warnings.append(f"{label}：多数标题为通用占位名；不得将分片号当作书籍章节号")
        notes.append(f"{label}：{len(chapters)} 个分片，{chars:,} 字符，标题唯一率 {unique_ratio:.0%}")

    if not data.get("sources"):
        errors.append("索引中没有有效来源")
    return errors, warnings, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="审计 hs-books4topic-to-skill 的提取来源质量")
    parser.add_argument("index", type=Path, help="all_sources_index.json 路径")
    parser.add_argument("--report", type=Path, help="可选 Markdown 报告输出路径")
    parser.add_argument("--fail-on-warnings", action="store_true", help="将人工复核警告也作为非零退出")
    args = parser.parse_args()

    errors, warnings, notes = audit(args.index)
    lines = ["# 多源提取质量报告", "", "## 来源状态", *[f"- {note}" for note in notes]]
    if warnings:
        lines.extend(["", "## 需要人工复核", *[f"- {warning}" for warning in warnings]])
    if errors:
        lines.extend(["", "## 阻断项", *[f"- {error}" for error in errors]])
    if not warnings and not errors:
        lines.extend(["", "## 结论", "- 未发现自动化阻断项或目录质量警告。"])

    report = "\n".join(lines) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    print(report, end="")
    return 1 if errors or (args.fail_on_warnings and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
