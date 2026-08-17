# 智能看板 · 数据接口契约（KA-96 里程碑 1 · KA-97 迭代 0 收敛 · KA-98 迭代 1 分页）

> 归属：KA-96 智能看板研发立项 · 协作人：开发者工具工程师（聚合器/结算数据接口对接）
> 面向：前端工程师（页面实现）、数据可视化工程师（真实数据接入 + 图表）
> 状态：接口 v1.0 已落地（`src/dashboard-data-feed.py`）；KA-97 迭代 0 完成**单一数据源收敛**；KA-98 #7 完成 **CLI 分页拉取**（35 条测试全通过）

## 0. 单一数据源收敛（KA-97 · #3）

- **唯一数据源**：智能看板 8 页的真实数据只由 `src/dashboard-data-feed.py`
  （Schema v1.0）聚合产出；前端通过 `generate-dashboard-data.py` 消费本接口，
  不再有任何第二处数据管线。
- **loader 删除**：早期并行管线 `dashboard-data-loader.py`（未在任何仓库交付，
  输出口径分叉：agent 数 60 vs 63、排名含无数据智能体、季度客观均值全员分母、
  等级分布预估全 0）已随迭代 0 **删除**，杜绝双管线分叉。
- **分叉口径清理**：前端只消费 feed；无数据智能体（E_MISS）不参与排名；
  季度均值/等级分布以有数据智能体为分母计算。
- **回归锁定**：`src/test-dashboard-data-feed.py` 新增 4 条用例——
  `TestSingleSourceConvergence` 3 条（发现范围含四目录 / Schema v1.0
  无 loader 字段契约 / 单一源覆盖全部智能体）+ 事件多事件 `;` 原始串契约 1 条
  （loader 12 用例并入后，feed 套件 22 条全通过）。

## 0.1 CLI 分页拉取（KA-98 · #7）

- **背景**：预算与 rating.status 计数经 `multica issue list` 只读拉取，旧实现单次
  `--limit 200`，工作区 issue >200 时静默截断尾部（预算条目漏、pending 计数偏少）。
- **修复**：`fetch_all_issues()` 按页拉取（`--limit/--offset`），直到空页 / 非满页 /
  `has_more=false` / 达最大页数（25 页 × 200），并对分页期间新插入 issue 按 id 去重。
  预算/pending 计数全量覆盖，不再有 200 上限截断；后续页失败时降级返回已拉取部分
  并附 `note` 说明。
- **回归**：`TestCliPagination` 13 条——超量（>200）时预算/pending 跨页不漏、
  精确倍数、空工作区、CLI 不可用、中途页失败部分返回、达最大页数、老 CLI 裸数组、
  跨页去重、note 传播。

## 1. 一句话

看板 8 页的**全部真实数据**由只读脚本 `src/dashboard-data-feed.py` 一次性聚合为
**单一 JSON 接口**，页面前端只消费这一份 JSON —— 由此保证「跨页数值同源、
口径一致」（等级分布 / 季度均值 / 降档统计 / 排名全站来自同一解析）。

脚本**只读、幂等、不写任何文件**；同输入必得同输出（`--no-cli` 下完全确定）。

## 2. 运行方式

```bash
# 生产（agents 根 = 生产树 agents 目录）
python3 src/dashboard-data-feed.py --agents-dir <生产>/rating-system/agents --pretty

# 当前月 + 当前季度
python3 src/dashboard-data-feed.py --pretty
# 指定周期 / 单智能体 / 全量扫描
python3 src/dashboard-data-feed.py --month 2026-08 --quarter 2026-Q3 --agent "开发者工具工程师" --pretty
python3 src/dashboard-data-feed.py --all --pretty
# 离线（不调用 multica：预算/运行态计数缺省）—— CI/演示用
python3 src/dashboard-data-feed.py --no-cli --pretty
```

测试：`python3 src/test-dashboard-data-feed.py`（35 条，含只读性校验 + 单一源收敛回归 + CLI 分页）。

## 3. 数据来源（口径 = 与评分系统同源）

| 看板数据 | 来源 | 生产脚本 | 口径 |
|----------|------|----------|------|
| 月度百分制 R-41 | `reviews/scoring/monthly/{agent}/{YYYY-MM}.md` | `rating-aggregator.py` | clamp(月积分÷基准×100, 0, 120) |
| 季度客观分 R-51 | `reviews/scoring/quarterly/{agent}/{YYYY-Qn}.md`「一、」 | `rating-aggregator.py` | (M1+M2+M3)/3，缺失月按 0 计 |
| 人评分 R-52/53 | 同季度表单「二、」已填值 | `quarterly-review-judge.py` | Σ(维度×权重)×20；多评分人平均 |
| 季度综合 R-61 | 同季度表单「三、」 | `quarterly-review-judge.py` | 客观×0.8 + 人评×0.2 |
| 等级 R-62~66 | 同季度表单「三、」 | `quarterly-review-judge.py` | ≥95 S / 85 A / 70 B / 60 C / <60 D |
| 事件流水 | `reviews/scoring/events/{agent}/{YYYY-MM}.md` | `rating-settler.py` | `时间\|任务(issue)\|事件\|积分` |
| 防失真标记 | 季度表单「四、」+ `reviews/scoring/anti-distortion/{agent}/{YYYY-Qn}.md` | `anti-distortion-rules.py` | R-71 上限C / R-72 降档 / E-02 上限A |
| 预算 | issue metadata `budget.ceiling/spent/variance` | `multica issue list`（只读 CLI） | variance>0 即超支 |
| 运行态 | 目录文件 mtime + `rating.status` 计数 | 本脚本推导 | 每日结算 / 月末聚合 / 季度人评 最近运行时基 |

