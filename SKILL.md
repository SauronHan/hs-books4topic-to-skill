---
name: hs-books4topic-to-skill
description: 用户指定书籍目录后，通读其中多本书，按主题分类并融合方法论；先报告主题数量，再为每个主题生成一个独立 Skill，输出到本 Skill 目录之外。适用于“多本书按主题做成一组 Skills”；不用于只要摘要或书单。
license: private
---

# hs-books4topic-to-skill

本 Skill 是独立的**多书 → 多主题 Skills** 生产母机。只有用户为当前运行明确指定书籍目录后才启动；不能自行读取仓库中碰巧存在的书籍或复用以前的语料作为本次输入。输出在本 Skill 目录之外。**最终主题数 K 必须等于独立 Skill 数 K。**每个主题 Skill 均有自己的 `SKILL.md`，可单独安装与使用。不得用一个总路由 Skill、一组构件 MD 或按书名逐本生成的 Skills 代替。

## 运行约定

- 输入前提是**用户明确给出的书籍目录**。未给目录时只询问目录，不扫描默认路径。输出位置由用户指定；若用户未指定，在书籍目录之外选择可写的同级运行目录，并告知路径。提取缓存、审计文件和最终主题 Skills 全部写到该目录，不能写进本元 Skill 目录，也不能混进书籍目录。可选应用目标只用于任务排序，不预设书籍分类。
- 先运行 `scripts/extract_multisource.py --sources <用户书籍目录> --output-dir <外部运行目录>/extracted`；仅当索引确实对应用户本次指定目录且文件状态未变时才可复用。`scripts/inspect_extraction.py` 检查提取质量。分片索引只是阅读材料，不是读完的证据。
- 初读**每一本**书的目录、序言、章节结构与代表性正文，写逐书档案并建立初始主题分类；再在各主题内精读关键章节，修订分类。每书一个主要主题，可有有证据的次要引用。
- 每个主题先列用户会提出的任务，再对组内各书提取方法、案例、反例；按任务比较来源，说明互补、冲突、选择条件与舍弃理由。单本书的方法可以成为主题内能力，不为凑多源强行拼接。
- 对候选逐条检查来源是否支持、能否用新输入执行、能否改善任务结果。未经核实的候选留在待核查记录，不进入活跃执行指令。
- **通读全部指定书籍并修订完主题分类后、生成任何主题 Skill 前**，先向用户报告最终分为多少个主题、各主题名称、包含哪些书及分组理由。报告是进度告知；若用户没有提出调整，继续生成，不把告知变成不必要的批准等待。
- 为**每个最终主题**写一个独立 Skill。入口必须包含触发与排除情境、任务列表、必需输入、方法选择、执行步骤和分支、输出与完成标准、相邻主题边界。来源、案例、术语、参数、提示词等放在该 Skill 的 `references/` 或 `resources/` 按需读取。
- 各主题 Skill 独立测试触发、近邻混淆、实际执行、来源锚点和单独安装可用性。先修失败项，再发布。输出评测报告需区分自动结构检查与实际任务测试。

## 输出合同

```text
<output-root>/
├── corpus-audit/
│   ├── books.json             # 每书主要主题、阅读状态和来源索引 ID
│   ├── theme-map.md           # 主题边界、分组与拆分/合并理由
│   └── coverage.md            # 重要方法及去向
└── skills/
    ├── <theme-a>/
    │   ├── SKILL.md           # 可独立调用的入口
    │   ├── references/
    │   │   ├── synthesis.md   # 多书取舍与冲突仲裁
    │   │   ├── sources.md     # 逐条可定位的原书证据
    │   │   └── methods/       # 可执行方法卡
    │   └── evals/             # 测试用例与结果
    └── <theme-b>/SKILL.md
```

`books.json` 中每书只有一个 `primary_theme`；所有主题 slug 与 `skills/` 下的目录一一对应。完整字段见 [主题包合同](references/topic-skill-contract.md)。用户指定目录完成提取后，可用 `scripts/init_topic_project.py <索引> <外部运行目录> --books-dir <用户书籍目录>` 建立分类草稿；**脚本只建审计骨架，不会代替通读或自动声称分类正确**。交付前运行 `scripts/verify_skill_output.py <外部运行目录>`。

## 需要读的资料

- 分类、精读、跨书取舍及门禁细节：[多书合成流程](references/multibook-workflow.md)；逐书记录可用 [整书档案模板](templates/book_overview_template.md) 和 [方法去向模板](templates/book_coverage_template.md)。
- 写每个主题 Skill 前：[主题包合同](references/topic-skill-contract.md)、[跨书合成模板](templates/topic_synthesis_template.md)、[主题 Skill 模板](templates/topic_skill_template.md)、[方法卡模板](templates/method_card_template.md)。
- 有术语冲突时参考 [跨源术语归一与冲突仲裁指南](references/跨源术语归一与冲突仲裁指南.md)；不能只归一词汇而忽略方法适用条件。

## 发布门禁

1. 输入书籍均有阅读档案、主要主题和关键方法去向；遗漏与提取错误如实报告。
2. 每个最终主题都对应一个独立 Skill 目录，且可单独完成其任务。主题之间的边界通过真实请求检查。
3. 活跃方法有具体原书定位、执行合同、边界和实例；数值区分物理事实、作者经验与新制定的实现约定。
4. `verify_skill_output.py` 的结构检查通过，实际任务测试有留档。静态检查通过不等于知识与效果通过。

现有 `hs-dramaskill/references/building_blocks/` 是待核实的旧素材库，不是本 Skill 的默认输出路径，也不能直接算作主题 Skill。
