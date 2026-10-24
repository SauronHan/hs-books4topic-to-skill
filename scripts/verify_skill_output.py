#!/usr/bin/env python3
"""Check that a multi-book project emits one standalone Skill per theme.

This is a structural gate. Source truth and actual task quality require separate review.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
REQUIRED_CASE_TYPES = {"should_trigger", "should_not_trigger", "neighbor", "output"}
READING_STATES = {"indexed", "overviewed", "read", "audited"}


def load_json(path: Path, errors: list[str]) -> dict:
    if not path.is_file():
        errors.append(f"缺少文件：{path}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"无法读取 JSON：{path}（{exc}）")
        return {}
    if not isinstance(value, dict):
        errors.append(f"JSON 顶层必须是对象：{path}")
        return {}
    return value


def check_text(path: Path, label: str, errors: list[str], minimum: int = 80) -> str:
    if not path.is_file():
        errors.append(f"{label}缺失：{path}")
        return ""
    body = path.read_text(encoding="utf-8", errors="replace")
    if len(body.strip()) < minimum:
        errors.append(f"{label}内容过少：{path}")
    return body


def check_skill(root: Path, theme: dict, errors: list[str], draft: bool) -> None:
    slug = theme.get("slug")
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        return
    skill = root / "skills" / slug
    body = check_text(skill / "SKILL.md", "主题 Skill 入口", errors, 200)
    match = FRONTMATTER.match(body)
    if body and not match:
        errors.append(f"SKILL.md 缺少有效 YAML frontmatter：{skill}")
    elif match:
        fields = match.group(1)
        name = re.search(r"(?m)^name:\s*(\S+)\s*$", fields)
        desc = re.search(r"(?m)^description:\s*(.+)$", fields)
        if not name or name.group(1).strip("'\"") != slug:
            errors.append(f"SKILL.md 的 name 与主题 slug 不一致：{skill}")
        if not desc or len(desc.group(1).strip().strip("'\"")) < 20:
            errors.append(f"SKILL.md 的 description 缺失或不能说明触发任务：{skill}")
    if body and not draft:
        sections = ["触发", "输入", "方法", "输出", "验收", "边界"]
        absent = [section for section in sections if section not in body]
        if absent:
            errors.append(f"SKILL.md 缺少执行合同内容 {absent}：{skill}")

    refs = skill / "references"
    check_text(refs / "synthesis.md", "跨书取舍记录", errors, 150 if not draft else 1)
    check_text(refs / "sources.md", "来源记录", errors, 150 if not draft else 1)
    methods = refs / "methods"
    if not methods.is_dir() or not list(methods.glob("*.md")):
        errors.append(f"主题 Skill 缺少可执行方法卡：{methods}")
    elif not draft:
        for method in methods.glob("*.md"):
            check_text(method, "可执行方法卡", errors, 150)

    cases = load_json(skill / "evals" / "cases.json", errors)
    records = cases.get("cases", [])
    if not isinstance(records, list):
        errors.append(f"cases 必须是数组：{skill}")
        records = []
    seen_ids: set[str] = set()
    case_types: set[str] = set()
    for case in records:
        if not isinstance(case, dict):
            errors.append(f"测试用例必须是对象：{skill}")
            continue
        identifier, kind = case.get("id"), case.get("type")
        if not isinstance(identifier, str) or not identifier or identifier in seen_ids:
            errors.append(f"测试用例 ID 缺失或重复：{skill}")
            continue
        seen_ids.add(identifier)
        if isinstance(kind, str):
            case_types.add(kind)
        if not case.get("prompt") or not case.get("expected"):
            errors.append(f"测试用例缺少 prompt/expected：{skill}/{identifier}")
    if not draft and not REQUIRED_CASE_TYPES.issubset(case_types):
        errors.append(f"测试类型需完整覆盖 {sorted(REQUIRED_CASE_TYPES)}：{skill}")

    results = load_json(skill / "evals" / "results.json", errors)
    if not draft:
        if not results.get("runner") or not results.get("run_date"):
            errors.append(f"测试结果缺少 runner/run_date：{skill}")
        outcomes = results.get("results", [])
        if not isinstance(outcomes, list):
            errors.append(f"测试 results 必须是数组：{skill}")
            outcomes = []
        by_id = {
            row.get("id"): row for row in outcomes
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        for identifier in seen_ids:
            outcome = by_id.get(identifier)
            if not outcome or outcome.get("passed") is not True or not outcome.get("observed"):
                errors.append(f"测试未完成或未通过：{skill}/{identifier}")


def verify(root: Path, draft: bool = False, classification: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    root = root.resolve()
    skill_dir = Path(__file__).resolve().parents[1]
    if root.is_relative_to(skill_dir):
        errors.append("项目输出目录位于元 Skill 目录内")
    ledger = load_json(root / "corpus-audit" / "books.json", errors)
    if not ledger:
        return errors, notes
    if ledger.get("schema_version") != 1:
        errors.append("books.json schema_version 必须为 1")

    books_dir_field = ledger.get("books_dir")
    if not isinstance(books_dir_field, str) or not books_dir_field:
        errors.append("books.json 缺少用户指定的 books_dir")
        books_dir = None
    else:
        books_dir = Path(books_dir_field).resolve()
        if not books_dir.is_dir():
            errors.append(f"用户书籍目录不存在：{books_dir}")
        if root.is_relative_to(books_dir):
            errors.append("项目输出目录位于输入书籍目录内")

    index_field = ledger.get("source_index")
    if not isinstance(index_field, str) or not index_field:
        errors.append("books.json 缺少 source_index")
        index = {}
    else:
        index_path = Path(index_field)
        index_path = index_path if index_path.is_absolute() else root / index_path
        if index_path.resolve().is_relative_to(skill_dir):
            errors.append("提取索引位于元 Skill 目录内")
        index = load_json(index_path, errors)
    if index.get("failed_sources"):
        errors.append("提取索引含失败来源，不能声明完整覆盖")

    themes = ledger.get("themes", [])
    books = ledger.get("books", [])
    if not isinstance(themes, list) or not isinstance(books, list):
        errors.append("themes 和 books 必须是数组")
        return errors, notes
    slugs = [theme.get("slug") for theme in themes if isinstance(theme, dict)]
    if len(slugs) != len(set(slugs)):
        errors.append("主题 slug 重复")
    for theme in themes:
        if not isinstance(theme, dict):
            errors.append("主题条目必须是对象")
            continue
        slug = theme.get("slug")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            errors.append(f"主题 slug 无效：{slug}")
        if not theme.get("title") or not theme.get("intent"):
            errors.append(f"主题缺少 title/intent：{slug}")
        if not draft and not classification and theme.get("status") != "ready":
            errors.append(f"主题尚未达到 ready：{slug}")
    if not themes:
        errors.append("尚未建立任何主题分类")

    expected_sources = {
        (entry.get("book_index"), entry.get("source_file"))
        for entry in index.get("sources", []) if isinstance(entry, dict)
    }
    actual_sources = {
        (book.get("book_index"), book.get("source_file"))
        for book in books if isinstance(book, dict)
    }
    if expected_sources != actual_sources or len(actual_sources) != len(books):
        errors.append("books.json 与提取索引来源不一致，或书籍条目重复")
    if books_dir and books_dir.is_dir():
        for _, source_file in actual_sources:
            if not isinstance(source_file, str) or not Path(source_file).resolve().is_relative_to(books_dir):
                errors.append(f"来源不属于本次用户指定书籍目录：{source_file}")
    for book in books:
        if not isinstance(book, dict):
            errors.append("书籍条目必须是对象")
            continue
        label = f"B{book.get('book_index', 0):02d}"
        if book.get("primary_theme") not in slugs:
            errors.append(f"{label} 未分配有效主要主题")
        if book.get("reading_status") not in READING_STATES:
            errors.append(f"{label} 阅读状态无效")
        elif not draft and not classification and book["reading_status"] != "audited":
            errors.append(f"{label} 尚未完成阅读覆盖审计")
        if not draft and not classification:
            for field, title in (("overview", "逐书档案"), ("coverage", "方法去向")):
                value = book.get(field)
                if not isinstance(value, str) or not value:
                    errors.append(f"{label} 缺少{title}路径")
                else:
                    target = (root / value).resolve()
                    if not target.is_relative_to(root):
                        errors.append(f"{label} {title}路径越界")
                    else:
                        check_text(target, f"{label} {title}", errors, 150)

    if classification:
        notes.append(f"分类草稿：{len(books)} 本来源归入 {len(slugs)} 个候选主题；阅读与独立 Skill 尚未验收")
        return errors, notes

    skills_root = root / "skills"
    actual_skills = {path.name for path in skills_root.iterdir() if path.is_dir()} if skills_root.is_dir() else set()
    if set(slugs) != actual_skills:
        errors.append(f"主题与独立 Skill 目录不一一对应：主题={sorted(slugs)}，目录={sorted(actual_skills)}")
    for theme in themes:
        if isinstance(theme, dict):
            check_skill(root, theme, errors, draft)

    if not draft:
        check_text(root / "corpus-audit" / "theme-map.md", "主题分类审计", errors, 150)
        check_text(root / "corpus-audit" / "coverage.md", "全库覆盖审计", errors, 150)
    notes.append(f"来源 {len(books)} 本；最终主题 {len(slugs)} 个；独立 Skill 目录 {len(actual_skills)} 个")
    notes.append("本检查只覆盖结构与声明；原书事实和实际输出仍需人工或独立运行复核。")
    return errors, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="验证多书主题项目的一主题一独立 Skill 合同")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--draft", action="store_true", help="草稿阶段放宽阅读和测试状态，但仍检查主题与 Skill 一一对应")
    parser.add_argument("--classification", action="store_true", help="只验证来源与初始主题分类，不要求已生成 Skill")
    args = parser.parse_args()
    errors, notes = verify(args.project_root, args.draft, args.classification)
    for note in notes:
        print(note)
    for error in errors[:20]:
        print(f"错误：{error}")
    if len(errors) > 20:
        print(f"另有 {len(errors) - 20} 项错误；修复前述类别后重新运行以查看剩余问题。")
    print("结构检查通过" if not errors else f"结构检查失败：{len(errors)} 项")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