## 4. 输出 Schema（v1.0）

```jsonc
{
  "meta": { "generated_at", "agents_root", "months", "quarters",
            "schema_version", "read_only": true },
  "agents": [
    { "name", "category",            // execution/data/marketing/creative/technical
      "category_source",             // "cli" | "profile" | "inferred"
      "benchmark",                   // R-42 基准月积分
      "profile_exists" }
  ],
  "monthly": {
    "2026-08": {
      "开发者工具工程师": { "total", "benchmark", "score", "flags": ["E_PARSE: …"] }
    }
  },
  "quarterly": {
    "2026-Q3": {
      "开发者工具工程师": {
        "objective",                 // R-51（真实）
        "human_final",               // R-53（null = 人评待运行）
        "comprehensive",             // R-61（null = 待运行）
        "grade",                     // S/A/B/C/D（null = 待运行）
        "review_state",              // "judged" | "pending"
        "estimated": {               // 仅 pending 时出现 → 预估值
          "comprehensive", "grade", "basis": "objective_only",
          "as_of"                    // 时基：聚合器最后一次写报告时间
        },
        "anti_fraud": { "r71", "r72", "e02" },
        // e02 仅当 review_state==judged 且含 judge 回填标记「（E-02 单评分人」
        // 时为 true；模板静态描述「E-02: 单评分人可用，等级上限A」不触发
        // （KA-96 代码审查阻塞项修复，避免 pending 表单误标）
        "flags": ["E_MISS: …"]
      }
    }
  },
  "events": {
    "2026-08": {
      "开发者工具工程师": { "total", "rows": [{ "time", "issue", "event", "points" }], "flags" }
    }
  },
  "anti_distortion": {
    "2026-Q3": {
      "开发者工具工程师": { "auto_grade", "final_grade",
                          "counts": {"r31","r32"},
                          "corrections": [{ "rule","action","from","to" }] }
    }
  },
  "budget": {
    "entries": [ { "issue","identifier","title","status",
                   "ceiling","spent","variance" } ],  // 只含带 budget.* 的 issue
    "note": null | "offline（--no-cli）"
  },
  "runtime": {
    "settlement_last_run", "aggregation_last_run", "review_last_run",  // UTC 时基
    "budget_reconciliation",                       // 预留：预算对账时基
    "rating_status": { "pending", "escalated", "credited" },
    "rating_status_note"
  }
}
```

## 5. 页面 → 字段映射（数值同源）

| 页面 | 主数据 | 交叉口径 |
|------|--------|----------|
| 总览 | `monthly`/`quarterly` KPI + `runtime` | 等级分布 = 各 agent `quarterly.grade`（pending 用 `estimated.grade` 标「预估值」） |
| 排行榜 | `agents` + `quarterly` | 排名键 = `quarterly.comprehensive`（pending 用 `estimated.comprehensive` 并标注） |
| 趋势 | `monthly[各月]` | 同 agent 跨月 `monthly.score` 时序 |
| 评分明细 | `quarterly` 单 agent 全字段 | `anti_fraud` + `flags` 独立呈现 |
| 事件流水 | `events` | `event` 前缀 R-xx / E-xx 标签 |
| 预算 | `budget.entries` | 进度 = `spent/ceiling`；超支 = `variance > 0` |
| 升级队列 | `agents.category` + `quarterly.grade` | 按等级/类别过滤待晋升名单 |
| 异常中心 | `runtime.rating_status` + `monthly/quarterly.flags` | pending 滞留 / E-xx / escalated |

**口径一致性约定**：任何「预估」数值必须在 UI 上标注 `estimated.basis + as_of`
（即「人评待运行·预估值」，时基 = 聚合器最后写报告时间）；真实数值（objective/
judged 综合分/等级）直接呈现，不加标注。

## 6. 与前端/数据可视化工程师的接口约定

- 前端只读 `stdout` 的 JSON；**不直接解析 `reviews/scoring` 下的 markdown 文件**，
  解析口径已全部收敛在本脚本（避免各页各自解析导致口径分叉）。
- 如需新增字段/新页面数据，改 `build_feed()` 并在 `test-dashboard-data-feed.py`
  补用例（纯函数 + 集成各一条）。
- 本脚本在仓库 `src/` 维护，由 GitHub 仓库管理员统一推送；生产运行时以
  `--agents-dir` 指向生产树。

---
*开发者工具工程师 · KA-96 里程碑 1（数据接口打通）· KA-97 迭代 0（单一数据源收敛）*
