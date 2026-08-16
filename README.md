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
├── test-rating-aggregator.py # 聚合器测试
├── test-quarterly-review-judge.py    # 季度人评判定测试（P1-9，22 条用例）
├── test-anti-distortion-rules.py     # 防失真修正层测试（P1-10，19 条用例）
├── test-rating-settler.py     # 结算器测试（归属解析 6 条 + S-1 去重键 4 条）
├── test-review-scheduler-category.sh  # 调度器 category 解析验收测试
└── test-anti-fraud-scheduler.sh       # 调度器 check_anti_fraud 集成验收（P1-10）
scripts/                      # 运维层（定时任务包装脚本，P0-3）
├── run-daily-settlement.sh   # 每日 00:30 结算包装脚本（守卫 + 日志 + 退出码）
├── run-monthly-aggregation.sh# 月末聚合包装脚本（守卫：当月最后一天）
├── run-quarterly-review.sh   # 季度人评触发包装脚本（守卫：季末最后 3 天）
├── audit-events.py           # 流水审计（事件对账 / 重复检测 / 修复建议）
└── tasks/                    # autopilot 派发的任务提示模板（三任务各一）
config/
├── rating-benchmarks.conf    # 共享基准配置（category → 基准分）
└── crontab-rating.conf       # 三定时任务 cron 配置（每日结算 / 月末聚合 / 季度人评）
docs/
├── rating-aggregator-test-report.md  # 聚合器测试报告
├── quarterly-review-judge-test-report.md  # 季度人评自动判定测试报告（P1-9）
└── runbook.md                # 评分系统定时任务 Runbook（P0-3）
reports/                       # 报告为生成产物不入库（已 .gitignore）；归档见「报告归档」节
```

## P0 交付物（评分系统脚本）

- 来源：KA-16（P0-1 聚合器，已验收）、KA-43（调度器 R-42 修复版，代码审查员验收：9 目标一致 / 幂等 / 无回归）、KA-18（P0-3 定时任务部署 cron：包装脚本 + `crontab-rating.conf` + runbook + `audit-events.py`，owner 终审通过 / SRE 条件通过后修复 F1/F2 并回填证据）。
- 与生产同步：本仓库内容与生产树 `<WORKSPACE>/prod/rating-system/` 保持「仓库 == 生产」一致；生产树 commit `c576a01`（工作区干净）。
- 待补充：KA-19 P0-4 重试注入测试；KA-20 P0-5 过滤回归报告。

## 报告归档（Release）

月度/季度评分报告为聚合器运行生成的产物，不进入代码仓库，统一归档至 GitHub Release：

- [reports-2026-08-Q3 · P0 评分系统报告归档（116 份月度/季度报告）](https://github.com/kzh8175-dot/multica-skills/releases/tag/reports-2026-08-Q3)

## 说明

- 仓库初始提交（initial commit）已建立基础目录骨架；P0 评分系统脚本已并入（2026-08-16），KA-18 运维层于 2026-08-16 同步并入。
- 各目录的具体内容由对应负责智能体提供，由仓库管理员统一提交推送。
- 任何智能体如遇 checkout 失败，先确认仓库非空且有 `main` 分支，再删除本地缓存重试。
