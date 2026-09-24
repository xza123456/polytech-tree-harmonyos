# 数据许可 / Data licensing (`data/`)

本仓库 `data/` 目录的许可分为两部分，因为它们的来源不同。

## 1. 结构化字段：CC BY 4.0

`id`、`name`、`nameEn`、`wikiEn`、`aliases`、`year`、`year_basis`、`year_span`、`year_note`、
`era`、`category`、`kind`、`importance`、`prereqs`、`related` 这些字段是本项目的编排与判断成果
（哪一项技术、定在哪一年、属于哪个领域、依赖谁），以 **CC BY 4.0** 发布：

> You are free to Share and Adapt, in any medium or format, for any purpose,
> even commercial, provided you give appropriate credit, link to the licence,
> and indicate if changes were made.
> <https://creativecommons.org/licenses/by/4.0/>

署名建议：`Polytech Tree (github.com/secwind7/polytech-tree), CC BY 4.0`。

## 2. `desc` 摘要文字：含源自英文维基百科的内容，按 CC BY-SA 4.0 提供

`desc` 是本项目的中文摘要。其中一部分（尤其早期批次与部分定义句）参考了英文维基百科对应条目的
导语；英文维基文字本身以 **CC BY-SA 4.0** 发布，其翻译与改写属于衍生作品，因此**这部分文字继续
按 CC BY-SA 4.0 授权**，并据此署名：

> 部分条目的中文摘要参考了 Wikipedia contributors, "（对应英文条目标题见该条目的 `wikiEn` 字段）,"
> *Wikipedia, The Free Encyclopedia*, https://en.wikipedia.org/wiki/（同 `wikiEn`），
> 以 CC BY-SA 4.0 发布（https://creativecommons.org/licenses/by-sa/4.0/）。

再分发这部分文字时须同样以 CC BY-SA 4.0 释放（ShareAlike）。每条摘要对应的具体英文条目可由
`wikiEn` 与 `aliases` 定位；无法定位者视为纯原创内容，归入第 1 节的 CC BY 4.0。

## 3. 事实本身的地位

年代、人名、依赖关系是事实与编排判断；本文件不主张对事实本身的专有权利，许可只覆盖本仓库的
表达形式。技术"首次出现"的年代在学界常存争议，本库给出的是本编选定的取值（见 `year_basis`）。
