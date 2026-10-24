# 主题 Skill 包合同

本合同适用于**用户本次明确指定的书籍目录**。项目根目录由用户指定或在该书籍目录外选择；它不能位于 `hs-books4topic-to-skill/` 内，也不能位于输入书籍目录内。所有提取文件、审计和最终 Skills 共用这个外部项目根目录。通读后、生成 Skills 前须先向用户报告最终主题数和每组书籍归属。

## 项目清单 `corpus-audit/books.json`

```json
{
  "schema_version": 1,
  "source_index": "extracted/all_sources_index.json",
  "books_dir": "/用户指定的书籍目录",
  "themes": [
    {
      "slug": "story-structure",
      "title": "剧作结构与类型",
      "intent": "规划并诊断故事结构与类型节拍",
      "status": "draft"
    }
  ],
  "books": [
    {
      "book_index": 1,
      "title": "书名",
      "source_file": "原始文件路径",
      "primary_theme": "story-structure",
      "reading_status": "indexed",
      "overview": "corpus-audit/books/b01-overview.md",
      "coverage": "corpus-audit/books/b01-coverage.md"
    }
  ]
}
```

- `themes` 是**最终发布主题集合**；每个 slug 唯一，用小写字母、数字和连字符，长度不超过 64。`status` 可为 `draft`、`reviewed`、`ready`。
- `books` 必须与提取索引中的成功来源一一对应，按 `book_index` 和 `source_file` 核对。每本书恰有一个 `primary_theme`；需要跨主题时在来源账本注明次要引用，不重复计算主要归属。
- `books_dir` 记录用户本次指定的目录；来源必须都来自这个目录。不得沿用另一轮任务的语料索引。
- `reading_status` 为 `indexed`、`overviewed`、`read`、`audited`。只有逐书档案及关键方法去向完成后才可写 `audited`。脚本不会自动升级此状态。
- `overview`、`coverage` 是项目根目录下的相对路径。正式发布时必须存在，并有实质内容。
- 索引 `failed_sources` 不可静默忽略。若存在，项目不能宣称覆盖全部输入；先修提取或明确缩小输入范围并重新建立索引。

## 每主题必需文件

```text
skills/<slug>/
├── SKILL.md
├── references/
│   ├── synthesis.md
│   ├── sources.md
│   └── methods/<method>.md
└── evals/
    ├── cases.json
    └── results.json
```

`SKILL.md` 的 frontmatter 必须含 `name: <slug>` 和可区分相邻主题的 `description`。正文必须写任务、触发与排除条件、输入、方法选择、步骤、输出、完成标准及相邻 Skill 边界。只写书籍名单、术语表、提示词或总路由均不合格。

`sources.md` 对每条被采用的关键方法注明原书、章节或稳定分片位置、支持的主张及证据性质。书名列表不等于来源追溯。`synthesis.md` 说明各书贡献、互补或冲突关系、选用条件和舍弃理由。

`evals/cases.json` 至少包含 `should_trigger`、`should_not_trigger`、`neighbor`、`output` 四类真实请求，每条有唯一 `id`、`prompt` 与可检查的 `expected`。`evals/results.json` 按 `id` 记录 `passed`、`observed`、`runner`；必须记录执行环境和运行日期。`results.json` 是测试记录，不是仅靠字段即能证明结果正确的证书。

## 结构门禁与知识门禁

`scripts/verify_skill_output.py <项目根目录>` 只执行可机械检查的部分：清单一致、每书单一归属、主题目录一一对应、必需文件、frontmatter、测试覆盖和未完成状态。它不能自动证明读书质量、引用真实性或真实任务表现。

最终发布还需人工或独立运行核查：至少抽查每书一项重要方法原文；每主题运行正常、缺输入和近邻竞争任务；查看实际交付物与来源仲裁。无法完成的主题保留为草稿，不能宣称“25 本全部完成”。
