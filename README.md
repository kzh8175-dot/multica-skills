# multica-skills

Multica 工作室的共享技能与能力体系资料库。所有智能体的能力档案、评分系统脚本、评审记录统一存放在本仓库，由 **GitHub 仓库管理员** 负责维护（创建、更新、评审、推送）。

## 目录结构

```
agents/
├── capability-system/        # 能力评分系统脚本、模板、检查清单
├── profiles/                 # 各智能体能力档案
│   └── <智能体名>/capabilities.md
└── reviews/                  # 评审与评分运行数据
    ├── weekly/               # 周度自我审查
    ├── monthly/              # 月度自我审查
    └── scoring/              # 评分系统运行
        ├── events/           # 积分事件流水（输入）
        ├── monthly/          # 月度百分制报告（输出）
        ├── quarterly/        # 季度客观分报告（输出）
        └── logs/             # 结算/聚合/人评日志
src/                          # 评分系统核心脚本（P0/P1 交付物）
├── rating-aggregator.py      # 聚合器（月度 R-41 / 季度 R-51）
├── rating-settler.py         # 结算器（每日结算；SRE F1/F2 修复版：实时 agent 映射 + 跨文件全局去重 + S-1 (issue,事件) 去重键）
├── review-scheduler.sh       # 调度器（含 R-42 description [category=X] 标签解析）
├── quarterly-review-judge.py # 季度人评表单自动判定（P1-9：客观/人评/综合/等级 回填）
├── anti-distortion-rules.py  # 防失真修正层（P1-10：R-71 红线上限 C / R-72 缺自评降档，纯函数）
├── state-change-hook.py      # 状态变更钩子（P2-11：完成/失败/返工自动写 R-01~R-04 事件）
├── dashboard-data-feed.py    # 智能看板只读数据接口（KA-96：月度/季度/事件/防失真/预算/运行态 → JSON；KA-97 单一数据源）
├── test-rating-aggregator.py # 聚合器测试
├── test-quarterly-review-judge.py    # 季度人评判定测试（P1-9，22 条用例）
├── test-anti-distortion-rules.py     # 防失真修正层测试（P1-10，19 条用例）
├── test-rating-settler.py     # 结算器测试（归属解析 6 条 + S-1 去重键 4 条）
├── test-state-change-hook.py  # 状态变更钩子测试（P2-11，50 条用例，含 main() 集成 6 条）
├── test-dashboard-data-feed.py # 看板数据接口测试（KA-96，35 条用例，含只读性校验 + KA-97 单一源收敛回归 + KA-98 CLI 分页）
├── test-review-scheduler-category.sh  # 调度器 category 解析验收测试
└── test-anti-fraud-scheduler.sh       # 调度器 check_anti_fraud 集成验收（P1-10）
scripts/                      # 运维层（定时任务包装脚本，P0-3）
├── run-daily-settlement.sh   # 每日 00:30 结算包装脚本（守卫 + 日志 + 退出码）
├── run-state-change-hook.sh  # 状态变更钩子包装脚本（P2-11，00:20 结算前运行）
├── run-monthly-aggregation.sh# 月末聚合包装脚本（守卫：当月最后一天）
├── run-quarterly-review.sh   # 季度人评触发包装脚本（守卫：季末最后 3 天）
├── audit-events.py           # 流水审计（事件对账 / 重复检测 / 修复建议）
└── tasks/                    # autopilot 派发的任务提示模板（三任务各一）
config/
├── rating-benchmarks.conf    # 共享基准配置（category → 基准分）
└── crontab-rating.conf       # 四定时任务 cron 配置（状态钩子 / 每日结算 / 月末聚合 / 季度人评）
docs/
├── rating-aggregator-test-report.md  # 聚合器测试报告
├── quarterly-review-judge-test-report.md  # 季度人评自动判定测试报告（P1-9）
├── dashboard-data-interface.md       # 智能看板数据接口契约（KA-96，Schema v1.0 + 8 页字段映射）
├── runbook.md                # 评分系统定时任务 Runbook（P0-3）
├── system-report-spec.md     # 系统报告整合规范（P2-15：周报/月报/季度报告统一输出 + 归档）
└── report-templates/         # 系统报告统一模板（周报/月报/季度报告三份，P2-15）
reports/                       # 报告为生成产物不入库（已 .gitignore）；归档见「系统报告」节
```

## P0 交付物（评分系统脚本）

- 来源：KA-16（P0-1 聚合器，已验收）、KA-43（调度器 R-42 修复版，代码审查员验收：9 目标一致 / 幂等 / 无回归）、KA-18（P0-3 定时任务部署 cron：包装脚本 + `crontab-rating.conf` + runbook + `audit-events.py`，owner 终审通过 / SRE 条件通过后修复 F1/F2 并回填证据）。
- 与生产同步：本仓库内容与生产树 `<WORKSPACE>/prod/rating-system/` 保持「仓库 == 生产」一致；生产树 commit `c576a01`（工作区干净）。
- 待补充：KA-19 P0-4 重试注入测试；KA-20 P0-5 过滤回归报告。

## 系统报告（统一输出与归档 · P2-15）

三类系统运行报告统一输出骨架与归档口径，见 **[系统报告整合规范](docs/system-report-spec.md)**，
统一模板见 **[docs/report-templates/](docs/report-templates/)**（周报/月报/季度报告三份）。

| 报告类型 | 周期 | 执行人(R) | 模板 | 归档 |
|----------|------|-----------|------|------|
| 系统监控周报（P2-13） | 每周五 | SRE稳定性工程师 + 数据可视化工程师 | [周报模板](docs/report-templates/weekly-report-template.md) | GitHub Release（产物） |
| 月度百分制报告（R-41） | 每月末 | 自动化（`rating-aggregator.py`） | [月报模板](docs/report-templates/monthly-report-template.md) | GitHub Release（产物） |
| 季度综合评分报告（R-51 + 人评） | 每季末 | 自动化 + `quarterly-review-judge.py`（P1-9） | [季度报告模板](docs/report-templates/quarterly-report-template.md) | GitHub Release（产物） |

**归档原则**：报告为生成产物，不入代码仓库（`reports/` 已 `.gitignore`），统一打包发布至
GitHub Release；规范/模板/索引入库维护。

- [reports-2026-08-Q3 · P0 评分系统报告归档（116 份月度/季度报告）](https://github.com/kzh8175-dot/multica-skills/releases/tag/reports-2026-08-Q3)

## 说明

- 仓库初始提交（initial commit）已建立基础目录骨架；P0 评分系统脚本已并入（2026-08-16），KA-18 运维层于 2026-08-16 同步并入。
- 各目录的具体内容由对应负责智能体提供，由仓库管理员统一提交推送。
- 任何智能体如遇 checkout 失败，先确认仓库非空且有 `main` 分支，再删除本地缓存重试。
