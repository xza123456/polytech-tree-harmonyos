# 贡献指南 CONTRIBUTING

数据都在 `data/` 下的普通 JSON 文件里，不需要改代码就能新增科技。改完跑一次校验，没有 `错误` 就可以提 PR。

```bash
npm install
npm run validate        # 等价于 python scripts/validate_data.py
```

校验失败时进程返回非零并打印每条问题，`data/validate-report.json` 是完整报告（该文件被 gitignore，不要提交）。

---

## 1. 新增一条科技

编辑 `data/techs.json`，在数组里加一个对象。字段全部必填（`wikiEn` / `aliases` 可以为空字符串 / 空数组）：

```json
{
  "id": "transistor",
  "name": "晶体管",
  "nameEn": "Transistor",
  "wikiEn": "Transistor",
  "aliases": ["点接触晶体管"],
  "year": 1947,
  "era": "atomic_electronic",
  "category": "information",
  "importance": 1,
  "prereqs": ["semiconductor_theory"],
  "related": ["integrated_circuit"],
  "desc": "贝尔实验室点接触晶体管，现代电子学的开关基石。"
}
```

| 字段 | 规则 |
|---|---|
| `id` | 全库唯一，小写英文加下划线，语义化（`steam_engine` 而不是 `t123`）。`prereqs` / `related` 引用的就是这个 id |
| `name` | 中文名。留空会警告，界面上回退显示 `nameEn` |
| `nameEn` | 英文名，与英文维基条目名保持一致 |
| `wikiEn` | 英文维基条目标题（不带 URL 前缀）。留空会警告 |
| `aliases` | 中英文别名数组，用于搜索，可为 `[]` |
| `year` | 整数，公元前的年份用负数（前 30 万年 = `-300000`） |
| `era` | **不要手填**，由 `year` 查 `eras.json` 的区间得出，见第 2 节。填错直接报错 |
| `category` | 必须是 `categories.json` 里已有的 `id` |
| `importance` | 整数 1–5，1 最高。含义见第 4 节 |
| `prereqs` | 前置科技 id 数组。引用不存在的 id 会警告；前置年份晚于本条会警告 |
| `related` | 同级关联科技 id 数组，规则同上 |
| `desc` | 一句话中文简介，超过 40 字会警告 |

`prereqs` 与 `related` 各自超过 4 条会警告 —— 塔上的连线一多就糊成一片了，请只保留最能说明"为什么它必须存在"的那几条。

### `desc` 必须独立撰写，不得翻译英文导语

`desc` 是这个项目的差异化内容。它是你用自己的话讲清"这条科技解决了什么问题、为什么后面的科技站在它上面"，不是英文维基导语的汉译。

- ✅ 允许与英文导语在**事实层面**重合：年份、人名、术语、因果，事实不受版权保护
- ✅ 允许句序与英文完全不同，鼓励带上该条目在科技树里的位置感
- ❌ 逐句对应英文导语的句序与修辞。反例：`a powerful tool to evaluate line integrals... it can often be used to compute real integrals and infinite series as well` → "给出实积分与级数求和利器"
- ❌ 搬运英文里带个人风格的比喻或固定搭配。反例：`batteries-included standard library` → "电池自备"

自检方法：写完把你的中文句和英文页首句并排读一遍。如果你的中文句序能被英文句序**解释**（即"照原文翻一遍就长这样"），那就是翻译，重写一遍 —— 通常做法是先合上英文页，只按自己的理解写，再打开核对事实。

> 背景：`desc` 应为原创中文改写，不要照着英文导语逐句译。早期批次有部分条目贴着英文写成，仓库不再安排全库重写，而是把这部分按 **CC BY-SA 4.0**（署名英文维基贡献者）发布——因为维基文字是相同方式共享，翻译算衍生作品，不能改以 CC BY 释放。结构化字段仍是 CC BY 4.0，详见 `LICENSE-data.md`。

## 授权声明（提 PR 前必读）

提交贡献即表示：你确认自己是该贡献的作者或有权提交，同意按仓库当时的许可证发布该贡献，并**额外授予仓库管理方以其他许可再分发该贡献的权利**。后者是显式声明，比 GitHub 服务条款的默认规则更宽，目的是让项目日后仍能整体迁移许可证（例如从 CC BY 迁到 ODbL）。不接受此条款请勿提交。

## 2. era 由 year 推导

`eras.json` 里每个时代是一段半开区间 `[yearStart, yearEnd)`，只有最后一个时代额外包含自己的 `yearEnd`。校验器会用 `year` 反查区间，和 `era` 字段比对，不一致就报错。

批量修正：

```bash
python scripts/recompute_era.py
```

新增时代时，新区间必须和相邻时代严丝合缝地接上，不能重叠也不能留空隙，`order` 决定塔里从下到上的次序。

## 3. 新增一个领域

编辑 `data/categories.json`：

```json
{
  "id": "agriculture_food",
  "name": "农牧·食品",
  "nameEn": "Agriculture and Food",
  "color": "#a8c94a",
  "polyhedron": "cube",
  "archimedean": false,
  "subcategories": ["农具", "灌溉", "育种", "食品加工"]
}
```

只有 `id`、`name`、`color` 真正被渲染使用（`id` 被 `techs.json` 引用，`color` 是节点颜色和图例色块）。`polyhedron` / `archimedean` / `subcategories` 目前是描述性元数据，渲染器不读取 —— 节点形状只由 `importance` 决定（20/12/8/6/4 面对应 1–5 档）。

注意塔的圆周按领域数量等分，加一个领域会让所有现有扇区变窄。如果新领域和已有领域高度重叠，优先考虑放进 `subcategories` 而不是新开一个。

## 4. importance 怎么定档

| 档 | 面数 | 含义 | 例 |
|---|---|---|---|
| 1 | 20 | 基石：后续一大片领域都建立在它之上 | 火、轮、晶体管 |
| 2 | 12 | 领域支柱 | 蒸汽机、DNA 结构 |
| 3 | 8 | 领域内重要 | 感应电动机 |
| 4 | 6 | 改良与细分 | 超外差接收机 |
| 5 | 4 | 长尾补充 | 具体机型、单一工艺 |

判据是"抽掉它，后面有多少条科技站不住"，不是"它出名不出名"。同一时代同领域里 1 档应当是少数。

## 5. core-ids.json 注册表

`data/core-ids.json` 钉住一批核心科技的 `era` / `category` 归属，防止后续批量编辑把它们挪错层。如果你改动的条目在注册表里，它的 `era` / `category` 必须和注册表一致，否则校验报错。确实需要改归属时，同一个 PR 里把注册表一起改掉并说明理由。

## 6. 提 PR 之前

- [ ] `npm run validate` 零错误（警告可以有，但请在 PR 描述里说明）
- [ ] `npm run build` 通过（TypeScript 类型检查 + 打包）
- [ ] 每条新增科技都有可查的来源，`wikiEn` 填对应英文条目名
- [ ] 新增 `desc` 按上文自检过，是独立概括而不是英文导语的翻译
- [ ] 没有提交 `data/*.bak-*`、`data/*-report.json`、`data/von-*.json`、`data/jev-*.json` 这类本地生成物
- [ ] 没有为了少改数据而修改 `src/` 的渲染逻辑 —— 数据和视图分开，纯数据 PR 更容易审

## 7. 调研记录

`data/research/` 按时代保存批量整理的原始记录，文件名是 `序号-时代.json`。新加一批科技时，把整理过程一并放进来，方便后来者追溯某条年份是从哪来的。这是可选的，但对成批新增很有用。
